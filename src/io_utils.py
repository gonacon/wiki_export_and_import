import os
import json
import time
from .config import EXPORT_DIR, OLD_BASE, old_session, MAX_RETRIES, RETRY_DELAY
from .utils import safe_folder_name
import logging

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

