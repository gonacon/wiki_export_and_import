import re
import html
import os
import logging
import unicodedata
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

        def _find_matching_image(attachments_dir, display_name, macro_id):
            """
            디스플레이명이나 매크로ID와 일치하는 이미지 파일을 찾습니다.
            우선순위:
            1. displayName + 이미지 확장자 (정확 일치)
            2. displayName과 정확히 일치하는 이미지 파일
            3. macroId와 일치하는 이미지
            4. 부분 문자열 매칭
            """
            if not attachments_dir or not os.path.isdir(attachments_dir):
                return None
                
            files = os.listdir(attachments_dir)
            image_exts = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp'}
            
            # 이미지 파일만 필터링
            image_files = [fn for fn in files if any(fn.lower().endswith(ext) for ext in image_exts)]
            
            # 정규화된 파일명 매핑 (NFC 형식으로 정규화)
            # macOS 파일 시스템은 NFD 형식을 사용하므로, 비교를 위해 NFC로 정규화
            normalized_map = {}
            for fn in image_files:
                fn_nfc = unicodedata.normalize('NFC', fn)
                fn_nfc_lower = fn_nfc.lower()
                normalized_map[fn_nfc_lower] = fn
            
            # 검색 문자열 정규화 함수
            def normalize_for_search(s):
                return unicodedata.normalize('NFC', s).lower()
            
            # 1. displayName + 이미지 확장자로 일치 (우선순위 높음)
            if display_name:
                display_normalized = normalize_for_search(display_name)
                for ext in image_exts:
                    key = display_normalized + ext
                    if key in normalized_map:
                        return normalized_map[key]
            
            # 2. displayName이 정확히 일치하는 이미지 파일
            if display_name:
                display_normalized = normalize_for_search(display_name)
                if display_normalized in normalized_map:
                    return normalized_map[display_normalized]
            
            # 3. macroId와 일치
            if macro_id:
                macro_normalized = normalize_for_search(macro_id)
                if macro_normalized in normalized_map:
                    return normalized_map[macro_normalized]
            
            # 4. displayName을 포함하는 파일 찾기 (부분 매칭)
            if display_name:
                display_normalized = normalize_for_search(display_name)
                for fn in image_files:
                    fn_normalized = normalize_for_search(fn)
                    if display_normalized in fn_normalized:
                        return fn
            
            # 5. macroId를 포함하는 파일 찾기
            if macro_id:
                macro_normalized = normalize_for_search(macro_id)
                for fn in image_files:
                    fn_normalized = normalize_for_search(fn)
                    if macro_normalized in fn_normalized:
                        return fn
            
            return None

        def _repl(m):
            params = _extract(m.group(0))
            display = (params.get('displayName') or params.get('name') or params.get('macroId') or 'Gliffy diagram')
            mid = params.get('macroId', '')
            
            # displayName 우선, 없으면 name
            display_name = params.get('displayName') or params.get('name') or ''

            if attachments_dir and os.path.isdir(attachments_dir):
                matched_file = _find_matching_image(attachments_dir, display_name, mid)
                
                if matched_file:
                    logger.info(f"Gliffy 매크로 → 이미지 변환: {display} → {matched_file}")
                    return f'<ac:image><ri:attachment ri:filename="{html.escape(matched_file)}" /></ac:image>'

            logger.warning(f"Gliffy 매크로 변환 실패 (첨부파일 없음): {display}")
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
