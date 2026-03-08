"""
Confluence Wiki Migration Tool
================================
기존 Confluence 위키 공간을 자동으로 export → 로컬 저장 → 새 위키 import

Usage:
  python down_and_upload_wiki.py export   [--page-id PAGE_ID] [--inline-images]
  python down_and_upload_wiki.py import   [--inline-images]
  python down_and_upload_wiki.py migrate  [--page-id PAGE_ID] [--inline-images]
"""

import requests
import os
import json
import sys
import re
import base64
import logging
import argparse
import time
import getpass
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from markdownify import markdownify as md_convert
import markdown2
import html

# --- 내부 sanitizer 구현 (single-file용) ----------------------------------
class _Sanitizer:
    """
    페이지 storage HTML을 타깃 Confluence(예: 7.19)에 맞게 전처리합니다.
      - remove_macro_attrs : ac:schema-version, ac:macro-id 등 문제 속성 제거
      - sanitize_code_macros : <ac:structured-macro ac:name="code"> → <pre><code>
      - sanitize_gliffy_macros : <ac:structured-macro ac:name="gliffy"> → <img> / <a> / 폴백
    """

    @staticmethod
    def remove_macro_attrs(html_text):
        out = re.sub(r'\s+ac:schema-version="[^"]+"', "", html_text, flags=re.IGNORECASE)
        out = re.sub(r'\s+ac:macro-id="[^"]+"', "", out, flags=re.IGNORECASE)
        return out

    @staticmethod
    def sanitize_code_macros(html_text):
        """
        <ac:structured-macro ac:name="code"> ... <![CDATA[...]]> ... </ac:structured-macro>
        → <pre><code class="language-{lang}">...</code></pre>
        """
        # 1차: CDATA 영역까지 정확히 캡처
        CODE_FULL_RE = re.compile(
            r'<ac:structured-macro\b[^>]*ac:name="code"[^>]*>'
            r'.*?'
            r'<ac:plain-text-body>\s*<!\[CDATA\[(.*?)\]\]>\s*</ac:plain-text-body>'
            r'.*?</ac:structured-macro>',
            re.DOTALL | re.IGNORECASE,
            )
        # 언어 파라미터 추출용
        LANG_RE = re.compile(
            r'<ac:parameter\s+ac:name="language"\s*>(.*?)</ac:parameter>',
            re.DOTALL | re.IGNORECASE,
            )

        def _repl_full(m):
            code_text = m.group(1)
            lang_m = LANG_RE.search(m.group(0))
            lang = (lang_m.group(1).strip().lower() if lang_m else "") or "text"
            return f'<pre><code class="language-{lang}">{html.escape(code_text)}</code></pre>'

        result, n = CODE_FULL_RE.subn(_repl_full, html_text)
        if n:
            return result

        # 2차 폴백: CDATA 없는 code 매크로
        CODE_ANY_RE = re.compile(
            r'<ac:structured-macro\b[^>]*ac:name="code"[^>]*>(.*?)</ac:structured-macro>',
            re.DOTALL | re.IGNORECASE,
            )

        def _repl_any(m):
            body = m.group(1)
            cdata = re.search(r'<!\[CDATA\[(.*?)\]\]>', body, re.DOTALL)
            code_text = cdata.group(1) if cdata else re.sub(r'<[^>]+>', '', body).strip()
            lang_m = LANG_RE.search(m.group(0))
            lang = (lang_m.group(1).strip().lower() if lang_m else "") or "text"
            return f'<pre><code class="language-{lang}">{html.escape(code_text)}</code></pre>'

        return CODE_ANY_RE.sub(_repl_any, html_text)

    @staticmethod
    def sanitize_gliffy_macros(html_text, attachments_dir=None):
        """
        Gliffy 매크로를 찾아 attachments 에 관련 이미지가 있으면 <img> 로 대체하고,
        없으면 링크 또는 폴백 박스로 대체합니다.

        파일명 우선순위:
          1) gliffy_{displayName}.png  (download_gliffy_thumbnails 가 저장한 파일)
          2) gliffy_{macroId}.png
          3) macroId 그대로
          4) displayName 변형 (.png / .svg / .gliffy)
          5) attachments 내 'gliffy' 포함 파일
        """
        GLIFFY_RE = re.compile(
            r'<ac:structured-macro\b[^>]*ac:name="gliffy"[^>]*>.*?</ac:structured-macro>',
            re.DOTALL | re.IGNORECASE,
            )
        PARAM_RE = re.compile(
            r'<ac:parameter\s+ac:name="([^"]+)"\s*>(.*?)</ac:parameter>',
            re.DOTALL | re.IGNORECASE,
            )

        def _extract(macro_html):
            return {m.group(1).strip(): m.group(2).strip()
                    for m in PARAM_RE.finditer(macro_html)}

        def _safe(s, maxlen=80):
            return re.sub(r'[^\w\-.]', '_', s)[:maxlen]

        def _repl(m):
            params  = _extract(m.group(0))
            display = (params.get('displayName') or params.get('name')
                       or params.get('macroId') or 'Gliffy diagram')
            mid     = params.get('macroId', '')

            candidates = []
            if attachments_dir and os.path.isdir(attachments_dir):
                files     = os.listdir(attachments_dir)
                lower_map = {fn.lower(): fn for fn in files}

                # 1·2순위: download_gliffy_thumbnails 가 저장한 파일
                for key in [f"gliffy_{_safe(display)}.png",
                            f"gliffy_{_safe(mid)}.png" if mid else None]:
                    if key and key.lower() in lower_map:
                        candidates.append(lower_map[key.lower()])

                # 3순위: macroId 그대로
                if mid and mid.lower() in lower_map:
                    candidates.append(lower_map[mid.lower()])

                # 4순위: displayName 변형
                dn = params.get('displayName', '')
                for variant in [dn, dn + '.png', dn + '.svg', dn + '.gliffy']:
                    if variant and variant.lower() in lower_map:
                        candidates.append(lower_map[variant.lower()])

                # 5순위: attachments 내 gliffy 포함 파일
                for fn in files:
                    if 'gliffy' in fn.lower() or (mid and mid.lower() in fn.lower()):
                        candidates.append(fn)

                # 이미지 확장자 우선 반환 → <ac:image> 첨부 매크로로 대체
                for ext in ('.png', '.svg', '.jpg', '.jpeg'):
                    for c in candidates:
                        if c.lower().endswith(ext):
                            # Confluence storage format: 첨부파일 이미지 참조
                            return (
                                f'<ac:image>'
                                f'<ri:attachment ri:filename="{html.escape(c)}" />'
                                f'</ac:image>'
                            )
                # 이미지가 없고 .gliffy 원본만 있으면 다운로드 링크
                if candidates:
                    return (
                        f'<a href="./attachments/{html.escape(candidates[0])}">'
                        f'{html.escape(display)} (diagram)</a>'
                    )

            # ── 첨부파일 전혀 없음 ──────────────────────────────────────────
            # ⚠️  <ac:structured-macro ac:name="gliffy"> 를 그대로 두면
            #    타깃(7.19)에 Gliffy 플러그인이 없거나 매크로 ID가 달라
            #    "Unknown macro: gliffy" 오류가 발생하므로
            #    안전한 HTML 폴백으로 완전히 대체합니다.
            return (
                f'<div class="gliffy-macro-fallback" '
                f'style="border:1px dashed #f0a;padding:8px;background:#fff7e6;'
                f'color:#555;font-size:0.9em;">'
                f'⚠️ Gliffy 다이어그램: <strong>{html.escape(display)}</strong>'
                f'<br/><small>(첨부파일 없음 — 원본 위키에서 이미지로 저장 후 재-export 권장)</small>'
                f'</div>'
            )

        return GLIFFY_RE.sub(_repl, html_text)

sanitizer = _Sanitizer()

# ─── 설정 ───────────────────────────────────────────────────────────────────
OLD_BASE = "https://wiki.11stcorp.com"
NEW_BASE = "https://wiki.skplanet.com"

# 새 위키에서 최상위 부모로 지정할 페이지 ID (없으면 None)
NEW_PARENT_PAGE_ID = "737063089"

OLD_USER = os.getenv("O_USER")
OLD_PASS = os.getenv("O_PASS")

NEW_USER = os.getenv("N_USER")
NEW_PASS = os.getenv("N_PASS")

SPACE = "GFTCDEV"          # 기존 위키 Space Key (export 대상)
NEW_SPACE = "~1004592"    # 새 위키 Space Key  (import 대상)

EXPORT_DIR = "../wiki_down_upload_export"

# 동시 다운로드 스레드 수
MAX_WORKERS = 8

# 재시도 횟수 / 대기 시간(초)
MAX_RETRIES = 3
RETRY_DELAY = 2

# ─── 세션 ────────────────────────────────────────────────────────────────────
old_session = requests.Session()
new_session = requests.Session()

# ─── 로거 설정 ───────────────────────────────────────────────────────────────
def setup_logger():
    os.makedirs(EXPORT_DIR, exist_ok=True)
    logger = logging.getLogger("wiki_migrate")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    # 콘솔 핸들러
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    # 파일 핸들러
    fh = logging.FileHandler(os.path.join(EXPORT_DIR, "migrate.log"), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger

logger = setup_logger()

# ─── Resume 상태 관리 ────────────────────────────────────────────────────────
RESUME_FILE = os.path.join(EXPORT_DIR, "resume_state.json")

def load_resume_state():
    if os.path.exists(RESUME_FILE):
        with open(RESUME_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"downloaded": [], "uploaded": [], "page_map": {}}

def save_resume_state(state):
    with open(RESUME_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# ─── 재시도 데코레이터 ────────────────────────────────────────────────────────
def with_retry(func, *args, retries=MAX_RETRIES, delay=RETRY_DELAY, **kwargs):
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exc = e
            logger.warning(f"시도 {attempt}/{retries} 실패: {e}")
            if attempt < retries:
                time.sleep(delay * attempt)
    logger.error(f"최대 재시도 초과: {last_exc}")
    raise last_exc

# ─── 로그인 ──────────────────────────────────────────────────────────────────
def login(session, base, user, password):
    url = f"{base}/dologin.action"
    data = {
        "os_username": user,
        "os_password": password,
        "login": "Log in",
    }
    r = session.post(url, data=data)
    if r.status_code != 200:
        logger.error(f"로그인 실패: {base} (status={r.status_code})")
        sys.exit(1)
    logger.info(f"로그인 성공: {base}")

# ─── 페이지 목록 수집 ─────────────────────────────────────────────────────────
def get_all_pages(root_page_id=None):
    """
    root_page_id 지정 시 해당 페이지와 모든 하위 페이지만 수집.
    없으면 전체 Space 페이지 수집.
    """
    if root_page_id:
        return get_descendant_pages(root_page_id)

    pages = []
    start = 0
    limit = 100

    while True:
        url = f"{OLD_BASE}/rest/api/content"
        params = {
            "spaceKey": SPACE,
            "limit": limit,
            "start": start,
            "expand": "body.storage,ancestors",
        }
        r = with_retry(old_session.get, url, params=params)
        data = r.json()
        results = data.get("results", [])
        if not results:
            break
        pages += results
        start += limit
        logger.debug(f"페이지 수집 중... 현재 {len(pages)}개")

    logger.info(f"전체 페이지 수집 완료: {len(pages)}개")
    return pages


def get_descendant_pages(root_page_id):
    """지정 페이지와 모든 하위(descendants) 페이지를 재귀적으로 수집"""
    pages = []

    # 루트 페이지 자체 가져오기
    url = f"{OLD_BASE}/rest/api/content/{root_page_id}"
    params = {"expand": "body.storage,ancestors"}
    r = with_retry(old_session.get, url, params=params)
    root = r.json()
    pages.append(root)

    # 하위 페이지 재귀 수집
    def collect_children(page_id):
        start = 0
        limit = 100
        while True:
            url = f"{OLD_BASE}/rest/api/content/{page_id}/child/page"
            params = {
                "limit": limit,
                "start": start,
                "expand": "body.storage,ancestors",
            }
            r = with_retry(old_session.get, url, params=params)
            results = r.json().get("results", [])
            if not results:
                break
            for child in results:
                pages.append(child)
                collect_children(child["id"])
            start += limit

    collect_children(root_page_id)
    logger.info(f"하위 페이지 수집 완료 (root={root_page_id}): {len(pages)}개")
    return pages

# ─── 이미지 링크 수정 ─────────────────────────────────────────────────────────
def fix_image_links(markdown_text, attachments_dir):
    """
    위키 내부 이미지 태그를 로컬 상대 경로로 변환.
    예: <ac:image><ri:attachment ri:filename="img.png"/></ac:image>
        → ![img.png](./attachments/img.png)
    """
    # Confluence storage format 이미지 패턴
    pattern = re.compile(
        r'<ac:image[^>]*>.*?<ri:attachment\s+ri:filename="([^"]+)"[^/]*/?>.*?</ac:image>',
        re.DOTALL | re.IGNORECASE,
        )
    def replace_match(m):
        fname = m.group(1)
        return f"![{fname}](./attachments/{fname})"

    text = pattern.sub(replace_match, markdown_text)

    # 마크다운 변환 후 남은 ![]() 링크 중 절대 URL을 상대경로로 수정
    text = re.sub(
        r'!\[([^]]*)](https?://[^)]+/([^/)]+\.(png|jpg|jpeg|gif|svg|webp|bmp)))',
        lambda m: f"![{m.group(1)}](./attachments/{m.group(3)})",
        text,
        flags=re.IGNORECASE,
    )
    return text


def convert_images_to_inline(markdown_text, attachments_dir):
    """
    ./attachments/xxx 이미지 링크를 base64 inline 데이터로 변환.
    예: ![img.png](./attachments/img.png) → ![img.png](data:image/png;base64,...)
    """
    def replacer(m):
        alt = m.group(1)
        fname = m.group(2)
        fpath = os.path.join(attachments_dir, fname)
        if not os.path.exists(fpath):
            return m.group(0)
        ext = fname.rsplit(".", 1)[-1].lower()
        mime_map = {
            "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "gif": "image/gif", "svg": "image/svg+xml", "webp": "image/webp",
            "bmp": "image/bmp",
        }
        mime = mime_map.get(ext, "application/octet-stream")
        with open(fpath, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return f"![{alt}](data:{mime};base64,{b64})"

    pattern = re.compile(r'!\[([^]]*)][(]\./attachments/([^)]+)[)]')
    return pattern.sub(replacer, markdown_text)


def markdown_to_confluence_html(markdown_text):
    """
    마크다운을 Confluence Storage Format HTML로 변환.
    - 마크다운 → HTML 변환
    - 특수문자 이스케이프
    - Confluence 호환 포맷
    """
    # 마크다운을 HTML로 변환
    html_text = markdown2.markdown(markdown_text, extras=['tables', 'fenced-code-blocks'])

    # 특수문자 이스케이프 (XML/XHTML 호환성)
    html_text = html.escape(html_text, quote=True)

    # 다시 HTML 태그를 언이스케이프 (이미 변환된 태그들만)
    html_text = html_text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#x27;", "'")

    return html_text


def convert_local_imgs_to_acimage(html_text):
    """
    로컬/상대 이미지 참조를 Confluence storage attachment 매크로로 변환.
    변환 대상:
    - <img src="./attachments/file.png" ...>
    - ![alt](./attachments/file.png)
    비대상:
    - data:image/... inline
    - http(s):// 원격 URL
    """
    from urllib.parse import unquote

    def to_acimage(filename):
        safe_name = html.escape(filename, quote=True)
        return f'<ac:image><ri:attachment ri:filename="{safe_name}" /></ac:image>'

    # 마크다운 이미지 문법을 먼저 변환
    md_pattern = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')

    def md_repl(m):
        src = m.group(1).strip()
        if src.startswith("data:") or re.match(r'^(https?:)?//', src, flags=re.IGNORECASE):
            return m.group(0)
        fname = os.path.basename(unquote(src.split("?", 1)[0]))
        if not fname:
            return m.group(0)
        return to_acimage(fname)

    converted = md_pattern.sub(md_repl, html_text)

    # HTML img 태그를 변환
    img_pattern = re.compile(r'<img\b[^>]*\bsrc=("|\')(.*?)\1[^>]*>', re.IGNORECASE)

    def img_repl(m):
        src = m.group(2).strip()
        if src.startswith("data:") or re.match(r'^(https?:)?//', src, flags=re.IGNORECASE):
            return m.group(0)
        fname = os.path.basename(unquote(src.split("?", 1)[0]))
        if not fname:
            return m.group(0)
        return to_acimage(fname)

    return img_pattern.sub(img_repl, converted)


def convert_data_uri_imgs_to_acimage(html_text, attachments_dir):
    """
    data URI 이미지(<img src="data:image/...">)를 첨부파일 매크로로 변환.
    page.md가 inline(base64)로 저장된 경우 alt/title의 파일명을 사용해 매핑한다.
    """
    def to_acimage(filename):
        safe_name = html.escape(filename, quote=True)
        return f'<ac:image><ri:attachment ri:filename="{safe_name}" /></ac:image>'

    img_tag_pattern = re.compile(r'<img\b[^>]*>', re.IGNORECASE)

    def extract_attr(tag, attr):
        m = re.search(rf'\b{attr}\s*=\s*(["\'])(.*?)\1', tag, flags=re.IGNORECASE)
        return m.group(2).strip() if m else ""

    def repl(m):
        tag = m.group(0)
        src = extract_attr(tag, "src")
        if not src.startswith("data:image/"):
            return tag

        # markdown2가 ![filename](data:...)를 <img alt="filename" src="data:...">로 만든다.
        alt = extract_attr(tag, "alt")
        title = extract_attr(tag, "title")
        filename = (alt or title).strip()
        if not filename:
            logger.warning("data URI 이미지 변환 스킵: alt/title 파일명 없음")
            return tag

        # alt에 경로가 포함될 수 있어 파일명만 사용
        filename = os.path.basename(filename)
        fpath = os.path.join(attachments_dir, filename)
        if not os.path.exists(fpath):
            logger.warning(f"data URI 이미지 변환 스킵: 첨부파일 없음 [{filename}]")
            return tag

        return to_acimage(filename)

    return img_tag_pattern.sub(repl, html_text)

# ─── 단일 페이지 저장 ─────────────────────────────────────────────────────────
def safe_folder_name(title):
    return re.sub(r'[<>:"/\\|?*]', '_', title)


def fix_image_links_html(html_text, attachments_dir):
    """
    Confluence storage HTML 내의 <ac:image> 태그를 로컬 상대경로의 <img> 태그로 변환.
    예: <ac:image>...<ri:attachment ri:filename="img.png"/>...</ac:image>
         -> <img src="./attachments/img.png" alt="img.png" />
    또한 절대 URL로 연결된 이미지 링크도 ./attachments/로 변경.
    """
    # <ac:image> ... <ri:attachment ri:filename="fname" .../> ... </ac:image>
    pattern = re.compile(r'<ac:image[^>]*>.*?<ri:attachment\s+ri:filename="([^\"]+)"[^/]*/?>.*?</ac:image>', re.DOTALL | re.IGNORECASE)
    def repl(m):
        fname = m.group(1)
        return f'<img src="./attachments/{fname}" alt="{fname}" />'
    text = pattern.sub(repl, html_text)

    # 절대 URL로 연결된 이미지들을 attachments로 교체 (마지막 경로명으로)
    text = re.sub(r'<img[^>]+src=["\']https?://[^"\']*/([^/"\']+\.(?:png|jpg|jpeg|gif|svg|webp|bmp))["\']',
                  lambda m: f'<img src="./attachments/{m.group(1)}"', text, flags=re.IGNORECASE)
    return text


def save_page(page, index, inline_images=False):
    title = page["title"]
    folder = os.path.join(EXPORT_DIR, "pages", f"{index:04d}_{safe_folder_name(title)}")
    os.makedirs(os.path.join(folder, "attachments"), exist_ok=True)

    html = page["body"]["storage"]["value"]

    # 저장: 원본 Confluence storage HTML을 함께 보존
    try:
        with open(os.path.join(folder, "page.storage.html"), "w", encoding="utf-8") as f:
            f.write(html)
    except Exception as e:
        logger.warning(f"page.storage.html 저장 실패 [{title}]: {e}")

    # HTML 단계에서 이미지 태그를 로컬 <img>로 변환 -> markdownify가 이미지로 변환하도록 함
    html_local = fix_image_links_html(html, os.path.join(folder, "attachments"))

    # HTML → Markdown 변환
    markdown = md_convert(html_local, heading_style="ATX")

    # inline 변환 옵션은 attachments가 다운로드된 이후에 수행되므로 여기서는 적용하지 않음

    with open(os.path.join(folder, "page.md"), "w", encoding="utf-8") as f:
        f.write(markdown)

    parent = None
    if page.get("ancestors"):
        parent = page["ancestors"][-1]["id"]

    meta = {
        "id": page["id"],
        "title": title,
        "parent": parent,
    }
    with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return folder

# ─── 첨부파일 다운로드 ────────────────────────────────────────────────────────
def download_attachments(page, folder):
    url = f"{OLD_BASE}/rest/api/content/{page['id']}/child/attachment"
    r = with_retry(old_session.get, url)
    results = r.json().get("results", [])

    for att in results:
        link = OLD_BASE + att["_links"]["download"]
        name = att["title"]
        path = os.path.join(folder, "attachments", name)
        if os.path.exists(path):
            logger.debug(f"첨부파일 이미 존재 (skip): {name}")
            continue
        try:
            data = with_retry(old_session.get, link)
            with open(path, "wb") as f:
                f.write(data.content)
            logger.debug(f"첨부파일 다운로드: {name}")
        except Exception as e:
            logger.error(f"첨부파일 다운로드 실패 [{name}]: {e}")

# ─── Gliffy 썸네일 다운로드 ──────────────────────────────────────────────────
def download_gliffy_thumbnails(page, folder):
    """
    page.storage.html 에서 Gliffy 매크로를 찾아
    Confluence REST API로 PNG 썸네일을 다운로드하여 attachments/ 에 저장합니다.

    Confluence REST API:
      GET /rest/gliffy/1.0/embeddedDiagrams/{macroId}.png?pageId={pageId}
      (서버 버전에 따라 경로 다를 수 있음 - 두 가지 경로를 시도)

    저장 파일명 규칙:
      gliffy_{macroId}.png  또는  gliffy_{name}.png  (파일명 안전 처리 후)
    """
    storage_path = os.path.join(folder, "page.storage.html")
    if not os.path.exists(storage_path):
        return

    content = open(storage_path, "r", encoding="utf-8", errors="ignore").read()
    att_dir = os.path.join(folder, "attachments")
    os.makedirs(att_dir, exist_ok=True)

    # Gliffy 매크로 전체 추출
    GLIFFY_RE = re.compile(
        r'<ac:structured-macro[^>]+ac:name="gliffy"[^>]*>(.*?)</ac:structured-macro>',
        re.DOTALL | re.IGNORECASE,
        )
    PARAM_RE = re.compile(
        r'<ac:parameter\s+ac:name="([^"]+)"\s*>(.*?)</ac:parameter>',
        re.DOTALL | re.IGNORECASE,
        )

    for macro_match in GLIFFY_RE.finditer(content):
        macro_body = macro_match.group(0)
        params = {m.group(1): m.group(2).strip() for m in PARAM_RE.finditer(macro_body)}

        macro_id = params.get("macroId", "")
        display_name = params.get("displayName") or params.get("name") or macro_id
        page_id = page["id"]

        # 저장 파일명: gliffy_{macroId}.png (안전한 문자만)
        safe_name = re.sub(r'[^\w\-.]', '_', display_name)[:80]
        out_filename = f"gliffy_{safe_name}.png"
        out_path = os.path.join(att_dir, out_filename)

        if os.path.exists(out_path):
            logger.debug(f"Gliffy 썸네일 이미 존재 (skip): {out_filename}")
            continue

        # ── Confluence Server Gliffy 썸네일 API 엔드포인트 (우선순위 순) ──────
        # 참고: Confluence Server + Gliffy 플러그인 설치 시 아래 URL들이 동작함
        candidate_urls = []

        # 1순위: Gliffy REST API (Gliffy 플러그인 설치 시)
        if macro_id:
            candidate_urls.append(
                f"{OLD_BASE}/rest/gliffy/1.0/embeddedDiagrams/{macro_id}.png"
                f"?pageId={page_id}"
            )
        # 2순위: Gliffy servlet export (name 파라미터 사용)
        if display_name:
            from urllib.parse import quote as url_quote
            candidate_urls.append(
                f"{OLD_BASE}/plugins/servlet/gliffy/export"
                f"?pageId={page_id}&name={url_quote(display_name)}&format=png"
            )
        # 3순위: 다이어그램 이름으로 직접 PNG 첨부파일 다운로드 시도
        if display_name:
            candidate_urls.append(
                f"{OLD_BASE}/download/attachments/{page_id}/{display_name}.png"
            )
        # 4순위: macroId 기반 첨부파일 직접 다운로드
        if macro_id:
            candidate_urls.append(
                f"{OLD_BASE}/download/attachments/{page_id}/{macro_id}.png"
            )

        downloaded = False
        for url in candidate_urls:
            try:
                resp = old_session.get(url, timeout=15)
                content_type = resp.headers.get("Content-Type", "")
                if resp.status_code == 200 and content_type.startswith("image/"):
                    with open(out_path, "wb") as f:
                        f.write(resp.content)
                    logger.info(
                        f"Gliffy 썸네일 다운로드 성공: {out_filename} "
                        f"(url={url}, size={len(resp.content)}bytes)"
                    )
                    downloaded = True
                    break
                else:
                    logger.debug(
                        f"Gliffy URL 응답 스킵: status={resp.status_code} "
                        f"content_type={content_type} url={url}"
                    )
            except Exception as e:
                logger.debug(f"Gliffy 썸네일 URL 실패 [{url}]: {e}")

        if not downloaded:
            logger.warning(
                f"Gliffy 썸네일 다운로드 실패 [{display_name}] (pageId={page_id}, macroId={macro_id}) "
                f"— export 시 Gliffy 이미지가 없으면 import 후 폴백 박스로 표시됩니다."
            )

# ─── 단일 페이지 처리 (다운로드 워커) ──────────────────────────────────────────
def process_page(args):
    i, page, inline_images, resume_state = args
    page_id = page["id"]

    if page_id in resume_state["downloaded"]:
        logger.debug(f"이미 다운로드됨 (skip): {page['title']}")
        return page_id, True, None

    try:
        # 먼저 기본 markdown(이미지 링크 포함) 생성
        folder = save_page(page, i, inline_images=False)
        # 첨부파일 다운로드를 먼저 수행
        download_attachments(page, folder)
        # Gliffy 매크로가 있으면 썸네일(PNG) 자동 다운로드
        download_gliffy_thumbnails(page, folder)

        # inline 옵션이 켜져 있으면 다운로드한 파일로부터 base64 변환을 적용
        if inline_images:
            md_path = os.path.join(folder, "page.md")
            if os.path.exists(md_path):
                md_text = open(md_path, "r", encoding="utf-8").read()
                md_text = convert_images_to_inline(md_text, os.path.join(folder, "attachments"))
                open(md_path, "w", encoding="utf-8").write(md_text)

        return page_id, True, None
    except Exception as e:
        logger.error(f"페이지 처리 실패 [{page['title']}]: {e}")
        return page_id, False, str(e)

# ─── 전체 Export ──────────────────────────────────────────────────────────────
def export_all(root_page_id=None, inline_images=False):
    os.makedirs(os.path.join(EXPORT_DIR, "pages"), exist_ok=True)

    resume_state = load_resume_state()
    failed_pages = []

    pages = get_all_pages(root_page_id=root_page_id)
    logger.info(f"다운로드 대상 페이지: {len(pages)}개")

    # pages.json 저장 (전체 메타 백업)
    with open(os.path.join(EXPORT_DIR, "pages.json"), "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False, indent=2)

    tasks = [(i, page, inline_images, resume_state) for i, page in enumerate(pages)]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_page, task): task for task in tasks}
        with tqdm(total=len(tasks), desc="Export", unit="page") as pbar:
            for future in as_completed(futures):
                page_id, success, err = future.result()
                if success:
                    if page_id not in resume_state["downloaded"]:
                        resume_state["downloaded"].append(page_id)
                    save_resume_state(resume_state)
                else:
                    failed_pages.append({"id": page_id, "error": err})
                pbar.update(1)

    if failed_pages:
        fail_path = os.path.join(EXPORT_DIR, "failed_pages.json")
        with open(fail_path, "w", encoding="utf-8") as f:
            json.dump(failed_pages, f, ensure_ascii=False, indent=2)
        logger.warning(f"실패한 페이지 {len(failed_pages)}개 → {fail_path}")

    logger.info("Export 완료")

# ─── 페이지 생성 (새 위키) ────────────────────────────────────────────────────
def get_page_by_title(title):
    """제목으로 페이지 조회"""
    url = f"{NEW_BASE}/rest/api/content"
    params = {
        "title": title,
        "spaceKey": NEW_SPACE,
        "expand": "version"
    }
    try:
        r = new_session.get(url, params=params, timeout=10)
        r.raise_for_status()
        resp = r.json()
        if resp.get("results"):
            return resp["results"][0]
    except Exception as e:
        logger.debug(f"페이지 조회 실패 [{title}]: {e}")
    return None


def update_page(page_id, title, body_html, parent=None):
    """기존 페이지 업데이트"""
    url = f"{NEW_BASE}/rest/api/content/{page_id}"

    # 페이지 정보 조회 (현재 버전 확인)
    r = new_session.get(url, params={"expand": "version"}, timeout=10)
    r.raise_for_status()
    resp = r.json()
    current_version = resp["version"]["number"]

    # 업데이트 데이터
    update_data = {
        "type": "page",
        "title": title,
        "space": {"key": NEW_SPACE},
        "body": {
            "storage": {
                "value": body_html,
                "representation": "storage",
            }
        },
        "version": {
            "number": current_version + 1
        }
    }
    if parent:
        update_data["ancestors"] = [{"id": parent}]

    r = with_retry(new_session.put, url, json=update_data)
    resp = r.json()
    if "id" not in resp:
        raise RuntimeError(f"페이지 업데이트 실패: {resp}")
    return resp["id"]


def create_page(title, body_html, parent=None):
    """페이지 생성 (중복 시 업데이트)"""
    # 먼저 같은 제목의 페이지가 있는지 확인
    existing = get_page_by_title(title)
    if existing:
        logger.debug(f"기존 페이지 발견 [{title}] (ID: {existing['id']}) → 업데이트")
        return update_page(existing["id"], title, body_html, parent)

    # 없으면 새로 생성
    url = f"{NEW_BASE}/rest/api/content"
    data = {
        "type": "page",
        "title": title,
        "space": {"key": NEW_SPACE},
        "body": {
            "storage": {
                "value": body_html,
                "representation": "storage",
            }
        },
    }
    if parent:
        data["ancestors"] = [{"id": parent}]

    r = with_retry(new_session.post, url, json=data)
    resp = r.json()
    if "id" not in resp:
        raise RuntimeError(f"페이지 생성 실패: {resp}")
    return resp["id"]


def upload_attachments(page_id, folder):
    att_path = os.path.join(folder, "attachments")
    if not os.path.exists(att_path):
        return
    for fname in os.listdir(att_path):
        file_path = os.path.join(att_path, fname)
        url = f"{NEW_BASE}/rest/api/content/{page_id}/child/attachment"
        try:
            with open(file_path, "rb") as f:
                with_retry(new_session.post, url, files={"file": (fname, f)},
                           headers={"X-Atlassian-Token": "no-check"})
            logger.debug(f"첨부파일 업로드: {fname}")
        except Exception as e:
            logger.error(f"첨부파일 업로드 실패 [{fname}]: {e}")

# ─── 전체 Import ──────────────────────────────────────────────────────────────
def import_all(inline_images=False, force_update=False):
    resume_state = load_resume_state()
    page_map = resume_state.get("page_map", {})

    pages_dir = os.path.join(EXPORT_DIR, "pages")
    folders = sorted(os.listdir(pages_dir))  # 번호 순서 정렬로 부모→자식 보장

    failed_uploads = []

    for folder_name in tqdm(folders, desc="Import", unit="page"):
        folder = os.path.join(pages_dir, folder_name)
        meta_path = os.path.join(folder, "meta.json")
        page_md_path = os.path.join(folder, "page.md")
        page_storage_path = os.path.join(folder, "page.storage.html")

        if not os.path.exists(meta_path):
            continue

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        old_id = meta["id"]

        # force_update=False일 때만 이미 업로드된 페이지 스킵
        if not force_update and old_id in resume_state.get("uploaded", []):
            logger.debug(f"이미 업로드됨 (skip): {meta['title']}")
            continue

        # --- 1) 먼저 placeholder로 페이지 생성(또는 기존 페이지 업데이트)하여 page_id 확보 ---
        parent_new_id = None
        html_body: str = ""  # 명시적 초기화 (할당 전 참조 방지)
        if meta.get("parent") and str(meta["parent"]) in page_map:
            parent_new_id = page_map[str(meta["parent"])]
        elif not meta.get("parent") and NEW_PARENT_PAGE_ID:
            parent_new_id = NEW_PARENT_PAGE_ID

        placeholder_html = "<p>Uploading attachments...</p>"

        try:
            # create_page는 동일 제목이 있으면 업데이트하므로 항상 안전하게 호출 가능
            new_id = create_page(meta["title"], placeholder_html, parent=parent_new_id)
        except Exception as e:
            logger.error(f"페이지 생성(placeholder) 실패 [{meta['title']}]: {e}")
            failed_uploads.append({"id": old_id, "title": meta["title"], "error": str(e)})
            continue

        # 페이지 ID 확보 후 매핑
        page_map[str(old_id)] = new_id
        resume_state["page_map"] = page_map
        save_resume_state(resume_state)

        # --- 2) 첨부파일 업로드 ---
        try:
            upload_attachments(new_id, folder)
        except Exception as e:
            logger.error(f"첨부파일 업로드 실패 [{meta['title']}]: {e}")
            # 계속 진행하여 본문 업데이트 시도

        # --- 3) 본문 준비: storage HTML 우선, 없으면 page.md -> html 변환 ---
        att_dir = os.path.join(folder, "attachments")

        if os.path.exists(page_storage_path):
            try:
                with open(page_storage_path, "r", encoding="utf-8") as f:
                    html_body = f.read()
                # 자동 전처리: Confluence 8.x -> 7.19 호환성 완화
                try:
                    html_body = sanitizer.remove_macro_attrs(html_body)
                    html_body = sanitizer.sanitize_code_macros(html_body)
                    # Gliffy → <ac:image 첨부> 또는 폴백 박스로 대체
                    html_body = sanitizer.sanitize_gliffy_macros(html_body, att_dir)
                except Exception as e:
                    logger.debug(f"sanitizer 적용 실패 [{meta['title']}]: {e}")
            except Exception as e:
                logger.warning(f"page.storage.html 읽기 실패 [{meta['title']}]: {e}")
                html_body = None
        else:
            html_body = None

        if not html_body:
            # 기존 마크다운 기반 경로
            if os.path.exists(page_md_path):
                md_text = open(page_md_path, "r", encoding="utf-8").read()
                if inline_images:
                    md_text = convert_images_to_inline(md_text, att_dir)
                try:
                    html_body = markdown_to_confluence_html(md_text)
                    try:
                        html_body = sanitizer.remove_macro_attrs(html_body)
                        html_body = sanitizer.sanitize_code_macros(html_body)
                        html_body = sanitizer.sanitize_gliffy_macros(html_body, att_dir)
                    except Exception as e:
                        logger.debug(f"sanitizer 적용 실패 (md) [{meta['title']}]: {e}")
                except Exception as e:
                    logger.warning(f"HTML 변환 실패 [{meta['title']}], 기본 처리로 진행: {e}")
                    html_body = html.escape(md_text, quote=False)
                    html_body = f"<p>{html_body}</p>"
            else:
                html_body = "<p></p>"

        # html_body가 None이면 빈 페이지로 안전하게 처리
        if not html_body:
            html_body = "<p></p>"

        # --- 4) data URI / 로컬 이미지 치환 ---
        html_body = convert_data_uri_imgs_to_acimage(html_body, att_dir)
        html_body = convert_local_imgs_to_acimage(html_body)

        # --- 5) 최종 본문으로 페이지 업데이트 ---
        try:
            update_page(new_id, meta["title"], html_body, parent=parent_new_id)

            if old_id not in resume_state.get("uploaded", []):
                resume_state.setdefault("uploaded", []).append(old_id)
            save_resume_state(resume_state)

            logger.debug(f"업로드 완료: {meta['title']} (new_id={new_id})")

        except Exception as e:
            logger.error(f"업로드 실패 [{meta['title']}]: {e}")
            failed_uploads.append({"id": old_id, "title": meta["title"], "error": str(e)})

    if failed_uploads:
        fail_path = os.path.join(EXPORT_DIR, "failed_uploads.json")
        with open(fail_path, "w", encoding="utf-8") as f:
            json.dump(failed_uploads, f, ensure_ascii=False, indent=2)
        logger.warning(f"실패한 업로드 {len(failed_uploads)}개 → {fail_path}")

    logger.info("Import 완료")

# ─── 전체 마이그레이션 ────────────────────────────────────────────────────────
def migrate(root_page_id=None, inline_images=False, force_update=False):
    login(old_session, OLD_BASE, OLD_USER, OLD_PASS)
    login(new_session, NEW_BASE, NEW_USER, NEW_PASS)
    export_all(root_page_id=root_page_id, inline_images=inline_images)
    import_all(inline_images=inline_images, force_update=force_update)

# ─── 인터랙티브 메뉴 ──────────────────────────────────────────────────────────
def ask(prompt, default=None):
    """사용자 입력을 받는 헬퍼. Ctrl+C 시 종료."""
    try:
        suffix = f" [{default}]" if default is not None and default != "" else ""
        val = input(f"{prompt}{suffix}: ").strip()
        # 입력이 없으면 기본값 반환 (None이면 None 반환)
        if not val:
            return default
        return val
    except (KeyboardInterrupt, EOFError):
        print("\n\n👋 종료합니다.")
        sys.exit(0)


def ask_yes_no(prompt, default=False):
    hint = "Y/n" if default else "y/N"
    val = ask(f"{prompt} ({hint})", default="y" if default else "n")
    return val.lower() in ("y", "yes")


def interactive_menu():
    """인자 없이 실행 시 표시되는 대화형 메뉴"""
    print()
    print("=" * 55)
    print("   Confluence Wiki Migration Tool")
    print("=" * 55)
    print()
    print("  1) export  — 기존 위키 → 로컬 파일")
    print("  2) import  — 로컬 파일 → 새 위키")
    print("  3) migrate — export + import 연속 실행")
    print()

    choice = ask("작업을 선택하세요 (1/2/3)", default="1")
    mode_map = {"1": "export", "2": "import", "3": "migrate",
                "export": "export", "import": "import", "migrate": "migrate"}
    mode = mode_map.get(choice)
    if not mode:
        print(f"❌ 잘못된 선택: {choice}")
        sys.exit(1)

    print(f"\n✅ 선택: {mode}")
    print()

    # ── 인증 정보 입력 ──────────────────────────────────────────────────────
    global OLD_USER, OLD_PASS, NEW_USER, NEW_PASS, SPACE, NEW_SPACE, NEW_PARENT_PAGE_ID, EXPORT_DIR, MAX_WORKERS

    if mode in ("export", "migrate"):
        print("─── 기존 위키 (export 대상) ───────────────────────────")
        env_user = os.getenv("O_USER", "")
        env_pass = os.getenv("O_PASS", "")

        if env_user and env_pass:
            print(f"  환경변수 O_USER / O_PASS 감지됨 → 자동 사용")
            OLD_USER = env_user
            OLD_PASS = env_pass
        else:
            OLD_USER = ask("  기존 위키 아이디", default=OLD_USER or "")
            OLD_PASS = getpass.getpass("  기존 위키 비밀번호: ") or OLD_PASS

    if mode in ("import", "migrate"):
        print("─── 새 위키 (import 대상) ─────────────────────────────")
        env_user = os.getenv("N_USER", "")
        env_pass = os.getenv("N_PASS", "")

        if env_user and env_pass:
            print(f"  환경변수 N_USER / N_PASS 감지됨 → 자동 사용")
            NEW_USER = env_user
            NEW_PASS = env_pass
        else:
            NEW_USER = ask("  새 위키 아이디", default=NEW_USER or "")
            NEW_PASS = getpass.getpass("  새 위키 비밀번호: ") or NEW_PASS

    # ── Space / 저장 경로 ───────────────────────────────────────────────────
    print()
    print("─── 기본 설정 ─────────────────────────────────────────")
    if mode in ("export", "migrate"):
        SPACE = ask("  기존 위키 Space Key", default=SPACE)
    if mode in ("import", "migrate"):
        NEW_SPACE = ask("  새 위키 Space Key", default=NEW_SPACE)
        parent_input = ask("  새 위키 부모 페이지 ID (없으면 Space 최상위)", default=NEW_PARENT_PAGE_ID or "")
        NEW_PARENT_PAGE_ID = parent_input if parent_input else None
    if mode in ("export", "migrate"):
        EXPORT_DIR = ask("  로컬 저장 경로", default=EXPORT_DIR)
    elif mode == "import":
        # import 모드에서도 EXPORT_DIR 확인 필요
        EXPORT_DIR = ask("  로컬 저장 경로", default=EXPORT_DIR)

    # ── 특정 페이지 ID (export/migrate 모드에서만) ────────────────────────
    page_id = None
    if mode in ("export", "migrate"):
        use_page = ask_yes_no("  특정 페이지와 하위 페이지만 가져오시겠어요?", default=False)
        if use_page:
            # page_id = ask("  페이지 ID 입력", default="")
            page_id = ask("  페이지 ID 입력", default="368351947")
            if not page_id:
                print("❌ 페이지 ID를 입력해야 합니다.")
                sys.exit(1)

    # ── inline 이미지 (export/migrate 모드에서만) ───────────────────────────
    inline_images = False
    if mode in ("export", "migrate"):
        inline_images = ask_yes_no("  이미지를 base64 inline으로 변환할까요?", default=False)

    # ── 병렬 스레드 수 (export/migrate 모드에서만) ─────────────────────────────
    if mode in ("export", "migrate"):
        workers_str = ask("  병렬 다운로드 스레드 수", default=str(MAX_WORKERS))
        try:
            MAX_WORKERS = int(workers_str)
        except ValueError:
            print("⚠️  숫자가 아니므로 기본값 8 사용")
            MAX_WORKERS = 8

    # ── 강제 업데이트 (import/migrate 모드에서만) ────────────────────────────
    force_update = False
    if mode in ("import", "migrate"):
        force_update = ask_yes_no("  이미 업로드된 페이지도 강제로 업데이트할까요?", default=False)

    # ── 최종 확인 ───────────────────────────────────────────────────────────
    print()
    print("─── 실행 요약 ─────────────────────────────────────────")
    print(f"  모드           : {mode}")
    if mode in ("export", "migrate"):
        print(f"  기존 Space Key : {SPACE}")
    if mode in ("import", "migrate"):
        print(f"  새 Space Key   : {NEW_SPACE}")
        print(f"  새 부모 페이지 : {NEW_PARENT_PAGE_ID if NEW_PARENT_PAGE_ID else '없음 (Space 최상위)'}")
        print(f"  강제 업데이트  : {'✅ 활성화' if force_update else '❌ 비활성화'}")
    print(f"  저장 경로      : {EXPORT_DIR}")
    if page_id:
        print(f"  페이지 ID      : {page_id} (하위 포함)")
    else:
        if mode in ("export", "migrate"):
            print(f"  페이지 범위    : 전체 Space")
    if mode in ("export", "migrate"):
        print(f"  inline 이미지  : {'✅ 사용' if inline_images else '❌ 미사용'}")
        print(f"  병렬 스레드    : {MAX_WORKERS}")
    print()

    confirm = ask_yes_no("위 설정으로 실행할까요?", default=True)
    if not confirm:
        print("취소되었습니다.")
        sys.exit(0)

    print()
    return mode, page_id, inline_images, force_update


# ─── CLI ─────────────────────────────────────────────────────────────────────
def main():
    print("main 함수 실행")
    # ── 인자가 없으면 인터랙티브 메뉴 실행 ─────────────────────────────────
    if len(sys.argv) == 1:
        mode, page_id, inline_images, force_update = interactive_menu()

        if mode == "export":
            login(old_session, OLD_BASE, OLD_USER, OLD_PASS)
            export_all(root_page_id=page_id, inline_images=inline_images)

        elif mode == "import":
            login(new_session, NEW_BASE, NEW_USER, NEW_PASS)
            import_all(inline_images=inline_images, force_update=force_update)

        elif mode == "migrate":
            migrate(root_page_id=page_id, inline_images=inline_images, force_update=force_update)

        return

    # ── 인자가 있으면 기존 CLI 방식 ────────────────────────────────────────
    parser = argparse.ArgumentParser(
        description="Confluence Wiki Migration Tool",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "mode",
        choices=["export", "import", "migrate"],
        help=(
            "export  : 기존 위키 → 로컬 파일\n"
            "import  : 로컬 파일 → 새 위키\n"
            "migrate : export + import 연속 실행"
        ),
    )
    parser.add_argument(
        "--page-id",
        metavar="PAGE_ID",
        default=None,
        help="이 ID의 페이지와 하위 페이지만 export (생략 시 전체 Space)",
    )
    parser.add_argument(
        "--inline-images",
        action="store_true",
        help="이미지를 base64 inline 데이터로 변환하여 저장/업로드",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="병렬 다운로드 스레드 수 (기본값: 8)",
    )
    parser.add_argument(
        "--force-update",
        action="store_true",
        help="이미 업로드된 페이지도 강제로 업데이트 (import/migrate 모드에서 사용)",
    )

    args = parser.parse_args()

    global MAX_WORKERS
    MAX_WORKERS = args.workers

    if args.mode == "export":
        login(old_session, OLD_BASE, OLD_USER, OLD_PASS)
        export_all(root_page_id=args.page_id, inline_images=args.inline_images)

    elif args.mode == "import":
        login(new_session, NEW_BASE, NEW_USER, NEW_PASS)
        import_all(inline_images=args.inline_images, force_update=args.force_update)

    elif args.mode == "migrate":
        migrate(root_page_id=args.page_id, inline_images=args.inline_images, force_update=args.force_update)


if __name__ == "__main__":
    main()