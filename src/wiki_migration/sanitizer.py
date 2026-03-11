import re
import html
import os
import logging
from urllib.parse import unquote, urlparse

logger = logging.getLogger("wiki_migrate")

class Sanitizer:
    """페이지 storage HTML을 타깃 Confluence(예: 7.19)에 맞게 전처리합니다."""

    @staticmethod
    def remove_macro_attrs(html_text):
        out = re.sub(r'\s+ac:schema-version="[^"]+"', "", html_text, flags=re.IGNORECASE)
        out = re.sub(r'\s+ac:macro-id="[^"]+"', "", out, flags=re.IGNORECASE)
        return out

    @staticmethod
    def sanitize_code_macros(html_text):
        CODE_FULL_RE = re.compile(
            r'<ac:structured-macro\b[^>]*ac:name="code"[^>]*>'
            r'.*?'
            r'<ac:plain-text-body>\s*<!\[CDATA\[(.*?)\]\]>\s*</ac:plain-text-body>'
            r'.*?</ac:structured-macro>',
            re.DOTALL | re.IGNORECASE,
            )
        LANG_RE = re.compile(r'<ac:parameter\s+ac:name="language"\s*>(.*?)</ac:parameter>', re.DOTALL | re.IGNORECASE)

        def _repl_full(m):
            code_text = m.group(1)
            lang_m = LANG_RE.search(m.group(0))
            lang = (lang_m.group(1).strip().lower() if lang_m else "") or "text"
            return f'<pre style="background-color:#0a2b1d; color: #f8f8f8; padding: 15px;"><code class="language-{lang}">{html.escape(code_text)}</code></pre>'

        result, n = CODE_FULL_RE.subn(_repl_full, html_text)
        if n:
            return result

        CODE_ANY_RE = re.compile(r'<ac:structured-macro\b[^>]*ac:name="code"[^>]*>(.*?)</ac:structured-macro>', re.DOTALL | re.IGNORECASE)

        def _repl_any(m):
            body = m.group(1)
            cdata = re.search(r'<!\[CDATA\[(.*?)\]\]>', body, re.DOTALL)
            code_text = cdata.group(1) if cdata else re.sub(r'<[^>]+>', '', body).strip()
            lang_m = LANG_RE.search(m.group(0))
            lang = (lang_m.group(1).strip().lower() if lang_m else "") or "text"
            return f'<pre style="background-color:#0a2b1d; color: #f8f8f8; padding: 15px;"><code class="language-{lang}">{html.escape(code_text)}</code></pre>'

        return CODE_ANY_RE.sub(_repl_any, html_text)

    @staticmethod
    def sanitize_gliffy_macros(html_text, attachments_dir=None):
        GLIFFY_RE = re.compile(r'<ac:structured-macro\b[^>]*ac:name="gliffy"[^>]*>.*?</ac:structured-macro>', re.DOTALL | re.IGNORECASE)
        PARAM_RE = re.compile(r'<ac:parameter\s+ac:name="([^"]+)"\s*>(.*?)</ac:parameter>', re.DOTALL | re.IGNORECASE)

        def _extract(macro_html):
            return {m.group(1).strip(): m.group(2).strip() for m in PARAM_RE.finditer(macro_html)}

        def _safe(s, maxlen=80):
            return re.sub(r'[^\w\-.]', '_', s)[:maxlen]

        def _repl(m):
            params = _extract(m.group(0))
            display = (params.get('displayName') or params.get('name') or params.get('macroId') or 'Gliffy diagram')
            mid = params.get('macroId', '')

            candidates = []
            if attachments_dir and os.path.isdir(attachments_dir):
                files = os.listdir(attachments_dir)
                lower_map = {fn.lower(): fn for fn in files}

                for key in [f"gliffy_{_safe(display)}.png", f"gliffy_{_safe(mid)}.png" if mid else None]:
                    if key and key.lower() in lower_map:
                        candidates.append(lower_map[key.lower()])

                if mid and mid.lower() in lower_map:
                    candidates.append(lower_map[mid.lower()])

                dn = params.get('displayName', '')
                for variant in [dn, dn + '.png', dn + '.svg', dn + '.gliffy']:
                    if variant and variant.lower() in lower_map:
                        candidates.append(lower_map[variant.lower()])

                for fn in files:
                    if 'gliffy' in fn.lower() or (mid and mid.lower() in fn.lower()):
                        candidates.append(fn)

                for ext in ('.png', '.svg', '.jpg', '.jpeg'):
                    for c in candidates:
                        if c.lower().endswith(ext):
                            return f'<ac:image><ri:attachment ri:filename="{html.escape(c)}" /></ac:image>'

                if candidates:
                    return f'<a href="./attachments/{html.escape(candidates[0])}">{html.escape(display)} (diagram)</a>'

            return (
                f'<div class="gliffy-macro-fallback" '
                f'style="border:1px dashed #f0a;padding:8px;background:#fff7e6;'
                f'color:#555;font-size:0.9em;">'
                f'⚠️ Gliffy 다이어그램: <strong>{html.escape(display)}</strong>'
                f'<br/><small>(첨부파일 없음 — 원본 위키에서 이미지로 저장 후 재-export 권장)</small>'
                f'</div>'
            )

        return GLIFFY_RE.sub(_repl, html_text)

    @staticmethod
    def convert_remaining_url_images(html_text, attachments_dir=None):
        """
        Import 시점에 남아있는 <ri:url> 이미지를 <ri:attachment>로 변환
        (Export에서 처리 못한 경우를 위한 보험)

        Args:
            html_text: HTML 내용
            attachments_dir: 첨부파일 디렉토리 (파일 존재 여부 확인용)

        Returns:
            변환된 HTML
        """
        # <ri:url> 패턴
        url_pattern = re.compile(
            r'<ac:image[^>]*>.*?<ri:url\s+ri:value="([^"]+)"\s*/?>.*?</ac:image>',
            re.DOTALL | re.IGNORECASE
        )

        def replace_with_attachment(match):
            full_block = match.group(0)
            url = match.group(1).replace('&amp;', '&')

            # URL에서 파일명 추출
            try:
                parsed = urlparse(url)
                filename = os.path.basename(unquote(parsed.path))
                filename = filename.split('?')[0]

                if not filename:
                    logger.warning(f"파일명 추출 실패, 원본 유지: {url}")
                    return full_block

                # 첨부파일 존재 여부 확인
                if attachments_dir and os.path.isdir(attachments_dir):
                    file_path = os.path.join(attachments_dir, filename)
                    if not os.path.exists(file_path):
                        logger.warning(f"첨부파일 없음, 원본 유지: {filename}")
                        return full_block

                # ac:alt 추출
                alt_match = re.search(r'ac:alt="([^"]*)"', full_block)
                alt_text = alt_match.group(1) if alt_match else filename

                # 변환
                new_block = f'<ac:image ac:alt="{alt_text}"><ri:attachment ri:filename="{filename}" /></ac:image>'
                logger.info(f"URL 이미지를 attachment로 변환: {filename}")
                return new_block

            except Exception as e:
                logger.warning(f"URL 이미지 변환 실패: {url}, {e}")
                return full_block

        return url_pattern.sub(replace_with_attachment, html_text)
