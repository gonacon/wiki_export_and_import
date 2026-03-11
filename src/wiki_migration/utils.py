import os
import re
import base64
import html
import markdown2
import logging
from markdownify import markdownify as md_convert
from urllib.parse import urlparse, unquote

logger = logging.getLogger("wiki_migrate")

def safe_folder_name(title):
    return re.sub(r'[<>:\"/\\|?*]', '_', title)


def fix_image_links_html(html_text, attachments_dir):
    pattern = re.compile(r'<ac:image[^>]*>.*?<ri:attachment\s+ri:filename="([^"]+)"[^/]*/?>.*?</ac:image>', re.DOTALL | re.IGNORECASE)
    def repl(m):
        fname = m.group(1)
        return f'<img src="./attachments/{fname}" alt="{fname}" />'
    text = pattern.sub(repl, html_text)
    text = re.sub(r'<img[^>]+src=["\']https?://[^"\']*/([^/"\']+\.(?:png|jpg|jpeg|gif|svg|webp|bmp))["\']',
                  lambda m: f'<img src="./attachments/{m.group(1)}"', text, flags=re.IGNORECASE)
    return text


def convert_images_to_inline(markdown_text, attachments_dir):
    def replacer(m):
        alt = m.group(1)
        fname = m.group(2)
        fpath = os.path.join(attachments_dir, fname)
        if not os.path.exists(fpath):
            return m.group(0)
        ext = fname.rsplit('.', 1)[-1].lower()
        mime_map = {
            'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
            'gif': 'image/gif', 'svg': 'image/svg+xml', 'webp': 'image/webp',
            'bmp': 'image/bmp',
        }
        mime = mime_map.get(ext, 'application/octet-stream')
        with open(fpath, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode('utf-8')
        return f'![{alt}](data:{mime};base64,{b64})'

    pattern = re.compile(r'!\[([^]]*)][(]\.\/attachments\/([^)]+)[)]')
    return pattern.sub(replacer, markdown_text)


def markdown_to_confluence_html(markdown_text):
    html_text = markdown2.markdown(markdown_text, extras=['tables', 'fenced-code-blocks'])
    html_text = html.escape(html_text, quote=True)
    html_text = html_text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#x27;", "'")
    return html_text


def html_to_markdown(html_text):
    return md_convert(html_text, heading_style='ATX')


def convert_local_imgs_to_acimage(html_text):
    """로컬/상대 이미지 참조를 Confluence storage attachment 매크로로 변환."""
    def to_acimage(filename):
        safe_name = html.escape(filename, quote=True)
        return f'<ac:image><ri:attachment ri:filename="{safe_name}" /></ac:image>'

    md_pattern = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')

    def md_repl(m):
        src = m.group(1).strip()
        if src.startswith('data:') or re.match(r'^(https?:)?//', src, flags=re.IGNORECASE):
            return m.group(0)
        fname = os.path.basename(unquote(src.split('?', 1)[0]))
        if not fname:
            return m.group(0)
        return to_acimage(fname)

    converted = md_pattern.sub(md_repl, html_text)

    img_pattern = re.compile(r'<img\b[^>]*\bsrc=("|\')(.*?)\1[^>]*>', re.IGNORECASE)

    def img_repl(m):
        src = m.group(2).strip()
        if src.startswith('data:') or re.match(r'^(https?:)?//', src, flags=re.IGNORECASE):
            return m.group(0)
        fname = os.path.basename(unquote(src.split('?', 1)[0]))
        if not fname:
            return m.group(0)
        return to_acimage(fname)

    return img_pattern.sub(img_repl, converted)


def convert_data_uri_imgs_to_acimage(html_text, attachments_dir):
    def to_acimage(filename):
        safe_name = html.escape(filename, quote=True)
        return f'<ac:image><ri:attachment ri:filename="{safe_name}" /></ac:image>'

    img_tag_pattern = re.compile(r'<img\b[^>]*>', re.IGNORECASE)

    def extract_attr(tag, attr):
        pattern = r'\b' + re.escape(attr) + r"\s*=\s*(['\"])(.*?)\1"
        m = re.search(pattern, tag, flags=re.IGNORECASE)
        return m.group(2).strip() if m else ''

    def repl(m):
        tag = m.group(0)
        src = extract_attr(tag, 'src')
        if not src.startswith('data:image/'):
            return tag
        alt = extract_attr(tag, 'alt')
        title = extract_attr(tag, 'title')
        filename = (alt or title).strip()
        if not filename:
            return tag
        filename = os.path.basename(filename)
        fpath = os.path.join(attachments_dir, filename)
        if not os.path.exists(fpath):
            return tag
        return to_acimage(filename)

    return img_tag_pattern.sub(repl, html_text)

def extract_filename_from_url(url):
    """URL에서 파일명 추출 (URL 디코딩 포함)"""
    parsed = urlparse(url)
    path = parsed.path

    # URL 디코딩
    decoded_path = unquote(path)

    # 파일명 추출
    filename = os.path.basename(decoded_path)

    # 쿼리 파라미터 제거
    filename = filename.split('?')[0]

    return filename


def download_url_image(url, save_dir, session, filename=None):
    """
    URL 이미지를 다운로드하여 저장

    Args:
        url: 이미지 URL
        save_dir: 저장 디렉토리
        session: requests.Session 객체
        filename: 저장할 파일명 (None이면 URL에서 추출)

    Returns:
        저장된 파일명 또는 None (실패 시)
    """
    try:
        if not filename:
            filename = extract_filename_from_url(url)

        # 파일명 안전하게 처리
        filename = safe_folder_name(filename)

        if not filename:
            logger.warning(f"파일명 추출 실패: {url}")
            return None

        save_path = os.path.join(save_dir, filename)

        # 이미 다운로드된 경우 skip
        if os.path.exists(save_path):
            logger.debug(f"이미지 이미 존재 (skip): {filename}")
            return filename

        # 다운로드
        resp = session.get(url, timeout=30)
        resp.raise_for_status()

        # 저장
        with open(save_path, 'wb') as f:
            f.write(resp.content)

        logger.debug(f"URL 이미지 다운로드 완료: {filename}")
        return filename

    except Exception as e:
        logger.error(f"URL 이미지 다운로드 실패 [{url}]: {e}")
        return None


def fix_url_images_in_html(html_text, attachments_dir, session):
    """
    HTML에서 <ri:url> 이미지를 찾아서 다운로드하고 로컬 참조로 변경

    Args:
        html_text: 원본 HTML
        attachments_dir: 첨부파일 저장 디렉토리
        session: requests.Session (다운로드용)

    Returns:
        변경된 HTML
    """
    import re

    # <ri:url ri:value="..."/> 패턴 찾기
    url_pattern = re.compile(
        r'<ri:url\s+ri:value="([^"]+)"\s*/?>',
        re.IGNORECASE
    )

    # <ac:image>...</ac:image> 블록 전체 찾기
    image_block_pattern = re.compile(
        r'<ac:image[^>]*>.*?<ri:url\s+ri:value="([^"]+)"\s*/?>.*?</ac:image>',
        re.DOTALL | re.IGNORECASE
    )

    downloaded_files = {}  # URL -> filename 매핑

    def download_and_convert(match):
        """이미지 블록을 변환"""
        full_block = match.group(0)
        url = match.group(1)

        # URL 디코딩 (HTML 엔티티)
        url = url.replace('&amp;', '&')

        # 이미 다운로드한 경우
        if url in downloaded_files:
            filename = downloaded_files[url]
        else:
            # 다운로드
            filename = download_url_image(url, attachments_dir, session)
            if filename:
                downloaded_files[url] = filename
            else:
                # 다운로드 실패 시 원본 유지
                return full_block

        # <ri:url>을 <ri:attachment>로 변경
        # ac:alt 속성 추출
        alt_match = re.search(r'ac:alt="([^"]*)"', full_block)
        alt_text = alt_match.group(1) if alt_match else filename

        # 새로운 이미지 블록 생성
        new_block = f'<ac:image ac:alt="{alt_text}"><ri:attachment ri:filename="{filename}" /></ac:image>'

        logger.info(f"URL 이미지 변환: {url} → {filename}")
        return new_block

    # 변환 실행
    converted_html = image_block_pattern.sub(download_and_convert, html_text)

    if downloaded_files:
        logger.info(f"총 {len(downloaded_files)}개 URL 이미지 다운로드 완료")

    return converted_html
