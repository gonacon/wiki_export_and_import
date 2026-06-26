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
# SPACE = os.getenv("SPACE", "Gifticonteam")
# SPACE = os.getenv("SPACE", "GIFTICONAF")
NEW_SPACE = os.getenv("NEW_SPACE", "~1004592")
# NEW_SPACE = os.getenv("NEW_SPACE", "GIFTICON")

EXPORT_DIR = os.getenv("EXPORT_DIR", "./wiki_down_upload_export")
FAILED_GLIFFY_LOG = os.path.join(EXPORT_DIR, "failed_gliffy.json")
RESUME_FILE = os.path.join(EXPORT_DIR, "resume_state.json")

MAX_WORKERS = int(os.getenv("MAX_WORKERS", "8"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "2"))

# 세션
old_session = requests.Session()
new_session = requests.Session()

# If credentials are provided via environment variables, set them as basic-auth
# on the sessions. For Atlassian Cloud it's common to use email:APITOKEN as
# Basic Auth. This ensures REST API calls use the same auth method.
if NEW_USER and NEW_PASS:
    # Set basic auth on the session (useful for Atlassian Cloud: email:APITOKEN)
    try:
        new_session.auth = (NEW_USER, NEW_PASS)
    except Exception:
        pass

if OLD_USER and OLD_PASS:
    try:
        old_session.auth = (OLD_USER, OLD_PASS)
    except Exception:
        pass

# 로거 설정

def setup_logger():
    # Ensure export dir exists before creating file handler
    os.makedirs(EXPORT_DIR, exist_ok=True)
    logger = logging.getLogger("wiki_migrate")
    logger.setLevel(logging.DEBUG)
    # Prevent messages from also being handled by the root logger
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    # Console handler (always present)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    handlers = [ch]

    # File handler: wrap in try/except so logger still works even if file can't be created
    log_path = os.path.join(EXPORT_DIR, "migrate.log")
    try:
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        handlers.append(fh)
    except Exception as e:
        # If file handler can't be created (permission, invalid path, etc.),
        # fall back to console-only and emit a warning to stderr.
        print(f"Warning: could not create log file handler ({log_path}): {e}", file=sys.stderr)

    # Replace existing handlers to avoid duplicates when module is re-imported
    if logger.handlers:
        # Clear existing handlers added previously
        logger.handlers.clear()

    for h in handlers:
        logger.addHandler(h)

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

    # 1) 먼저 기존 방식(폼 POST)으로 로그인 시도
    try:
        r = session.post(url, data=data, timeout=15, allow_redirects=True)
        r.raise_for_status()
        logger.info(f"폼 로그인 성공: {base}")
        return
    except requests.exceptions.HTTPError as he:
        # 403/401 등 폼 로그인 실패인 경우, 기본 인증(Basic Auth)으로 대체 시도
        status = getattr(locals().get('r', None), 'status_code', None)
        logger.warning(f"폼 로그인 실패: {base} (status={status}, error={he}). 기본 인증으로 재시도합니다.")

        # 2) Basic Auth 대체 방식 시도: session.auth에 설정하고 REST API에 접근 가능한지 확인
        session.auth = (user, password)
        test_url = f"{base}/rest/api/space?limit=1"
        try:
            tr = session.get(test_url, timeout=15)
            if tr.ok:
                # 간단 검증: JSON 응답이 오면 성공으로 간주
                ct = tr.headers.get('Content-Type', '').lower()
                if 'json' in ct or tr.text.strip().startswith('{'):
                    logger.info(f"기본 인증 성공: {base} (session.auth 설정). REST API 접근 가능")
                    return
                else:
                    logger.warning(f"기본 인증 응답은 JSON이 아님(status={tr.status_code}). 응답 앞부분: {tr.text[:200]!r}")
            else:
                logger.warning(f"기본 인증으로도 접근 불가: status={tr.status_code}")
        except Exception as e2:
            logger.warning(f"기본 인증 시도 중 오류 발생: {e2}")

        # 모든 대체 시도 실패 시 원래 예외를 재발생시켜 호출자에게 알림
        logger.error(f"로그인 실패: {base} (form login failed and basic auth fallback failed)")
        raise
    except Exception as e:
        logger.error(f"로그인 실패: {base} (error={e})")
        raise
