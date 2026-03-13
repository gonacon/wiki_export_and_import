import os
import json
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import datetime
from tqdm import tqdm
from .config import old_session, EXPORT_DIR, MAX_WORKERS
import traceback
from .utils import (
    safe_folder_name,
    fix_image_links_html,
    md_convert,
    convert_images_to_inline,
    fix_url_images_in_html,
    convert_ri_url_to_attachment_if_exists
)
from .sanitizer import Sanitizer
from .io_utils import (
    download_attachments_for_page,
    load_resume_state,
    save_resume_state,
    ensure_export_pages_dir,
    save_page_files_v2
)

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
        try:
            r.raise_for_status() # 4xx or 5xx 응답에 대해 예외 발생
        except Exception as e:
            logger.error(f"페이지 목록 수집 실패: {e} (url={url}, params={params})")
            raise
        data = r.json()
        results = data.get('results', [])
        if not results:
            break
        pages += results
        start += limit
    logger.info(f"전체 페이지 수집 완료: {len(pages)}개")
    return sort_pages_by_hierarchy(pages) # 계층 구조에 따라 정렬


def get_descendant_pages(old_session, old_base, root_page_id):
    pages = []
    url = f"{old_base}/rest/api/content/{root_page_id}"
    r = old_session.get(url, params={"expand": "body.storage,ancestors"})
    try:
        r.raise_for_status()
    except Exception as e:
        logger.error(f"루트 페이지 조회 실패 (root={root_page_id}): {e} (url={url})")
        raise
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
    # title을 미리 정의하여 예외 블록에서 안전하게 사용
    title = page.get('title', 'untitled')
    try:
        # 페이지 ID를 안전하게 추출 (page가 dict이고 'id' 키가 있는지 확인)
        if not isinstance(page, dict):
            raise KeyError("page is not a dict")
        page_id = page.get('id')
        if not page_id:
            raise KeyError("page 'id' missing")

        # 이미 다운로드된 페이지는 건너뛰기
        if page_id in resume_state.get('downloaded', []):
            return page_id, True, None

        # body.storage.value를 안전하게 추출
        body = page.get('body', {})
        storage = body.get('storage', {}) if isinstance(body, dict) else None
        raw_html = storage.get('value') if isinstance(storage, dict) else None
        if raw_html is None:
            raise KeyError("page body.storage.value missing")
    except Exception as e:
        # 예외 발생 시 page_id가 없을 수 있으므로 안전하게 처리
        title = page.get('title') if isinstance(page, dict) else None
        logger.error(f"페이지 처리 실패 [{title}]: {e}")
        return page.get('id') if isinstance(page, dict) else None, False, str(e)

    try:
        # 페이지별 폴더 생성
        folder = os.path.join(EXPORT_DIR, "pages", f"{i:04d}_{safe_folder_name(title)}")
        os.makedirs(os.path.join(folder, "attachments"), exist_ok=True)

        # 페이지의 기존 첨부파일 다운로드
        try:
            download_attachments_for_page(page, folder)
        except Exception as e:
            logger.debug(f"첨부파일 사전 다운로드 실패 (무시하고 계속 진행): {e}")

        # URL 이미지 다운로드 및 HTML 콘텐츠 변환
        # 1) 깨진 Confluence 링크/태그 보정
        try:
            repaired_html = Sanitizer.repair_broken_confluence_links(raw_html)
        except Exception:
            repaired_html = raw_html

        # 2) 외부 URL 이미지를 다운로드하여 로컬 첨부파일로 변환
        try:
            converted_html = fix_url_images_in_html(repaired_html, os.path.join(folder, "attachments"), old_session)
        except Exception as e:
            # 변환 중 문제가 생기면 원본(repaired_html)을 사용하고 로그를 남깁니다.
            logger.warning(f"URL 이미지 변환 중 오류 발생, 원본 HTML로 대체합니다: {e}")
            logger.debug(traceback.format_exc())
            converted_html = repaired_html

        # 3) 로컬에 존재하는 첨부파일에 대해 ri:url을 ri:attachment로 치환 (링크 깨짐 방지)
        try:
            converted_html = convert_ri_url_to_attachment_if_exists(converted_html, os.path.join(folder, "attachments"))
        except Exception as e:
            logger.debug(f"ri:url -> ri:attachment 변환 실패 (무시하고 계속 진행): {e}")

        # HTML 내 이미지 링크를 로컬 경로로 수정하고 마크다운으로 변환
        try:
            html_local = fix_image_links_html(converted_html, os.path.join(EXPORT_DIR, 'pages'))
        except Exception as e:
            logger.warning(f"이미지 링크 보정 중 오류 발생, 원본 HTML로 대체합니다: {e}")
            logger.debug(traceback.format_exc())
            html_local = converted_html or repaired_html or raw_html

        try:
            markdown = md_convert(html_local, heading_style='ATX')
        except Exception as e:
            logger.warning(f"HTML -> Markdown 변환 실패 [{title}]: {e}")
            logger.debug(traceback.format_exc())
            markdown = ''

        # 파일 저장: page.storage.html=원본, 변환본은 별도 파일
        save_page_files_v2(page, folder, raw_html, markdown, converted_html)

        # Inline images 처리
        if inline_images:
            md_path = os.path.join(folder, 'page.md')
            if os.path.exists(md_path):
                md_text = open(md_path, 'r', encoding='utf-8').read()
                md_text = convert_images_to_inline(md_text, os.path.join(folder, 'attachments'))
                open(md_path, 'w', encoding='utf-8').write(md_text)

        return page_id, True, None
    except Exception as e:
        logger.error(f"페이지 처리 실패 [{title}]: {e}")
        return page.get('id') if isinstance(page, dict) else None, False, str(e)


def export_all(old_session, old_base, space, root_page_id=None, inline_images=False, workers=None):
    """
    페이지를 export합니다.

    Args:
        old_session: 요청 세션
        old_base: 기존 wiki URL
        space: 스페이스 키
        root_page_id: 루트 페이지 ID (optional)
        inline_images: 이미지 인라인 변환 여부
        workers: 멀티스레드 워커 수 (None이면 MAX_WORKERS 사용)
    """
    # 기존 export 폴더가 있으면 백업하여 깨끗한 상태에서 시작
    pages_dir = os.path.join(EXPORT_DIR, "pages")
    if os.path.exists(pages_dir):
        # 자동 백업: EXPORT_DIR/backups/<timestamp>/ 아래로 이동
        backups_root = os.path.join(EXPORT_DIR, 'backups')
        os.makedirs(backups_root, exist_ok=True)
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_subdir = os.path.join(backups_root, f"pages_backup_{ts}")
        try:
            shutil.move(pages_dir, backup_subdir)
            logger.info(f"기존 pages 폴더 백업 완료: {backup_subdir}")
        except Exception as e:
            logger.warning(f"기존 pages 폴더 백업 실패({pages_dir} -> {backup_subdir}): {e}")

        # resume_state.json, failed_pages.json 등 관련 메타데이터 파일도 백업
        for fname in ('resume_state.json', 'failed_pages.json', 'pages.json', 'migrate.log'):
            src = os.path.join(EXPORT_DIR, fname)
            if os.path.exists(src):
                try:
                    os.makedirs(backup_subdir, exist_ok=True)
                    shutil.move(src, os.path.join(backup_subdir, fname))
                    logger.info(f"메타데이터 파일 백업 완료: {fname}")
                except Exception as e:
                    logger.warning(f"메타데이터 파일 백업 실패({src}): {e}")

    ensure_export_pages_dir()
    resume_state = load_resume_state()
    pages = get_all_pages(old_session, old_base, space, root_page_id=root_page_id)

    # 수집된 페이지 중 구조가 올바르지 않은 항목(ID 부재 등)을 분리하여 기록
    valid_pages = [p for p in pages if isinstance(p, dict) and p.get('id')]
    invalid_pages = [p for p in pages if not (isinstance(p, dict) and p.get('id'))]

    if invalid_pages:
        fail_path = os.path.join(EXPORT_DIR, 'invalid_pages.json')
        with open(fail_path, 'w', encoding='utf-8') as f:
            # 직렬화 불가능한 객체를 대비해 str()로 변환
            json.dump([str(p) for p in invalid_pages], f, ensure_ascii=False, indent=2)
        logger.warning(f"수집된 항목 중 {len(invalid_pages)}개가 유효하지 않아 'invalid_pages.json'에 기록됨")

    pages = valid_pages
    logger.info(f"다운로드 대상 페이지: {len(pages)}개")

    # 수집된 페이지 중 구조가 올바르지 않은 항목을 분리하여 기록
    valid_pages = []
    invalid_pages = []
    for p in pages:
        if isinstance(p, dict) and p.get('id'):
            valid_pages.append(p)
        else:
            invalid_pages.append(p)

    if invalid_pages:
        # 실패 리스트에 구조 문제 항목 기록
        invalid_info = []
        for p in invalid_pages:
            try:
                invalid_info.append({'item': p})
            except Exception:
                invalid_info.append({'item': str(p)})
        fail_path = os.path.join(EXPORT_DIR, 'failed_pages.json')
        with open(fail_path, 'w', encoding='utf-8') as f:
            json.dump(invalid_info, f, ensure_ascii=False, indent=2)
        logger.warning(f"수집된 항목 중 {len(invalid_pages)}개가 유효하지 않습니다(파일에 기록됨): {fail_path}")

    pages = valid_pages
    logger.info(f"다운로드 대상 페이지: {len(pages)}개")

    # workers 파라미터가 주어지면 해당 값을, 아니면 MAX_WORKERS를 사용
    num_workers = workers if workers is not None else MAX_WORKERS
    logger.info(f"멀티스레드 워커 수: {num_workers}")
    failed = []

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        # tasks 리스트를 미리 만들지 않고, 바로 executor에 작업을 제출합니다.
        # 페이지가 매우 많을 때 메모리 사용량을 크게 절약할 수 있습니다.
        futures = {
            executor.submit(process_page, i, page, inline_images, resume_state): page
            for i, page in enumerate(pages)
        }

        for future in tqdm(as_completed(futures), total=len(futures), desc='Export'):
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
