import os
import json
import logging
import threading
import time
from typing import cast
from concurrent.futures import ThreadPoolExecutor, as_completed
from .config import OLD_BASE, NEW_BASE, NEW_SPACE, NEW_PARENT_PAGE_ID, new_session, EXPORT_DIR, MAX_WORKERS
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
    # load manifest to map stored filenames -> original titles (if present)
    manifest_path = os.path.join(att_path, 'manifest.json')
    manifest = {}
    title_map = {}
    try:
        if os.path.exists(manifest_path):
            with open(manifest_path, 'r', encoding='utf-8') as mf:
                manifest = json.load(mf)
                title_map = manifest.get('title_map', {}) if isinstance(manifest, dict) else {}
    except Exception:
        title_map = {}
    for fname in os.listdir(att_path):
        # skip manifest file and any non-files
        if fname == 'manifest.json':
            continue
        file_path = os.path.join(att_path, fname)
        if not os.path.isfile(file_path):
            continue
        # normalize filename for comparison (macOS may use NFD on disk)
        try:
            import unicodedata
            fname_norm = unicodedata.normalize('NFC', fname)
        except Exception:
            fname_norm = fname
        url = f"{NEW_BASE}/rest/api/content/{page_id}/child/attachment"
        try:
            with open(file_path, 'rb') as f:
                # If we have an original title for this stored filename, upload using the original title
                # so that page references (ri:attachment ri:filename="original.jpg") match uploaded attachments.
                upload_name = fname
                # reverse title_map: stored_name -> title
                # title_map typically maps title -> stored_name; build reverse
                try:
                    # title_map values are stored names; find title whose value equals fname
                    for t, stored in title_map.items():
                        try:
                            stored_norm = unicodedata.normalize('NFC', stored)
                        except Exception:
                            stored_norm = stored
                        if stored_norm == fname_norm:
                            upload_name = t
                            break
                except Exception:
                    pass

                r = new_session.post(url, files={'file': (upload_name, f)}, headers={'X-Atlassian-Token': 'no-check'})
                try:
                    status = getattr(r, 'status_code', None)
                    if status and status >= 400:
                        logger.error(f"첨부파일 업로드 응답 에러 [{upload_name}] status={status} text={r.text}")
                    else:
                        logger.debug(f"첨부파일 업로드: stored={fname} upload_as={upload_name} status={status}")
                except Exception:
                    logger.debug(f"첨부파일 업로드(응답 로그) 실패: {fname}")
        except Exception as e:
             logger.error(f"첨부파일 업로드 실패 [{fname}]: {e}")


def build_page_hierarchy(pages_dir):
    """Export된 페이지들의 계층 구조를 파악"""
    pages_info = {}
    pages_dir = cast(str, pages_dir)

    for folder_name in os.listdir(pages_dir):
        folder_name = cast(str, folder_name)
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
    # 우선순위: 변환된 storage HTML이 있으면 사용하고, 없으면 원본 storage HTML 사용
    converted_path = os.path.join(folder, 'page.storage.converted.html')
    page_storage_path = converted_path if os.path.exists(converted_path) else os.path.join(folder, 'page.storage.html')
    page_md_path = os.path.join(folder, 'page.md')
    att_dir = os.path.join(folder, 'attachments')
    html_body = None

    if os.path.exists(page_storage_path):
        try:
            with open(page_storage_path, 'r', encoding='utf-8') as f:
                html_body = f.read()
            try:
                html_body = Sanitizer.repair_broken_confluence_links(html_body)
                html_body = Sanitizer.remove_macro_attrs(html_body)
                html_body = Sanitizer.sanitize_code_macros(html_body)
                html_body = Sanitizer.sanitize_gliffy_macros(html_body, att_dir)

                # 안전 보완: 변환된 HTML 내부의 ri:attachment 참조 정규화
                try:
                    html_body = Sanitizer.normalize_ri_attachment_refs(html_body)
                except Exception:
                    pass

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
                    html_body = Sanitizer.repair_broken_confluence_links(html_body)
                    html_body = Sanitizer.remove_macro_attrs(html_body)
                    html_body = Sanitizer.sanitize_code_macros(html_body)
                    html_body = Sanitizer.sanitize_gliffy_macros(html_body, att_dir)

                    # 안전 보완: md->HTML 변환본도 ri:attachment 정규화
                    try:
                        html_body = Sanitizer.normalize_ri_attachment_refs(html_body)
                    except Exception:
                        pass
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
        # Debug: list ac:image ri:attachment filenames referenced in html_body
        try:
            import re
            imgs = re.findall(r'<ac:image[^>]*>.*?<ri:attachment\s+ri:filename="([^"]+)"\s*/?>.*?</ac:image>', html_body or '', re.DOTALL | re.IGNORECASE)
            if imgs:
                logger.debug(f"페이지 업데이트 전에 참조되는 첨부파일 목록: {imgs}")
            else:
                logger.debug("페이지 업데이트 전에 참조되는 ac:image/ri:attachment 없음")
        except Exception as _e:
            logger.debug(f"첨부 참조 검사 실패: {_e}")
        update_page(new_id, meta['title'], html_body, parent=parent_new_id)

        # Verification: check remote attachments and re-upload any missing ones referenced in html_body
        try:
            def _list_remote_attachments(pid):
                url = f"{NEW_BASE}/rest/api/content/{pid}/child/attachment"
                res = new_session.get(url, params={'limit': 200}, timeout=15)
                res.raise_for_status()
                data = res.json().get('results', [])
                return set(item.get('title') for item in data if item.get('title'))

            referenced = set(imgs) if 'imgs' in locals() else set()
            remote_att = _list_remote_attachments(new_id) if referenced else set()
            missing = referenced - remote_att
            if missing:
                logger.warning(f"원격에 없는 참조 첨부 발견, 재업로드 시도: {missing}")
                # try to upload missing files from local attachments dir
                att_path_local = att_dir
                manifest_map = {}
                try:
                    mpath = os.path.join(att_path_local, 'manifest.json')
                    if os.path.exists(mpath):
                        manifest_map = json.load(open(mpath, 'r', encoding='utf-8')).get('title_map', {}) or {}
                except Exception:
                    manifest_map = {}

                uploaded_any = False
                for fname in list(missing):
                    # find file in att_dir: exact match or NFC-normalized match or manifest mapping
                    candidate = None
                    # direct file
                    p1 = os.path.join(att_path_local, fname)
                    if os.path.exists(p1):
                        candidate = p1
                        upload_as = fname
                    else:
                        # check manifest_map keys (title->stored)
                        stored = manifest_map.get(fname)
                        if stored:
                            p2 = os.path.join(att_path_local, stored)
                            if os.path.exists(p2):
                                candidate = p2
                                upload_as = fname
                        # try normalized matches
                        if not candidate:
                            try:
                                import unicodedata
                                nf = unicodedata.normalize('NFC', fname)
                                for f in os.listdir(att_path_local):
                                    if unicodedata.normalize('NFC', f) == nf:
                                        candidate = os.path.join(att_path_local, f)
                                        upload_as = fname
                                        break
                            except Exception:
                                pass
                    if candidate:
                        try:
                            with open(candidate, 'rb') as cf:
                                r = new_session.post(f"{NEW_BASE}/rest/api/content/{new_id}/child/attachment", files={'file': (upload_as, cf)}, headers={'X-Atlassian-Token': 'no-check'})
                                try:
                                    if getattr(r, 'status_code', None) and r.status_code >= 400:
                                        logger.error(f"재업로드 실패 [{upload_as}] status={r.status_code} text={r.text}")
                                    else:
                                        logger.info(f"재업로드 성공: {upload_as}")
                                        uploaded_any = True
                                except Exception:
                                    logger.debug(f"재업로드 응답 로깅 실패: {upload_as}")
                        except Exception as e:
                            logger.error(f"재업로드 중 파일 열기 실패 [{candidate}]: {e}")
                    else:
                        logger.error(f"로컬 첨부에서 참조 파일 찾을 수 없음: {fname}")

                if uploaded_any:
                    # if we uploaded missing attachments, update page again to ensure links resolve
                    try:
                        update_page(new_id, meta['title'], html_body, parent=parent_new_id)
                        logger.info(f"첨부 재업로드 후 페이지 재업데이트 완료: {meta['title']}")
                    except Exception as e:
                        logger.error(f"첨부 재업로드 후 페이지 업데이트 실패: {e}")
        except Exception as e:
            logger.debug(f"원격 첨부 검증 실패: {e}")

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
    # 안내: single-pass import는 기본적으로 순차 실행입니다.
    logger.info("단일 패스 import 모드: 업로드는 순차적으로 실행됩니다 (병렬화하려면 2-Pass 모드를 사용하세요).")

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

# importer.py - import_all 함수 다음에 추가

def import_all_two_pass(inline_images=False, force_update=False, root_page_id=None, target_parent_id=None):
    """
    2-Pass Import: 1차로 모든 페이지 생성, 2차로 내용 + 링크 업데이트

    Args:
        inline_images: 이미지를 인라인으로 변환할지 여부
        force_update: 이미 업로드된 페이지도 다시 업로드할지 여부
        root_page_id: import할 루트 페이지 ID
        target_parent_id: 새 wiki에서 부모로 지정할 페이지 ID
    """
    from .utils import convert_internal_links_with_pageid

    resume_state = load_resume_state()
    page_map = resume_state.get('page_map', {})
    pages_dir = os.path.join(EXPORT_DIR, 'pages')

    if not os.path.exists(pages_dir):
        logger.error(f"pages 디렉토리가 없습니다: {pages_dir}")
        return

    # 페이지 계층 구조 파악
    logger.info("페이지 계층 구조 분석 중...")
    # 안내: 병렬 처리 관련 정보 출력
    logger.info(f"2-Pass Import 시작: MAX_WORKERS 설정 = {MAX_WORKERS}")

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

    # helper: retry with backoff for transient errors
    def retry_with_backoff(func, retries=3, initial_delay=1, exceptions=(Exception,)):
        delay = initial_delay
        for attempt in range(1, retries + 1):
            try:
                return func()
            except exceptions as e:
                if attempt == retries:
                    raise
                logger.debug(f"Retry {attempt}/{retries} after error: {e}")
                time.sleep(delay)
                delay *= 2

    # compute depth (BFS) for level-by-level processing
    depths = {}
    from collections import deque
    q = deque()
    # roots: nodes whose parent is absent or not in pages_info
    for pid, info in pages_info.items():
        parent = info['meta'].get('parent')
        if not parent or str(parent) not in pages_info:
            q.append((pid, 0))

    while q:
        pid, d = q.popleft()
        if pid in depths:
            continue
        depths[pid] = d
        for c in pages_info[pid]['children']:
            q.append((c, d + 1))

    # group by level
    levels = {}
    for pid, d in depths.items():
        levels.setdefault(d, []).append(pid)

    page_map_lock = threading.Lock()
    resume_lock = threading.Lock()

    # ========================================
    # PASS 1: 페이지 구조 생성 (레벨별 병렬)
    # ========================================
    logger.info("=" * 60)
    logger.info("PASS 1: 페이지 구조 생성 (병렬) 중...")
    logger.info("=" * 60)

    pass1_created = 0

    def create_task(old_id):
        nonlocal pass1_created
        info = pages_info.get(old_id)
        if not info:
            return None
        meta = info['meta']
        # check existing mapping
        with page_map_lock:
            if str(old_id) in page_map and not force_update:
                return page_map[str(old_id)]

        # determine parent_new_id
        parent_old = meta.get('parent')
        parent_new = None
        with page_map_lock:
            if parent_old and str(parent_old) in page_map:
                parent_new = page_map[str(parent_old)]
            elif not parent_old and parent_id:
                parent_new = parent_id

        placeholder = f'<p>페이지 내용 업데이트 대기 중... (원본 ID: {old_id})</p>'
        try:
            new_id = retry_with_backoff(lambda: create_page(meta['title'], placeholder, parent=parent_new), retries=3)
        except Exception as e:
            logger.error(f"Pass1 페이지 생성 실패 [{meta['title']}]: {e}")
            failed_uploads.append({'id': old_id, 'title': meta['title'], 'error': str(e), 'pass': 1})
            return None

        with page_map_lock:
            page_map[str(old_id)] = new_id
        with resume_lock:
            resume_state['page_map'] = page_map
            save_resume_state(resume_state)

        pass1_created += 1
        logger.info(f"Pass1 생성: {meta['title']} (old={old_id}, new={new_id})")
        return new_id

    # run per level
    for depth in sorted(levels.keys()):
        pids = [pid for pid in levels[depth] if pid in page_ids_to_import]
        if not pids:
            continue
        workers = min(MAX_WORKERS, len(pids)) if MAX_WORKERS else min(8, len(pids))
        logger.info(f"Pass1: depth={depth} 레벨에서 {len(pids)}개 페이지를 처리합니다. 사용 워커 수 = {workers}")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(create_task, pid): pid for pid in pids}
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception as e:
                    pid = futures.get(fut)
                    logger.error(f"Pass1 task 실패 [{pid}]: {e}")

    # ensure page_map persisted
    with resume_lock:
        resume_state['page_map'] = page_map
        save_resume_state(resume_state)

    logger.info(f"Pass 1 완료: {pass1_created}개 페이지 생성")

    # ========================================
    # PASS 2: 내용 업데이트 + 링크 변환 (병렬)
    # ========================================
    logger.info("")
    logger.info("=" * 60)
    logger.info("PASS 2: 페이지 내용 업데이트 (병렬) 중...")
    logger.info("=" * 60)

    pass2_count = 0

    def update_task(old_id):
        nonlocal pass2_count
        if old_id not in pages_info:
            return
        info = pages_info[old_id]
        meta = info['meta']
        folder = info['folder']

        new_id = None
        with page_map_lock:
            new_id = page_map.get(str(old_id))

        if not new_id:
            logger.error(f"Pass2: page_map에 없음 (skip): {meta['title']}")
            return

        try:
            # attachments
            try:
                retry_with_backoff(lambda: upload_attachments(new_id, folder), retries=2)
            except Exception as e:
                logger.error(f"Pass2 첨부파일 업로드 실패 [{meta['title']}]: {e}")

            # HTML 본문 준비
            converted_path = os.path.join(folder, 'page.storage.converted.html')
            page_storage_path = converted_path if os.path.exists(converted_path) else os.path.join(folder, 'page.storage.html')
            att_dir = os.path.join(folder, 'attachments')
            html_body = None

            if os.path.exists(page_storage_path):
                with open(page_storage_path, 'r', encoding='utf-8') as f:
                    html_body = f.read()
                try:
                    html_body = Sanitizer.repair_broken_confluence_links(html_body)
                    html_body = Sanitizer.remove_macro_attrs(html_body)
                    html_body = Sanitizer.sanitize_code_macros(html_body)
                    html_body = Sanitizer.sanitize_gliffy_macros(html_body, att_dir)
                    html_body = Sanitizer.convert_remaining_url_images(html_body, att_dir)

                    # 내부 링크 변환
                    html_body = convert_internal_links_with_pageid(
                        html_body,
                        OLD_BASE,
                        NEW_BASE,
                        page_map,
                        pages_info=pages_info,
                        current_page_old_id=old_id
                    )
                except Exception as e:
                    logger.debug(f"Pass2 sanitizer 실패 [{meta['title']}]: {e}")

            if not html_body:
                html_body = '<p>내용 없음</p>'

            # data-uri 및 로컬 이미지 치환
            html_body = convert_data_uri_imgs_to_acimage(html_body, att_dir)
            html_body = convert_local_imgs_to_acimage(html_body)

            # determine parent_new_id
            parent_new_id = None
            parent_old = meta.get('parent')
            with page_map_lock:
                if parent_old and str(parent_old) in page_map:
                    parent_new_id = page_map[str(parent_old)]
                elif not parent_old and parent_id:
                    parent_new_id = parent_id

            retry_with_backoff(lambda: update_page(new_id, meta['title'], html_body, parent=parent_new_id), retries=3)

            with resume_lock:
                if old_id not in resume_state.get('uploaded', []):
                    resume_state.setdefault('uploaded', []).append(old_id)
                    save_resume_state(resume_state)

            pass2_count += 1
            logger.info(f"✓ Pass2 완료: {meta['title']} (new_id={new_id})")

        except Exception as e:
            logger.error(f"Pass2 업데이트 실패 [{meta['title']}]: {e}")
            failed_uploads.append({'id': old_id, 'title': meta['title'], 'error': str(e), 'pass': 2})

    # Run update_task in parallel for all import targets
    all_targets = [pid for pid in page_ids_to_import if pid in pages_info]
    workers = min(MAX_WORKERS, len(all_targets)) if MAX_WORKERS else min(8, len(all_targets))
    logger.info(f"Pass2: 총 대상 페이지 수 = {len(all_targets)}, 사용 워커 수 = {workers}")
    with ThreadPoolExecutor(max_workers=workers or 1) as ex:
        futures = {ex.submit(update_task, pid): pid for pid in all_targets}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                pid = futures.get(fut)
                logger.error(f"Pass2 task 실패 [{pid}]: {e}")

    logger.info(f"Pass 2 완료: {pass2_count}개 페이지 업데이트")

    # 실패 기록 저장
    if failed_uploads:
        with open(os.path.join(EXPORT_DIR, 'failed_uploads.json'), 'w', encoding='utf-8') as f:
            json.dump(failed_uploads, f, ensure_ascii=False, indent=2)
        logger.warning(f"실패한 업로드 {len(failed_uploads)}개")

    logger.info(f'2-Pass Import 완료: Pass1={pass1_created}, Pass2={pass2_count}')
