#!/usr/bin/env python3
"""
Safer regeneration of page.storage.converted.html
- Only replaces <ac:image> blocks that contain <ri:url ...> with <ri:attachment> **if** the target filename exists in attachments dir.
- Leaves all other content unchanged.
Usage:
  python3 scripts/regenerate_converted_safe.py [PAGES_DIR]
If no dir provided, defaults to wiki_down_upload_export/pages
"""
import sys
import os
from pathlib import Path
import re
import unicodedata

ROOT_DEFAULT = Path(__file__).resolve().parent.parent / 'wiki_down_upload_export' / 'pages'

IMG_BLOCK_RE = re.compile(r'<ac:image\b[^>]*>.*?<ri:url\s+ri:value="([^"]+)"\s*/?>.*?</ac:image>', re.DOTALL | re.IGNORECASE)
ALT_RE = re.compile(r'ac:alt="([^"]*)"', re.IGNORECASE)


def filename_from_url(url):
    from urllib.parse import urlparse, unquote
    parsed = urlparse(url.replace('&amp;', '&'))
    fname = os.path.basename(unquote(parsed.path))
    fname = fname.split('?')[0]
    return fname


def find_attachment_file(att_dir, fname):
    if not att_dir.exists() or not att_dir.is_dir():
        return None
    # build normalized maps
    files = [f for f in os.listdir(att_dir)]
    nmap = {unicodedata.normalize('NFC', f): f for f in files}
    nf = unicodedata.normalize('NFC', fname)
    if nf in nmap:
        return nmap[nf]
    # try case-insensitive
    lower_map = {unicodedata.normalize('NFC', f).lower(): f for f in files}
    key = nf.lower()
    return lower_map.get(key)


def process_file(folder: Path):
    in_path = folder / 'page.storage.html'
    out_path = folder / 'page.storage.converted.html'
    att_dir = folder / 'attachments'
    if not in_path.exists():
        return False, 'no input'
    text = in_path.read_text(encoding='utf-8')

    def repl(m):
        url = m.group(1)
        fname = filename_from_url(url)
        if not fname:
            return m.group(0)
        found = find_attachment_file(att_dir, fname)
        if not found:
            return m.group(0)
        # extract alt if any from the original block
        block = m.group(0)
        alt_m = ALT_RE.search(block)
        alt = alt_m.group(1) if alt_m else found
        # return a compact attachment block
        return f'<ac:image ac:alt="{alt}"><ri:attachment ri:filename="{found}" /></ac:image>'

    new_text = IMG_BLOCK_RE.sub(repl, text)
    out_path.write_text(new_text, encoding='utf-8')
    return True, 'ok'


def main(root_dir=None):
    root = Path(root_dir) if root_dir else ROOT_DEFAULT
    if not root.exists():
        print('ERROR: pages root not found:', root)
        return 2
    total = 0
    converted = 0
    skipped = 0
    failed = []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue
        total += 1
        ok, msg = process_file(folder)
        if ok:
            converted += 1
            print('OK:', folder.name)
        else:
            skipped += 1
            print('SKIP:', folder.name, msg)
    print('\nSummary: total', total, 'converted', converted, 'skipped', skipped, 'failed', len(failed))
    return 0

if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(main(arg))

