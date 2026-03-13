import os
import re
import base64
import html
import markdown2
import logging
from markdownify import markdownify as md_convert
from urllib.parse import urlparse, unquote
import traceback

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

    pattern = re.compile(r'!\[([^]]*)\]\(\./attachments/([^)]+)\)')
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

    md_pattern = re.compile(r'!\[([^]]*)\]\(([^)]+)\)')

    def md_repl(m):
        src = m.group(1).strip()
        if src.startswith('data:') or re.match(r'^(https?:)?//', src, flags=re.IGNORECASE):
            return m.group(0)
        fname = os.path.basename(unquote(src.split('?', 1)[0]))
        if not fname:
            return m.group(0)
        return to_acimage(fname)

    converted = md_pattern.sub(md_repl, html_text)

    img_pattern = re.compile(r"<img\b[^>]*\bsrc=(['\"])(.*?)\1[^>]*>", re.IGNORECASE)

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

    # wrapper-aware pattern: ac:link > ri:page ... > ac:link-body > ac:image(...ri:url...) </ac:link-body></ac:link>
    wrapper_pattern = re.compile(
        r'(<ac:link\b[^>]*>\s*<ri:page[^>]*>\s*<ac:link-body[^>]*>)(<ac:image[^>]*>.*?<ri:url\s+ri:value="([^"]+)"\s*/?>.*?</ac:image>)(\s*</ac:link-body>\s*</ac:link>)',
        re.DOTALL | re.IGNORECASE
    )

    downloaded_files = {}  # URL -> filename 매핑

    def download_and_convert_block(url, full_block):
        url_clean = url.replace('&amp;', '&')
        if url_clean in downloaded_files:
            filename = downloaded_files[url_clean]
        else:
            filename = download_url_image(url_clean, attachments_dir, session)
            if filename:
                downloaded_files[url_clean] = filename
            else:
                return None
        alt_match = re.search(r'ac:alt="([^"]*)"', full_block)
        alt_text = alt_match.group(1) if alt_match else filename
        new_block = f'<ac:image ac:alt="{alt_text}"><ri:attachment ri:filename="{filename}" /></ac:image>'
        logger.info(f"URL 이미지 변환: {url_clean} → {filename}")
        return new_block

    # 1) 먼저 ac:link > ac:link-body 래퍼 안의 이미지를 처리하여 래퍼를 보존
    def wrapper_repl(m):
        open_wrapper = m.group(1)
        image_block = m.group(2)
        url = m.group(3)
        close_wrapper = m.group(4)
        replaced = download_and_convert_block(url, image_block)
        if replaced:
            return open_wrapper + replaced + close_wrapper
        # 실패하면 원본 유지
        return m.group(0)

    html_text = wrapper_pattern.sub(wrapper_repl, html_text)

    # 2) 그 외의 standalone <ac:image> 블록 처리
    def download_and_convert(match):
        full_block = match.group(0)
        url = match.group(1)
        replaced = download_and_convert_block(url, full_block)
        return replaced or full_block

    converted_html = image_block_pattern.sub(download_and_convert, html_text)

    if downloaded_files:
        logger.info(f"총 {len(downloaded_files)}개 URL 이미지 다운로드 완료")

    return converted_html

# utils.py - 맨 끝에 추가

def convert_internal_links_with_pageid(html_text, old_base, new_base, page_map, pages_info=None, current_page_old_id=None):
    """
    내부 링크를 새 wiki의 pageId로 변환

    Args:
        html_text: HTML 내용
        old_base: 기존 wiki URL (예: https://wiki.11stcorp.com)
        new_base: 새 wiki URL (예: https://wiki.skplanet.com)
        page_map: old_id → new_id 매핑 dict
        pages_info: 페이지 정보 dict (optional, 첨부파일 소유 페이지 확인용)
        current_page_old_id: 현재 페이지의 old ID (optional)

    Returns:
        변환된 HTML
    """
    import re
    from urllib.parse import urlparse, parse_qs

    link_pattern = re.compile(
        r'<a\s+([^>]*\s+)?href=(["\'])(' + re.escape(old_base) + r'/[^"\']*)\2([^>]*)>(.*?)</a>',
        re.IGNORECASE | re.DOTALL
    )

    converted_count = {'page': 0, 'attachment': 0, 'attachment_cross': 0, 'display': 0}
    failed_links = []

    def replace_link(match):
        pre_attrs = match.group(1) or ''
        quote = match.group(2)
        url = match.group(3)
        post_attrs = match.group(4) or ''
        link_text = match.group(5)

        try:
            parsed = urlparse(url)

            # ========================================
            # 1. 페이지 링크: viewpage.action?pageId=123
            # ========================================
            if 'viewpage.action' in parsed.path:
                query_params = parse_qs(parsed.query)
                old_page_id = query_params.get('pageId', [None])[0]

                if old_page_id:
                    new_page_id = page_map.get(str(old_page_id))

                    if new_page_id:
                        new_url = f"{new_base}/pages/viewpage.action?pageId={new_page_id}"
                        new_link = f'<a {pre_attrs}href={quote}{new_url}{quote}{post_attrs}>{link_text}</a>'
                        converted_count['page'] += 1
                        logger.debug(f"페이지 링크 변환: {old_page_id} → {new_page_id}")
                        return new_link
                    else:
                        logger.warning(f"링크 대상 미import: pageId={old_page_id}")
                        failed_links.append(('page', old_page_id))
                        return f'<span style="background-color: #fff3cd; padding: 2px 4px;" title="원본 페이지 ID: {old_page_id}">{link_text}</span>'

            # ========================================
            # 2. 첨부파일 링크: /download/attachments/123/file.jpg
            # ========================================
            elif '/download/attachments/' in parsed.path:
                path_parts = parsed.path.split('/')
                if len(path_parts) >= 4:
                    attachment_owner_page_id = path_parts[3]  # 첨부파일이 있는 페이지 ID
                    filename_encoded = path_parts[4] if len(path_parts) > 4 else None

                    if filename_encoded:
                        filename = unquote(filename_encoded).split('?')[0]

                        # 현재 페이지의 첨부파일인지 확인
                        is_same_page = (str(current_page_old_id) == str(attachment_owner_page_id))

                        if is_same_page:
                            # Case 1: 같은 페이지의 첨부파일
                            new_link = (
                                f'<ac:link>'
                                f'<ri:attachment ri:filename="{html.escape(filename)}" />'
                                f'<ac:link-body>{link_text}</ac:link-body>'
                                f'</ac:link>'
                            )
                            converted_count['attachment'] += 1
                            logger.debug(f"첨부파일 링크 변환 (같은 페이지): {filename}")
                        else:
                            # Case 2: 다른 페이지의 첨부파일
                            if pages_info and attachment_owner_page_id in pages_info:
                                owner_page_title = pages_info[attachment_owner_page_id]['meta']['title']

                                new_link = (
                                    f'<ac:link>'
                                    f'<ri:attachment ri:filename="{html.escape(filename)}">'
                                    f'<ri:page ri:content-title="{html.escape(owner_page_title)}" />'
                                    f'</ri:attachment>'
                                    f'<ac:link-body>{link_text}</ac:link-body>'
                                    f'</ac:link>'
                                )
                                converted_count['attachment_cross'] += 1
                                logger.debug(f"첨부파일 링크 변환 (다른 페이지): {filename} from {owner_page_title}")
                            else:
                                # 페이지 정보 없으면 현재 페이지로 가정 (fallback)
                                logger.warning(f"첨부파일 소유 페이지 정보 없음: {attachment_owner_page_id}, 현재 페이지로 가정")
                                new_link = (
                                    f'<ac:link>'
                                    f'<ri:attachment ri:filename="{html.escape(filename)}" />'
                                    f'<ac:link-body>{link_text}</ac:link-body>'
                                    f'</ac:link>'
                                )
                                converted_count['attachment'] += 1

                        return new_link

                logger.warning(f"첨부파일 링크 파싱 실패: {url}")
                return match.group(0)

            # ========================================
            # 3. Display 링크: /display/SPACE/PageTitle
            # ========================================
            elif '/display/' in parsed.path:
                new_url = url.replace(old_base, new_base)
                new_link = f'<a {pre_attrs}href={quote}{new_url}{quote}{post_attrs}>{link_text}</a>'
                converted_count['display'] += 1
                logger.debug(f"display 링크 도메인 변경")
                return new_link

            # ========================================
            # 4. 기타 내부 링크
            # ========================================
            else:
                logger.debug(f"기타 내부 링크 유지: {parsed.path}")
                return match.group(0)

        except Exception as e:
            logger.warning(f"링크 변환 중 오류: {url}, {e}")
            logger.debug(traceback.format_exc())
            return match.group(0)

    # 변환 실행
    converted_html = link_pattern.sub(replace_link, html_text)

    # 결과 로그
    total = sum(converted_count.values())
    if total > 0:
        logger.info(
            f"내부 링크 변환: "
            f"페이지={converted_count['page']}, "
            f"첨부파일(같은페이지)={converted_count['attachment']}, "
            f"첨부파일(다른페이지)={converted_count['attachment_cross']}, "
            f"display={converted_count['display']}"
        )
    if failed_links:
        logger.warning(f"변환 실패: {failed_links[:10]}")

    return converted_html


def convert_ri_url_to_attachment_if_exists(html_text, attachments_dir):
    """
    안전 변환: <ac:image> 내부의 <ri:url ri:value="..."/> 를 attachments 디렉토리에서
    실제 파일명이 존재하면 <ri:attachment ri:filename="..."/> 로 교체합니다.
    다른 본문/매크로는 건드리지 않습니다.

    Args:
        html_text: 원본 HTML
        attachments_dir: 첨부파일 폴더 경로(문자열)

    Returns:
        변환된 HTML (원본을 변경하지 않음)
    """
    import re
    import os
    import unicodedata
    from urllib.parse import urlparse, unquote

    IMAGE_BLOCK_RE = re.compile(r'(<ac:image\b[^>]*>)(.*?)(</ac:image>)', re.DOTALL | re.IGNORECASE)
    RI_URL_RE = re.compile(r'<ri:url\s+ri:value="([^"]+)"\s*/?>', re.IGNORECASE)
    ALT_RE = re.compile(r'ac:alt="([^"]*)"', re.IGNORECASE)

    def filename_from_url(url):
        parsed = urlparse(url.replace('&amp;', '&'))
        path = unquote(parsed.path)
        fname = os.path.basename(path)
        if not fname:
            return ''
        return fname.split('?')[0]

    def find_attachment_file(dirpath, fname):
        try:
            if not dirpath or not os.path.isdir(dirpath):
                return None
            files = [f for f in os.listdir(dirpath) if os.path.isfile(os.path.join(dirpath, f))]
            nmap = {unicodedata.normalize('NFC', f): f for f in files}
            nf = unicodedata.normalize('NFC', fname)
            if nf in nmap:
                return nmap[nf]
            lower_map = {unicodedata.normalize('NFC', f).lower(): f for f in files}
            return lower_map.get(nf.lower())
        except Exception:
            return None

    def extract_alt(text):
        m = ALT_RE.search(text)
        return m.group(1) if m else ''

    def repl(m):
        open_tag = m.group(1) or ''
        inner = m.group(2) or ''
        close_tag = m.group(3) or ''
        url_m = RI_URL_RE.search(inner)
        if not url_m:
            return m.group(0)
        url = url_m.group(1)
        fname = filename_from_url(url)
        if not fname:
            return m.group(0)
        found = find_attachment_file(attachments_dir, fname)
        if not found:
            return m.group(0)
        # replace only the ri:url tag with ri:attachment, keep other inner content
        new_inner = RI_URL_RE.sub(f'<ri:attachment ri:filename="{html.escape(found)}" />', inner)
        return open_tag + new_inner + close_tag

    return IMAGE_BLOCK_RE.sub(repl, html_text)
