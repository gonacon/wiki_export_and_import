import os
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from .config import OLD_BASE, old_session, EXPORT_DIR, MAX_WORKERS, MAX_RETRIES, RETRY_DELAY
from .utils import safe_folder_name, fix_image_links_html, md_convert, convert_images_to_inline, fix_url_images_in_html
from .sanitizer import Sanitizer
from .io_utils import save_page_files, download_attachments_for_page, load_resume_state, save_resume_state, ensure_export_pages_dir, download_gliffy_thumbnails, save_page_files_v2
import logging

logger = logging.getLogger("wiki_migrate")


def sort_pages_by_hierarchy(pages):
    from collections import defaultdict
    page_map = {p['id']: p for p in pages}
    children_map = defaultdict(list)
    roots = []
    for p in pages:
        ancestors = p.get('ancestors', [])
        if ancestors:
            parent_id = ancestors[-1]['id']
            if parent_id in page_map:
                children_map[parent_id].append(p)
            else:
                roots.append(p)
        else:
            roots.append(p)
    sorted_pages = []
    def traverse(page):
        sorted_pages.append(page)
        for child in children_map.get(page['id'], []):
            traverse(child)
    for r in roots:
        traverse(r)
    if len(sorted_pages) < len(pages):
        visited = set(p['id'] for p in sorted_pages)
        for p in pages:
            if p['id'] not in visited:
                sorted_pages.append(p)
    return sorted_pages


def get_all_pages(old_session, old_base, space, root_page_id=None):
    if root_page_id:
        return get_descendant_pages(old_session, old_base, root_page_id)
    pages = []
    start = 0
    limit = 100
    while True:
        url = f"{old_base}/rest/api/content"
        params = {"spaceKey": space, "limit": limit, "start": start, "expand": "body.storage,ancestors"}
        r = old_session.get(url, params=params)
        data = r.json()
        results = data.get('results', [])
        if not results:
            break
        pages += results
        start += limit
    logger.info(f"전체 페이지 수집 완료: {len(pages)}개")
    return sort_pages_by_hierarchy(pages)


def get_descendant_pages(old_session, old_base, root_page_id):
    pages = []
    url = f"{old_base}/rest/api/content/{root_page_id}"
    r = old_session.get(url, params={"expand": "body.storage,ancestors"})
    root = r.json()
    pages.append(root)
    def collect_children(page_id):
        start = 0
        limit = 100
        while True:
            url = f"{old_base}/rest/api/content/{page_id}/child/page"
            params = {"limit": limit, "start": start, "expand": "body.storage,ancestors"}
            r = old_session.get(url, params=params)
            results = r.json().get('results', [])
            if not results:
                break
            for c in results:
                pages.append(c)
                collect_children(c['id'])
            start += limit
    collect_children(root_page_id)
    logger.info(f"하위 페이지 수집 완료 (root={root_page_id}): {len(pages)}개")
    return pages


def process_page(i, page, inline_images, resume_state, old_session=old_session):
    page_id = page['id']
    if page_id in resume_state.get('downloaded', []):
        return page_id, True, None
    try:
        html = page['body']['storage']['value']

        # 폴더 먼저 생성
        title = page.get('title', 'untitled')
        folder = os.path.join(EXPORT_DIR, "pages", f"{i:04d}_{safe_folder_name(title)}")
        os.makedirs(os.path.join(folder, "attachments"), exist_ok=True)

        # ✨ URL 이미지 다운로드 및 HTML 변환
        html = fix_url_images_in_html(html, os.path.join(folder, "attachments"), old_session)

        # 기존 로직
        html_local = fix_image_links_html(html, os.path.join(EXPORT_DIR, 'pages'))
        markdown = md_convert(html_local, heading_style='ATX')  # ← globals() 체크 제거

        # 파일 저장
        save_page_files_v2(page, folder, html, markdown)

        # 일반 첨부파일 다운로드
        download_attachments_for_page(page, folder)

        # Inline images 처리
        if inline_images:
            md_path = os.path.join(folder, 'page.md')
            if os.path.exists(md_path):
                md_text = open(md_path, 'r', encoding='utf-8').read()
                md_text = convert_images_to_inline(md_text, os.path.join(folder, 'attachments'))
                open(md_path, 'w', encoding='utf-8').write(md_text)

        return page_id, True, None
    except Exception as e:
        logger.error(f"페이지 처리 실패 [{page.get('title')}]: {e}")
        return page_id, False, str(e)


def export_all(old_session, old_base, space, root_page_id=None, inline_images=False):
    ensure_export_pages_dir()
    resume_state = load_resume_state()
    pages = get_all_pages(old_session, old_base, space, root_page_id=root_page_id)
    logger.info(f"다운로드 대상 페이지: {len(pages)}개")
    tasks = [(i, page, inline_images, resume_state) for i, page in enumerate(pages)]
    from concurrent.futures import ThreadPoolExecutor
    failed = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_page, *task): task for task in tasks}
        for future in tqdm(as_completed(futures), total=len(tasks), desc='Export'):
            page_id, success, err = future.result()
            if success:
                if page_id not in resume_state.get('downloaded', []):
                    resume_state.setdefault('downloaded', []).append(page_id)
                save_resume_state(resume_state)
            else:
                failed.append({'id': page_id, 'error': err})
    if failed:
        with open(os.path.join(EXPORT_DIR, 'failed_pages.json'), 'w', encoding='utf-8') as f:
            json.dump(failed, f, ensure_ascii=False, indent=2)
        logger.warning(f"실패한 페이지 {len(failed)}개")
    logger.info('Export 완료')
