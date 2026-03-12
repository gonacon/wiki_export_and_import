import os
import logging
import sys
import requests

# 기본 설정
OLD_BASE = os.getenv("OLD_BASE", "https://wiki.11stcorp.com")
NEW_BASE = os.getenv("NEW_BASE", "https://wiki.skplanet.com")
# 사용자 pageId "728909587"
NEW_PARENT_PAGE_ID = os.getenv("NEW_PARENT_PAGE_ID", "")

OLD_USER = os.getenv("O_USER")
OLD_PASS = os.getenv("O_PASS")
NEW_USER = os.getenv("N_USER")
NEW_PASS = os.getenv("N_PASS")

SPACE = os.getenv("SPACE", "GFTCDEV")
NEW_SPACE = os.getenv("NEW_SPACE", "~1004592")

EXPORT_DIR = os.getenv("EXPORT_DIR", "./wiki_down_upload_export")
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

# 초기화
logger = setup_logger()


def login(session, base, user, password):
    """로그인: 세션에 인증 쿠키를 설정합니다. 사용자명/비밀번호가 없으면 경고 후 리턴합니다.

    이 함수는 기존 single-file 구현과 유사하게 POST /dologin.action을 호출합니다.
    실패하면 예외를 발생시켜 호출자에서 처리하게 합니다.
    """
    if not user or not password:
        logger.warning(f"로그인 정보 미설정: base={base} (user 또는 password 없음). 로그인 건너뜀")
        return
    url = f"{base}/dologin.action"
    data = {
        "os_username": user,
        "os_password": password,
        "login": "Log in",
    }
    try:
        r = session.post(url, data=data, timeout=15)
        r.raise_for_status()
    except Exception as e:
        logger.error(f"로그인 실패: {base} (error={e})")
        raise
    logger.info(f"로그인 성공: {base}")
