import os
import logging
import sys
import requests

# 기본 설정
OLD_BASE = os.getenv("OLD_BASE", "https://wiki.11stcorp.com")
NEW_BASE = os.getenv("NEW_BASE", "https://wiki.skplanet.com")
# NEW_PARENT_PAGE_ID = os.getenv("NEW_PARENT_PAGE_ID", "728909587")
NEW_PARENT_PAGE_ID = os.getenv("NEW_PARENT_PAGE_ID", "")

OLD_USER = os.getenv("O_USER")
OLD_PASS = os.getenv("O_PASS")
NEW_USER = os.getenv("N_USER")
NEW_PASS = os.getenv("N_PASS")

SPACE = os.getenv("SPACE", "GFTCDEV")
NEW_SPACE = os.getenv("NEW_SPACE", "~1004592")

EXPORT_DIR = os.getenv("EXPORT_DIR", "../wiki_down_upload_export")
FAILED_GLIFFY_LOG = os.path.join(EXPORT_DIR, "failed_gliffy.json")
RESUME_FILE = os.path.join(EXPORT_DIR, "resume_state.json")

MAX_WORKERS = int(os.getenv("MAX_WORKERS", "8"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "2"))

# 세션
old_session = requests.Session()
new_session = requests.Session()

# 로거 설정

def setup_logger():
    os.makedirs(EXPORT_DIR, exist_ok=True)
    logger = logging.getLogger("wiki_migrate")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    fh = logging.FileHandler(os.path.join(EXPORT_DIR, "migrate.log"), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # 중복 핸들러 추가 방지
    if not logger.handlers:
        logger.addHandler(ch)
        logger.addHandler(fh)
    return logger

logger = setup_logger()
