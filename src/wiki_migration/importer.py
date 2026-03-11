import os
import json
import logging
from .config import NEW_BASE, NEW_SPACE, NEW_PARENT_PAGE_ID, new_session, EXPORT_DIR
from .sanitizer import Sanitizer
from .io_utils import load_resume_state, save_resume_state
from .utils import markdown_to_confluence_html, convert_local_imgs_to_acimage, convert_data_uri_imgs_to_acimage, convert_images_to_inline

logger = logging.getLogger('wiki_migrate')


def get_page_by_title(title):
    url = f"{NEW_BASE}/rest/api/content"
    params = {"title": title, "spaceKey": NEW_SPACE, "expand": "version"}
    try:
        r = new_session.get(url, params=params, timeout=10)
        r.raise_for_status()
        resp = r.json()
        if resp.get('results'):
            return resp['results'][0]
    except Exception as e:
        logger.debug(f"페이지 조회 실패 [{title}]: {e}")
    return None


def update_page(page_id, title, body_html, parent=None):
    url = f"{NEW_BASE}/rest/api/content/{page_id}"
    r = new_session.get(url, params={'expand': 'version'}, timeout=10)
    r.raise_for_status()
    resp = r.json()
    current_version = resp['version']['number']
    update_data = {
        'type': 'page', 'title': title, 'space': {'key': NEW_SPACE},
        'body': {'storage': {'value': body_html, 'representation': 'storage'}},
        'version': {'number': current_version + 1}
    }
    if parent:
        update_data['ancestors'] = [{'id': parent}]
    r = new_session.put(url, json=update_data)
    resp = r.json()
    if 'id' not in resp:
        raise RuntimeError(f"페이지 업데이트 실패: {resp}")
    return resp['id']


def create_page(title, body_html, parent=None):
    existing = get_page_by_title(title)
    if existing:
        logger.debug(f"기존 페이지 발견 [{title}] (ID: {existing['id']}) → 업데이트")
        return update_page(existing['id'], title, body_html, parent)
    url = f"{NEW_BASE}/rest/api/content"
    data = {'type': 'page', 'title': title, 'space': {'key': NEW_SPACE}, 'body': {'storage': {'value': body_html, 'representation': 'storage'}}}
    if parent:
        data['ancestors'] = [{'id': parent}]
    r = new_session.post(url, json=data)
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
        url = f"{NEW_BASE}/rest/api/content/{page_id}/child/attachment"
        try:
            with open(file_path, 'rb') as f:
                new_session.post(url, files={'file': (fname, f)}, headers={'X-Atlassian-Token': 'no-check'})
            logger.debug(f"첨부파일 업로드: {fname}")
        except Exception as e:
            logger.error(f"첨부파일 업로드 실패 [{fname}]: {e}")


def build_page_hierarchy(pages_dir):
    """Export된 페이지들의 계층 구조를 파악"""
    pages_info = {}

    for folder_name in os.listdir(pages_dir):
        folder = os.path.join(pages_dir, folder_name)
        meta_path = os.path.join(folder, 'meta.json')
        if not os.path.exists(meta_path):
            continue

        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)

        pages_info[meta['id']] = {
            'folder': folder,
            'folder_name': folder_name,
            'meta': meta,
            'children': []
        }

    # 부모-자식 관계 구축
    for page_id, info in pages_info.items():
        parent_id = info['meta'].get('parent')
        if parent_id and parent_id in pages_info:
            pages_info[parent_id]['children'].append(page_id)

    return pages_info


def get_descendant_page_ids(pages_info, root_page_id):
    """특정 페이지의 모든 하위 페이지 ID를 재귀적으로 수집"""
    descendants = [root_page_id]

    def collect_children(page_id):
        if page_id in pages_info:
            for child_id in pages_info[page_id]['children']:
                descendants.append(child_id)
                collect_children(child_id)

    collect_children(root_page_id)
    return descendants


def upload_page(old_id, pages_info, page_map, parent_new_id, inline_images, force_update, resume_state):
    """단일 페이지를 업로드"""
    info = pages_info[old_id]
    meta = info['meta']
    folder = info['folder']

    # 이미 업로드된 페이지 처리
    if not force_update and old_id in resume_state.get('uploaded', []):
        existing_new_id = page_map.get(str(old_id))
        if existing_new_id:
            logger.debug(f"이미 업로드됨 (skip): {meta['title']} (new_id={existing_new_id})")

            # 부모가 변경되었는지 확인
            if parent_new_id:
                try:
                    # 기존 페이지의 부모를 확인하고 필요시 업데이트
                    url = f"{NEW_BASE}/rest/api/content/{existing_new_id}"
                    r = new_session.get(url, params={'expand': 'ancestors'}, timeout=10)
                    current_data = r.json()
                    current_ancestors = current_data.get('ancestors', [])
                    current_parent = current_ancestors[-1]['id'] if current_ancestors else None

                    # 부모가 다르면 재배치 필요
                    if current_parent != parent_new_id:
                        logger.info(f"부모 변경 감지: {meta['title']} - {current_parent} → {parent_new_id}")
                        # 간단한 업데이트로 부모만 변경
                        update_page_parent_only(existing_new_id, meta['title'], parent_new_id)
                except Exception as e:
                    logger.warning(f"기존 페이지 부모 확인 실패 [{meta['title']}]: {e}")

            return existing_new_id, None
        else:
            logger.warning(f"업로드 기록은 있지만 page_map에 없음: {old_id}")

    # Placeholder로 먼저 페이지 생성
    placeholder_html = '<p>Uploading attachments...</p>'
    try:
        new_id = create_page(meta['title'], placeholder_html, parent=parent_new_id)
    except Exception as e:
        logger.error(f"페이지 생성(placeholder) 실패 [{meta['title']}]: {e}")
        return None, {'id': old_id, 'title': meta['title'], 'error': str(e)}

    page_map[str(old_id)] = new_id

    # 첨부파일 업로드
    try:
        upload_attachments(new_id, folder)
    except Exception as e:
        logger.error(f"첨부파일 업로드 실패 [{meta['title']}]: {e}")

    # HTML 본문 준비
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

                # ✨ 새로 추가: URL 이미지 변환 (보험용)
                html_body = Sanitizer.convert_remaining_url_images(html_body, att_dir)
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

    # 실제 내용으로 업데이트
    try:
        update_page(new_id, meta['title'], html_body, parent=parent_new_id)
        if old_id not in resume_state.get('uploaded', []):
            resume_state.setdefault('uploaded', []).append(old_id)
        logger.info(f"✓ 업로드 완료: {meta['title']} (new_id={new_id})")
        return new_id, None
    except Exception as e:
        logger.error(f"업로드 실패 [{meta['title']}]: {e}")
        return new_id, {'id': old_id, 'title': meta['title'], 'error': str(e)}

def update_page_parent_only(page_id, title, parent_id):
    """페이지의 부모만 변경 (내용은 그대로)"""
    url = f"{NEW_BASE}/rest/api/content/{page_id}"
    r = new_session.get(url, params={'expand': 'version,body.storage'}, timeout=10)
    r.raise_for_status()
    resp = r.json()

    current_version = resp['version']['number']
    current_body = resp['body']['storage']['value']

    update_data = {
        'type': 'page',
        'title': title,
        'space': {'key': NEW_SPACE},
        'body': {'storage': {'value': current_body, 'representation': 'storage'}},
        'version': {'number': current_version + 1},
        'ancestors': [{'id': parent_id}]
    }

    r = new_session.put(url, json=update_data)
    resp = r.json()
    if 'id' not in resp:
        raise RuntimeError(f"부모 업데이트 실패: {resp}")

    logger.info(f"부모 변경 완료: {title} → parent_id={parent_id}")
    return resp['id']

def upload_recursively(old_id, parent_new_id, pages_info, page_ids_to_import,
                       page_map, inline_images, force_update, resume_state,
                       failed_uploads, uploaded_count_ref):
    """
    재귀적으로 페이지를 업로드

    중요: 이미 업로드된 페이지도 하위 페이지는 계속 처리
    """
    if old_id not in pages_info:
        logger.warning(f"페이지 정보를 찾을 수 없습니다: {old_id}")
        return

    # 현재 페이지 업로드 (또는 skip하되 new_id 확인)
    new_id, error = upload_page(
        old_id, pages_info, page_map, parent_new_id,
        inline_images, force_update, resume_state
    )

    if error:
        failed_uploads.append(error)
        # 에러가 발생해도 하위 페이지는 시도 (옵션)
        # return  # ← 이 줄을 주석 처리하면 에러 발생해도 하위 계속 진행
    else:
        uploaded_count_ref[0] += 1
        save_resume_state(resume_state)

    # 자식 페이지들을 재귀적으로 업로드
    # 중요: 부모가 skip되어도 하위는 처리!
    if new_id:  # new_id가 있으면 (skip된 경우에도 page_map에서 가져옴)
        for child_id in pages_info[old_id]['children']:
            if child_id in page_ids_to_import:
                upload_recursively(
                    child_id, new_id, pages_info, page_ids_to_import,
                    page_map, inline_images, force_update, resume_state,
                    failed_uploads, uploaded_count_ref
                )

def import_all(inline_images=False, force_update=False, root_page_id=None, target_parent_id=None):
    """
    페이지를 import합니다.

    Args:
        inline_images: 이미지를 인라인으로 변환할지 여부
        force_update: 이미 업로드된 페이지도 다시 업로드할지 여부
        root_page_id: import할 루트 페이지 ID (이 페이지와 모든 하위 페이지를 import)
        target_parent_id: 새 wiki에서 부모로 지정할 페이지 ID (지정하지 않으면 NEW_PARENT_PAGE_ID 사용)
    """
    resume_state = load_resume_state()
    page_map = resume_state.get('page_map', {})
    pages_dir = os.path.join(EXPORT_DIR, 'pages')

    if not os.path.exists(pages_dir):
        logger.error(f"pages 디렉토리가 없습니다: {pages_dir}")
        return

    # 페이지 계층 구조 파악
    logger.info("페이지 계층 구조 분석 중...")
    pages_info = build_page_hierarchy(pages_dir)

    # import할 페이지 목록 결정
    if root_page_id:
        logger.info(f"루트 페이지 {root_page_id}와 하위 페이지들을 import합니다.")
        page_ids_to_import = get_descendant_page_ids(pages_info, root_page_id)
        logger.info(f"총 {len(page_ids_to_import)}개 페이지를 import합니다.")
    else:
        logger.info("모든 페이지를 import합니다.")
        page_ids_to_import = list(pages_info.keys())

    # 부모 페이지 ID 결정
    parent_id = target_parent_id or NEW_PARENT_PAGE_ID

    failed_uploads = []
    uploaded_count_ref = [0]  # mutable object for nested function

    # root_page_id가 지정된 경우
    if root_page_id:
        if root_page_id in pages_info:
            upload_recursively(
                root_page_id, parent_id, pages_info, page_ids_to_import,
                page_map, inline_images, force_update, resume_state,
                failed_uploads, uploaded_count_ref
            )
        else:
            logger.error(f"루트 페이지를 찾을 수 없습니다: {root_page_id}")
            return
    else:
        # 모든 최상위 페이지부터 시작
        for page_id in page_ids_to_import:
            info = pages_info[page_id]
            # 부모가 없거나, 부모가 import 대상이 아닌 경우만 최상위로 간주
            parent = info['meta'].get('parent')
            if not parent or parent not in page_ids_to_import:
                upload_recursively(
                    page_id, parent_id, pages_info, page_ids_to_import,
                    page_map, inline_images, force_update, resume_state,
                    failed_uploads, uploaded_count_ref
                )

    # 실패 기록 저장
    if failed_uploads:
        with open(os.path.join(EXPORT_DIR, 'failed_uploads.json'), 'w', encoding='utf-8') as f:
            json.dump(failed_uploads, f, ensure_ascii=False, indent=2)
        logger.warning(f"실패한 업로드 {len(failed_uploads)}개 → {os.path.join(EXPORT_DIR, 'failed_uploads.json')}")

    logger.info(f'Import 완료: {uploaded_count_ref[0]}개 페이지 업로드')
