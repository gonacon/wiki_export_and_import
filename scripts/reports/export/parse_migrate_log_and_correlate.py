#!/usr/bin/env python3
"""
parse_migrate_log_and_correlate.py (export)

Parse migrate.log for ERROR/WARNING entries and correlate to page folders.
Moved into scripts/reports/export and uses scripts._common.utils.
"""
import os
import sys
import re
import json
from pathlib import Path

# ensure repo root on path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._common import utils

export_dir = utils.detect_export_dir()
MIGRATE_LOG = export_dir / 'migrate.log'
PAGES_DIR = export_dir / 'pages'
OUT_JSON = export_dir / 'failed_from_log.json'

PATTERNS = [
    re.compile(r"페이지 처리 실패\s*\[(?P<title>[^]]+)\]:(?P<err>.*)$"),
    re.compile(r"첨부파일 다운로드 실패 \[(?P<filename>[^]]+)\]: (?P<err>.*)$"),
    re.compile(r"URL 이미지 다운로드 실패 \[(?P<url>[^]]+)\]: (?P<err>.*)$"),
    re.compile(r"Gliffy 썸네일 다운로드 최종 실패 \[(?P<display>[^]]+)\](?: \(pageId=(?P<pageId>\d+)[^)]*\))?"),
]

PAGEID_RE = re.compile(r"pageId=(?P<pageId>\d+)")
ATT_DIR_RE = re.compile(r"attachments_dir\s*=?\s*([^)\s]+)")


def find_page_by_title_or_id(title=None, page_id=None):
    if not Path(PAGES_DIR).exists():
        return None
    for root, dirs, files in os.walk(PAGES_DIR):
        if 'meta.json' in files:
            try:
                with open(os.path.join(root, 'meta.json'), 'r', encoding='utf-8') as f:
                    meta = json.load(f)
            except Exception:
                continue
            if page_id and str(meta.get('id')) == str(page_id):
                return root, meta
            if title and meta.get('title') and str(meta.get('title')) == str(title):
                return root, meta
    return None


def collect_attachments(folder):
    att_dir = os.path.join(folder, 'attachments')
    images = []
    others = []
    if not os.path.isdir(att_dir):
        return images, others
    for fn in sorted(os.listdir(att_dir)):
        p = os.path.join(att_dir, fn)
        if os.path.isfile(p):
            ext = os.path.splitext(fn)[1].lower()
            if ext in {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp'}:
                images.append(fn)
            else:
                others.append(fn)
    return images, others


def main():
    if not MIGRATE_LOG.exists():
        print(f"migrate.log not found at: {MIGRATE_LOG}")
        return

    results = []
    seen = set()

    with open(MIGRATE_LOG, 'r', encoding='utf-8', errors='ignore') as f:
        lines = [l.rstrip('\n') for l in f]

    for idx, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        if not re.search(r'ERROR|WARNING|페이지 처리 실패|첨부파일 다운로드 실패|URL 이미지 다운로드 실패|Gliffy', line, re.I):
            continue

        matched = False
        info = {'raw_line': line, 'title_from_log': None, 'pageId_from_log': None, 'error': None, 'found_folder': None, 'meta': None, 'images': [], 'other_attachments': []}

        for pat in PATTERNS:
            m = pat.search(line)
            if not m:
                continue
            gd = m.groupdict()
            info['error'] = gd.get('err') or line
            if gd.get('title'):
                info['title_from_log'] = gd.get('title')
            if gd.get('pageId'):
                info['pageId_from_log'] = gd.get('pageId')
            if gd.get('filename'):
                info['error'] = f"attachment_failure filename={gd.get('filename')}: {info['error']}"
            if gd.get('url'):
                info['error'] = f"url_failure url={gd.get('url')}: {info['error']}"
            matched = True
            break

        if not info['pageId_from_log'] and not info['found_folder']:
            lookback = 60
            start = max(0, idx - lookback)
            for j in range(idx, start - 1, -1):
                l = lines[j]
                if 'attachments_dir' in l:
                    m2 = ATT_DIR_RE.search(l)
                    if m2:
                        cand = m2.group(1)
                        cand = cand.replace('./', '').replace('\\/', '')
                        folder = cand
                        if not os.path.isabs(folder):
                            folder = os.path.join(str(export_dir), folder)
                        if os.path.isdir(folder):
                            info['found_folder'] = folder
                            break
                m3 = PAGEID_RE.search(l)
                if m3:
                    info['pageId_from_log'] = m3.group('pageId')
                    break

        if not info['found_folder'] and info.get('pageId_from_log'):
            found = find_page_by_title_or_id(page_id=info['pageId_from_log'])
            if found:
                folder, meta = found
                info['found_folder'] = folder
                info['meta'] = meta
                images, others = collect_attachments(folder)
                info['images'] = images
                info['other_attachments'] = others

        if info['found_folder'] and not info.get('meta'):
            try:
                with open(os.path.join(info['found_folder'], 'meta.json'), 'r', encoding='utf-8') as f:
                    info['meta'] = json.load(f)
            except Exception:
                info['meta'] = None
            images, others = collect_attachments(info['found_folder']) if info['found_folder'] else ([], [])
            info['images'] = images
            info['other_attachments'] = others

        key = (info.get('pageId_from_log'), info.get('title_from_log'), info.get('found_folder'))
        if key in seen:
            continue
        seen.add(key)
        results.append(info)

    try:
        with open(OUT_JSON, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f'Wrote: {OUT_JSON}')
    except Exception as e:
        print(f'Error writing out JSON: {e}', file=sys.stderr)

    if not results:
        print('No ERROR/WARNING entries found in migrate.log (or none matched patterns).')
        return
    print('\nExtracted items:')
    for r in results:
        print('-' * 60)
        print('title_from_log:', r.get('title_from_log'))
        print('pageId_from_log:', r.get('pageId_from_log'))
        print('found_folder:', r.get('found_folder'))
        if r.get('meta'):
            print('meta.id:', r['meta'].get('id'), 'meta.title:', r['meta'].get('title'))
        print('error snippet:', (r.get('error') or '')[:200])
        print('images:', ', '.join(r.get('images') or []))


if __name__ == '__main__':
    main()

