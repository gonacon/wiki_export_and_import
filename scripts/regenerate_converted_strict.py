#!/usr/bin/env python3
"""
Strict/safe regeneration: replace <ac:image> blocks that contain <ri:url .../>
with <ac:image><ri:attachment ri:filename="..."/></ac:image> only when the corresponding
attachment filename exists in the page's attachments directory.
This keeps all other content intact (no macro removal).

Usage:
  python3 scripts/regenerate_converted_strict.py [PAGE_FOLDER]
If PAGE_FOLDER omitted, runs for all folders under wiki_down_upload_export/pages
"""
import sys
from pathlib import Path
import re
import os
import unicodedata
from urllib.parse import urlparse, unquote
import html

ROOT = Path(__file__).resolve().parent.parent / 'wiki_down_upload_export' / 'pages'
# 패턴 변경: ac:image 블록 전체가 아닌 내부의 ri:url 태그만 찾아 교체하도록 한다.
IMAGE_BLOCK_RE = re.compile(r'(<ac:image\b[^>]*>)(.*?)(</ac:image>)', re.DOTALL | re.IGNORECASE)
RI_URL_RE = re.compile(r'<ri:url\s+ri:value="([^"]+)"\s*/?>', re.IGNORECASE)
ALT_RE = re.compile(r'ac:alt="([^"]*)"', re.IGNORECASE)


def filename_from_url(url: str) -> str:
    parsed = urlparse(url.replace('&amp;', '&'))
    path = unquote(parsed.path)
    fname = os.path.basename(path)
    if not fname:
        return ''
    return fname.split('?')[0]


def find_attachment(att_dir: Path, fname: str):
    if not att_dir.exists() or not att_dir.is_dir():
        return None
    files = [f for f in os.listdir(att_dir) if os.path.isfile(att_dir / f)]
    # Normalize to NFC for macOS compatibility
    nmap = {unicodedata.normalize('NFC', f): f for f in files}
    nf = unicodedata.normalize('NFC', fname)
    if nf in nmap:
        return nmap[nf]
    # try case-insensitive
    lower_map = {unicodedata.normalize('NFC', f).lower(): f for f in files}
    return lower_map.get(nf.lower())


def extract_alt_from(text: str) -> str:
    m = ALT_RE.search(text)
    return m.group(1) if m else ''


def process_folder(folder: Path):
    in_path = folder / 'page.storage.html'
    out_path = folder / 'page.storage.converted.html'
    att_dir = folder / 'attachments'
    if not in_path.exists():
        return False, 'no input'
    text = in_path.read_text(encoding='utf-8')

    replacements = 0

    def image_block_repl(m):
        nonlocal replacements
        open_tag = m.group(1) or ''
        inner = m.group(2) or ''
        close_tag = m.group(3) or ''

        # inner에서 ri:url 찾기
        url_m = RI_URL_RE.search(inner)
        if not url_m:
            return m.group(0)  # 변경 없음
        url = url_m.group(1)
        fname = filename_from_url(url)
        if not fname:
            return m.group(0)
        found = find_attachment(att_dir, fname)
        if not found:
            return m.group(0)

        # 파일이 존재하면 ri:url 태그만 <ri:attachment .../>로 교체
        # 기존 inner의 다른 내용과 스타일은 그대로 유지
        # alt 추출(있으면 유지, 없으면 filename 사용)
        alt = extract_alt_from(open_tag) or extract_alt_from(inner) or found

        # 안전하게 ri:attachment 단일 태그로 교체
        new_inner = RI_URL_RE.sub(f'<ri:attachment ri:filename="{html.escape(found)}" />', inner)
        replacements += 1
        return open_tag + new_inner + close_tag

    new_text = IMAGE_BLOCK_RE.sub(image_block_repl, text)
    out_path.write_text(new_text, encoding='utf-8')
    return True, f'ok ({replacements} replacements)'


def main(arg=None):
    if arg:
        path = Path(arg)
        if not path.exists():
            print('ERROR: path not found:', path)
            return 2
        folders = [path] if path.is_dir() else [path.parent]
    else:
        folders = sorted([p for p in ROOT.iterdir() if p.is_dir()])

    total = 0
    conv = 0
    skipped = 0
    failed = []

    for folder in folders:
        total += 1
        ok, msg = process_folder(folder)
        if ok:
            conv += 1
            print('OK:', folder.name, msg)
        else:
            skipped += 1
            print('SKIP:', folder.name, msg)

    print('\nSummary: total', total, 'converted', conv, 'skipped', skipped, 'failed', len(failed))
    return 0

if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(main(arg))
