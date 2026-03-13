import os
import json
import time
import re
import logging
from .config import EXPORT_DIR, OLD_BASE, old_session, MAX_RETRIES, RETRY_DELAY, FAILED_GLIFFY_LOG, MAX_WORKERS
from .utils import safe_folder_name
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

logger = logging.getLogger("wiki_migrate")


def ensure_export_pages_dir():
    os.makedirs(os.path.join(EXPORT_DIR, "pages"), exist_ok=True)


def save_page_files(page, index, html, markdown):
    title = page.get('title', 'untitled')
    folder = os.path.join(EXPORT_DIR, "pages", f"{index:04d}_{safe_folder_name(title)}")
    os.makedirs(os.path.join(folder, "attachments"), exist_ok=True)
    try:
        with open(os.path.join(folder, "page.storage.html"), "w", encoding="utf-8") as f:
            f.write(html)
    except Exception as e:
        logger.warning(f"page.storage.html 저장 실패 [{title}]: {e}")
    with open(os.path.join(folder, "page.md"), "w", encoding="utf-8") as f:
        f.write(markdown)
    parent = None
    if page.get("ancestors"):
        parent = page["ancestors"][-1]["id"]
    meta = {"id": page["id"], "title": title, "parent": parent}
    with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return folder

def save_page_files_v2(page, folder, html, markdown, converted_html=None):
    """
    페이지 파일 저장 (폴더가 이미 생성된 경우)

    Args:
        page: 페이지 정보
        folder: 이미 생성된 폴더 경로
        html: 원본 storage HTML 내용
        markdown: Markdown 내용
        converted_html: export 중 변환된 storage HTML (optional)
    """
    title = page.get('title', 'untitled')

    try:
        with open(os.path.join(folder, "page.storage.html"), "w", encoding="utf-8") as f:
            f.write(html)
    except Exception as e:
        logger.warning(f"page.storage.html 저장 실패 [{title}]: {e}")

    # 항상 converted 파일을 생성하도록 변경: 변환 결과가 없으면 원본 HTML을 사용
    try:
        to_write = converted_html if converted_html is not None else html
        with open(os.path.join(folder, "page.storage.converted.html"), "w", encoding="utf-8") as f:
            f.write(to_write)
        if converted_html is None:
            logger.debug(f"converted_html 없음: 원본 HTML로 page.storage.converted.html 생성 [{title}]")
    except Exception as e:
        logger.warning(f"page.storage.converted.html 저장 실패 [{title}]: {e}")

    with open(os.path.join(folder, "page.md"), "w", encoding="utf-8") as f:
        f.write(markdown)

    parent = None
    if page.get("ancestors"):
        parent = page["ancestors"][-1]["id"]

    meta = {"id": page["id"], "title": title, "parent": parent}
    with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return folder

def download_attachments_for_page(page, folder):
    url = f"{OLD_BASE}/rest/api/content/{page['id']}/child/attachment"
    r = old_session.get(url)
    results = r.json().get('results', [])
    for att in results:
        link = OLD_BASE + att["_links"]["download"]
        name = att["title"]
        path = os.path.join(folder, "attachments", name)
        if os.path.exists(path):
            logger.debug(f"첨부파일 이미 존재 (skip): {name}")
            continue
        try:
            resp = old_session.get(link)
            with open(path, "wb") as f:
                f.write(resp.content)
            logger.debug(f"첨부파일 다운로드: {name}")
        except Exception as e:
            logger.error(f"첨부파일 다운로드 실패 [{name}]: {e}")


def load_resume_state(resume_file=None):
    path = resume_file or os.path.join(EXPORT_DIR, "resume_state.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"downloaded": [], "uploaded": [], "page_map": {}}


def save_resume_state(state, resume_file=None):
    path = resume_file or os.path.join(EXPORT_DIR, "resume_state.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def download_gliffy_thumbnails(page, folder):
    storage_path = os.path.join(folder, "page.storage.html")
    if not os.path.exists(storage_path):
        return

    content = open(storage_path, "r", encoding="utf-8", errors="ignore").read()
    att_dir = os.path.join(folder, "attachments")
    os.makedirs(att_dir, exist_ok=True)

    GLIFFY_RE = re.compile(r'<ac:structured-macro[^>]+ac:name="gliffy"[^>]*>(.*?)</ac:structured-macro>', re.DOTALL | re.IGNORECASE)
    PARAM_RE = re.compile(r'<ac:parameter\s+ac:name="([^\"]+)"\s*>(.*?)</ac:parameter>', re.DOTALL | re.IGNORECASE)

    for macro_match in GLIFFY_RE.finditer(content):
        macro_body = macro_match.group(0)
        params = {m.group(1): m.group(2).strip() for m in PARAM_RE.finditer(macro_body)}

        macro_id = params.get("macroId", "")
        display_name = params.get("displayName") or params.get("name") or macro_id
        page_id = page["id"]

        safe_name = re.sub(r'[^\w\-.]', '_', display_name)[:80]
        out_filename = f"gliffy_{safe_name}.png"
        out_path = os.path.join(att_dir, out_filename)

        if os.path.exists(out_path):
            logger.debug(f"Gliffy 썸네일 이미 존재 (skip): {out_filename}")
            continue

        candidate_urls = []
        if macro_id:
            candidate_urls.append(f"{OLD_BASE}/rest/gliffy/1.0/embeddedDiagrams/{macro_id}.png?pageId={page_id}")
        if display_name:
            from urllib.parse import quote as url_quote
            candidate_urls.append(f"{OLD_BASE}/plugins/servlet/gliffy/export?pageId={page_id}&name={url_quote(display_name)}&format=png")
            candidate_urls.append(f"{OLD_BASE}/download/attachments/{page_id}/{display_name}.png")
        if macro_id:
            candidate_urls.append(f"{OLD_BASE}/download/attachments/{page_id}/{macro_id}.png")

        downloaded = False
        for attempt in range(1, MAX_RETRIES + 1):
            for url in candidate_urls:
                try:
                    resp = old_session.get(url, timeout=15)
                    content_type = resp.headers.get("Content-Type", "")
                    if resp.status_code == 200 and content_type.startswith("image/"):
                        with open(out_path, "wb") as f:
                            f.write(resp.content)
                        logger.info(f"Gliffy 썸네일 다운로드 성공: {out_filename} (url={url}, size={len(resp.content)}bytes)")
                        downloaded = True
                        break
                except Exception as e:
                    logger.debug(f"Gliffy 썸네일 URL 실패 [{url}]: {e}")
            if downloaded:
                break
            if attempt < MAX_RETRIES:
                logger.warning(f"Gliffy 썸네일 다운로드 재시도 ({attempt}/{MAX_RETRIES}) [{display_name}]... {RETRY_DELAY * attempt}초 후")
                time.sleep(RETRY_DELAY * attempt)

        if not downloaded:
            logger.error(f"Gliffy 썸네일 다운로드 최종 실패 [{display_name}] (pageId={page_id}, macroId={macro_id})")
            log_failed_gliffy({
                "pageId": page_id,
                "pageTitle": page.get("title", ""),
                "macroId": macro_id,
                "displayName": display_name,
                "folder": folder
            })


def log_failed_gliffy(fail_info):
    failed_items = []
    if os.path.exists(FAILED_GLIFFY_LOG):
        with open(FAILED_GLIFFY_LOG, "r", encoding="utf-8") as f:
            try:
                failed_items = json.load(f)
            except json.JSONDecodeError:
                pass
    if not any(item['macroId'] == fail_info['macroId'] and item['pageId'] == fail_info['pageId'] for item in failed_items):
        failed_items.append(fail_info)
        with open(FAILED_GLIFFY_LOG, "w", encoding="utf-8") as f:
            json.dump(failed_items, f, ensure_ascii=False, indent=2)


def retry_failed_gliffy():
    if not os.path.exists(FAILED_GLIFFY_LOG):
        logger.info("실패한 Gliffy 로그 파일이 없습니다.")
        return
    with open(FAILED_GLIFFY_LOG, "r", encoding="utf-8") as f:
        try:
            failed_items = json.load(f)
        except json.JSONDecodeError:
            logger.error("실패 로그 파일을 읽을 수 없습니다.")
            return
    if not failed_items:
        logger.info("재시도할 Gliffy 항목이 없습니다.")
        return
    logger.info(f"실패한 Gliffy 썸네일 {len(failed_items)}개에 대해 재시도를 시작합니다.")
    still_failing = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        tasks = []
        for item in failed_items:
            fake_page = {"id": item["pageId"], "title": item["pageTitle"]}
            folder = item["folder"]
            tasks.append(executor.submit(download_gliffy_thumbnails, fake_page, folder))
        for future in tqdm(as_completed(tasks), total=len(tasks), desc="Gliffy 재시도"):
            try:
                future.result()
            except Exception as e:
                logger.error(f"Gliffy 재시도 중 오류 발생: {e}")
    if os.path.exists(FAILED_GLIFFY_LOG):
        os.remove(FAILED_GLIFFY_LOG)
    for item in failed_items:
        safe_name = re.sub(r'[^\w\-.]', '_', item['displayName'])[:80]
        out_filename = f"gliffy_{safe_name}.png"
        out_path = os.path.join(item['folder'], "attachments", out_filename)
        if not os.path.exists(out_path):
            still_failing.append(item)
    if still_failing:
        with open(FAILED_GLIFFY_LOG, "w", encoding="utf-8") as f:
            json.dump(still_failing, f, ensure_ascii=False, indent=2)
        logger.warning(f"재시도 후에도 {len(still_failing)}개의 Gliffy 썸네일 다운로드에 실패했습니다.")
    else:
        logger.info("모든 Gliffy 썸네일 재시도에 성공했습니다!")
