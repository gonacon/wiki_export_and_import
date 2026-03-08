import os
import json
import logging
from . import config
from .sanitizer import Sanitizer
from .io_utils import load_resume_state, save_resume_state
from .utils import markdown_to_confluence_html, convert_local_imgs_to_acimage, convert_data_uri_imgs_to_acimage

logger = logging.getLogger('wiki_migrate')


def get_page_by_title(title):
    url = f"{config.NEW_BASE}/rest/api/content"
    params = {"title": title, "spaceKey": config.NEW_SPACE, "expand": "version"}
    try:
        r = config.new_session.get(url, params=params, timeout=10)
        r.raise_for_status()
        resp = r.json()
        if resp.get('results'):
            return resp['results'][0]
    except Exception as e:
        logger.debug(f"페이지 조회 실패 [{title}]: {e}")
    return None


def update_page(page_id, title, body_html, parent=None):
    url = f"{config.NEW_BASE}/rest/api/content/{page_id}"
    r = config.new_session.get(url, params={'expand': 'version'}, timeout=10)
    r.raise_for_status()
    resp = r.json()
    current_version = resp['version']['number']
    update_data = {
        'type': 'page', 'title': title, 'space': {'key': config.NEW_SPACE},
        'body': {'storage': {'value': body_html, 'representation': 'storage'}},
        'version': {'number': current_version + 1}
    }
    if parent:
        update_data['ancestors'] = [{'id': parent}]
    r = config.new_session.put(url, json=update_data)
    resp = r.json()
    if 'id' not in resp:
        raise RuntimeError(f"페이지 업데이트 실패: {resp}")
    return resp['id']


def create_page(title, body_html, parent=None):
    existing = get_page_by_title(title)
    if existing:
        logger.debug(f"기존 페이지 발견 [{title}] (ID: {existing['id']}) → 업데이트")
        return update_page(existing['id'], title, body_html, parent)
    url = f"{config.NEW_BASE}/rest/api/content"
    data = {'type': 'page', 'title': title, 'space': {'key': config.NEW_SPACE}, 'body': {'storage': {'value': body_html, 'representation': 'storage'}}}
    if parent:
        data['ancestors'] = [{'id': parent}]
    r = config.new_session.post(url, json=data)
    resp = r.json()
    if 'id' not in resp:
        raise RuntimeError(f"페이지 생성 실패: {resp}")
    return resp['id']


def upload_attachments(page_id, folder):
    att_path = os.path.join(folder, 'attachments')
    if not os.path.exists(att_path):
        return
    for fname in os.listdir(att_path):
        file_path = os.path.join(att_path, fname)
        url = f"{config.NEW_BASE}/rest/api/content/{page_id}/child/attachment"
        try:
            with open(file_path, 'rb') as f:
                config.new_session.post(url, files={'file': (fname, f)}, headers={'X-Atlassian-Token': 'no-check'})
            logger.debug(f"첨부파일 업로드: {fname}")
        except Exception as e:
            logger.error(f"첨부파일 업로드 실패 [{fname}]: {e}")


def import_all(inline_images=False, force_update=False):
    resume_state = load_resume_state()
    page_map = resume_state.get('page_map', {})
    pages_dir = os.path.join(config.EXPORT_DIR, 'pages')
    if not os.path.exists(pages_dir):
        logger.error(f"pages 디렉토리가 없습니다: {pages_dir}")
        return
    folders = sorted(os.listdir(pages_dir))
    failed_uploads = []
    for folder_name in folders:
        folder = os.path.join(pages_dir, folder_name)
        meta_path = os.path.join(folder, 'meta.json')
        if not os.path.exists(meta_path):
            continue
        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        old_id = meta['id']
        if not force_update and old_id in resume_state.get('uploaded', []):
            logger.debug(f"이미 업로드됨 (skip): {meta['title']}")
            continue
        parent_new_id = None
        if meta.get('parent') and str(meta['parent']) in page_map:
            parent_new_id = page_map[str(meta['parent'])]
        elif not meta.get('parent') and config.NEW_PARENT_PAGE_ID:
            parent_new_id = config.NEW_PARENT_PAGE_ID
        placeholder_html = '<p>Uploading attachments...</p>'
        try:
            new_id = create_page(meta['title'], placeholder_html, parent=parent_new_id)
        except Exception as e:
            logger.error(f"페이지 생성(placeholder) 실패 [{meta['title']}]: {e}")
            failed_uploads.append({'id': old_id, 'title': meta['title'], 'error': str(e)})
            continue
        page_map[str(old_id)] = new_id
        resume_state['page_map'] = page_map
        save_resume_state(resume_state)
        try:
            upload_attachments(new_id, folder)
        except Exception as e:
            logger.error(f"첨부파일 업로드 실패 [{meta['title']}]: {e}")
        page_storage_path = os.path.join(folder, 'page.storage.html')
        page_md_path = os.path.join(folder, 'page.md')
        att_dir = os.path.join(folder, 'attachments')
        html_body = None
        if os.path.exists(page_storage_path):
            try:
                with open(page_storage_path, 'r', encoding='utf-8') as f:
                    html_body = f.read()
                try:
                    html_body = Sanitizer.remove_macro_attrs(html_body)
                    html_body = Sanitizer.sanitize_code_macros(html_body)
                    html_body = Sanitizer.sanitize_gliffy_macros(html_body, att_dir)
                except Exception as e:
                    logger.debug(f"sanitizer 적용 실패 [{meta['title']}]: {e}")
            except Exception as e:
                logger.warning(f"page.storage.html 읽기 실패 [{meta['title']}]: {e}")
                html_body = None
        if not html_body:
            if os.path.exists(page_md_path):
                md_text = open(page_md_path, 'r', encoding='utf-8').read()
                if inline_images:
                    md_text = convert_images_to_inline(md_text, att_dir)
                try:
                    html_body = markdown_to_confluence_html(md_text)
                    try:
                        html_body = Sanitizer.remove_macro_attrs(html_body)
                        html_body = Sanitizer.sanitize_code_macros(html_body)
                        html_body = Sanitizer.sanitize_gliffy_macros(html_body, att_dir)
                    except Exception as e:
                        logger.debug(f"sanitizer 적용 실패 (md) [{meta['title']}]: {e}")
                except Exception as e:
                    logger.warning(f"HTML 변환 실패 [{meta['title']}], 기본 처리로 진행: {e}")
                    import html as _html
                    html_body = _html.escape(md_text, quote=False)
                    html_body = f"<p>{html_body}</p>"
            else:
                html_body = '<p></p>'
        if not html_body:
            html_body = '<p></p>'
        # data-uri 및 로컬 이미지 치환
        html_body = convert_data_uri_imgs_to_acimage(html_body, att_dir)
        html_body = convert_local_imgs_to_acimage(html_body)
        try:
            update_page(new_id, meta['title'], html_body, parent=parent_new_id)
            if old_id not in resume_state.get('uploaded', []):
                resume_state.setdefault('uploaded', []).append(old_id)
            save_resume_state(resume_state)
            logger.debug(f"업로드 완료: {meta['title']} (new_id={new_id})")
        except Exception as e:
            logger.error(f"업로드 실패 [{meta['title']}]: {e}")
            failed_uploads.append({'id': old_id, 'title': meta['title'], 'error': str(e)})
    if failed_uploads:
        with open(os.path.join(config.EXPORT_DIR, 'failed_uploads.json'), 'w', encoding='utf-8') as f:
            json.dump(failed_uploads, f, ensure_ascii=False, indent=2)
        logger.warning(f"실패한 업로드 {len(failed_uploads)}개 → {os.path.join(config.EXPORT_DIR, 'failed_uploads.json')}")
    logger.info('Import 완료')
