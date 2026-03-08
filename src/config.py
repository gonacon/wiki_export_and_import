import os
import logging
import sys
import requests
import threading

class Config:
    def __init__(self):
        # 기본값 (환경변수 우선)
        self.lock = threading.RLock()
        self.OLD_BASE = os.getenv("OLD_BASE", "https://wiki.11stcorp.com")
        self.NEW_BASE = os.getenv("NEW_BASE", "https://wiki.skplanet.com")
        self.NEW_PARENT_PAGE_ID = os.getenv("NEW_PARENT_PAGE_ID", "")

        self.OLD_USER = os.getenv("O_USER")
        self.OLD_PASS = os.getenv("O_PASS")
        self.NEW_USER = os.getenv("N_USER")
        self.NEW_PASS = os.getenv("N_PASS")

        self.SPACE = os.getenv("SPACE", "GFTCDEV")
        self.NEW_SPACE = os.getenv("NEW_SPACE", "~1004592")

        self.EXPORT_DIR = os.getenv("EXPORT_DIR", "../wiki_down_upload_export")
        self.FAILED_GLIFFY_LOG = os.path.join(self.EXPORT_DIR, "failed_gliffy.json")
        self.RESUME_FILE = os.path.join(self.EXPORT_DIR, "resume_state.json")

        self.MAX_WORKERS = int(os.getenv("MAX_WORKERS", "8"))
        self.MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))
        self.RETRY_DELAY = int(os.getenv("RETRY_DELAY", "2"))

        # Sessions (shared)
        self.old_session = requests.Session()
        self.new_session = requests.Session()

        # logger will be set later when config object created
        self.logger = None

    def ensure_dirs(self):
        os.makedirs(self.EXPORT_DIR, exist_ok=True)


# 글로벌 인스턴스
cfg = Config()

# 로거 설정 (모듈 레벨로 설정하여 동일 로거를 공유)
def setup_logger(cfg_obj=None):
    c = cfg_obj or cfg
    c.ensure_dirs()
    logger = logging.getLogger("wiki_migrate")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    fh = logging.FileHandler(os.path.join(c.EXPORT_DIR, "migrate.log"), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    if not logger.handlers:
        logger.addHandler(ch)
        logger.addHandler(fh)

    c.logger = logger
    return logger

# 초기화
logger = setup_logger(cfg)

# 편의용: 모듈 레벨 이름(기존 코드가 직접 import한 경우를 최소화하기 위해 권장하지 않지만 남겨둠)
old_session = cfg.old_session
new_session = cfg.new_session
EXPORT_DIR = cfg.EXPORT_DIR
OLD_BASE = cfg.OLD_BASE
NEW_BASE = cfg.NEW_BASE
MAX_WORKERS = cfg.MAX_WORKERS
MAX_RETRIES = cfg.MAX_RETRIES
RETRY_DELAY = cfg.RETRY_DELAY
FAILED_GLIFFY_LOG = cfg.FAILED_GLIFFY_LOG
RESUME_FILE = cfg.RESUME_FILE
