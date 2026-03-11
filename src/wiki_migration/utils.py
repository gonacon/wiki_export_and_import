import os
import re
import base64
import html
import markdown2
from markdownify import markdownify as md_convert
from urllib.parse import unquote


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

