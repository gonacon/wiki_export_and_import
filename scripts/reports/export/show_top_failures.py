#!/usr/bin/env python3
"""
show_top_failures.py (export)

Generate detailed CSV for top-N failures by resolving pages/attachments where possible.
"""
import argparse
import json
import os
import sys
from pathlib import Path

# ensure repo root on path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._common import utils

export_dir = utils.detect_export_dir()
PAGES_DIR = export_dir / 'pages'

POSSIBLE_JSONS = [
    export_dir / 'failed_from_log.json',
    export_dir / 'failed_summary.json'
]

def locate_input_json():
    for p in POSSIBLE_JSONS:
        if p.exists():
            return p
    return None

def load_json(p):
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)

def find_page_by_id(page_id):
    if not PAGES_DIR.exists():
        return None
    for d in PAGES_DIR.iterdir():
        if not d.is_dir():
            continue
        meta_p = d / 'meta.json'
        if meta_p.exists():
            try:
                m = json.load(open(meta_p, encoding='utf-8'))
                if str(m.get('id') or m.get('pageId') or m.get('page_id') or '') == str(page_id):
                    return d, m
            except Exception:
                continue
    return None

def find_page_by_attachment_name(name):
    if not PAGES_DIR.exists():
        return None
    for d in PAGES_DIR.iterdir():
        if not d.is_dir():
            continue
        att_dir = d / 'attachments'
        if not att_dir.exists():
            continue
        for fn in att_dir.iterdir():
            if fn.is_file():
                if fn.name == name or fn.name.endswith('__' + name) or fn.name.lower().endswith(name.lower()):
                    meta_p = d / 'meta.json'
                    meta = None
                    if meta_p.exists():
                        try:
                            meta = json.load(open(meta_p, encoding='utf-8'))
                        except Exception:
                            meta = None
                    return d, meta, str(fn)
    return None

def normalize_folder_string(folder_str):
    if not folder_str:
        return None
    s = folder_str
    if s.startswith('./'):
        s = s[2:]
    if str(export_dir) in s:
        idx = s.find(str(export_dir))
        s = s[idx + len(str(export_dir)):]
        s = s.lstrip('/\\')
    cand = export_dir / s
    return cand

def main():
    p = locate_input_json()
    if not p:
        print('No aggregated failure JSON found. Run scripts/reports/export/aggregate_log_failures.py first.')
        return 1
    data = load_json(p)
    parser = argparse.ArgumentParser()
    parser.add_argument('--top', type=int, default=100)
    parser.add_argument('--out', type=str, default=str(export_dir / 'top_failed_detailed.csv'))
    args = parser.parse_args()

    out_rows = []
    count = 0
    for it in data[:args.top]:
        count += 1
        key = it.get('key')
        typ = it.get('type')
        cnt = it.get('count')
        errs = ' | '.join(it.get('error_samples') or [])
        pageIds = it.get('pageIds') or []
        folders = it.get('folders') or []

        resolved = []
        for pid in pageIds:
            found = find_page_by_id(pid)
            if found:
                d, meta = found
                title = meta.get('title') if meta else d.name
                resolved.append({'pageId': pid, 'title': title, 'folder': str(d)})

        for f in folders:
            try:
                cand = normalize_folder_string(f)
                if cand and cand.exists():
                    meta_p = cand / 'meta.json'
                    meta = None
                    if meta_p.exists():
                        try:
                            meta = json.load(open(meta_p, encoding='utf-8'))
                        except Exception:
                            meta = None
                    title = meta.get('title') if meta else cand.name
                    pid = None
                    if meta:
                        pid = meta.get('id') or meta.get('pageId') or meta.get('page_id')
                    resolved.append({'pageId': pid, 'title': title, 'folder': str(cand)})
            except Exception:
                pass

        attached_local = None
        if isinstance(key, str) and (key.startswith('http') or '/' in key):
            from urllib.parse import urlparse, unquote
            try:
                base = os.path.basename(unquote(urlparse(key).path))
            except Exception:
                base = os.path.basename(key)
            found_att = find_page_by_attachment_name(base)
            if found_att:
                d, meta, fn = found_att
                title = meta.get('title') if meta else d.name
                pid = (meta.get('id') if meta and meta.get('id') else None)
                resolved.append({'pageId': pid, 'title': title, 'folder': str(d)})
                attached_local = fn

        out_rows.append({
            'rank': count,
            'key': key,
            'type': typ,
            'count': cnt,
            'error_samples': errs,
            'pageIds_from_json': ';'.join(pageIds),
            'folders_from_json': ';'.join(folders),
            'resolved_pages': resolved,
            'attached_local': attached_local
        })

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    import csv
    with open(outp, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['rank','key','type','count','error_samples','pageIds_from_json','folders_from_json','resolved_pages','attached_local'])
        for r in out_rows:
            w.writerow([r['rank'], r['key'], r['type'], r['count'], r['error_samples'], r['pageIds_from_json'], r['folders_from_json'], json.dumps(r['resolved_pages'], ensure_ascii=False), r['attached_local'] or ''])

    print(f'Wrote detailed CSV to: {outp} (top {len(out_rows)})')
    for r in out_rows[:min(20, len(out_rows))]:
        print(f"#{r['rank']:>3} count={r['count']:>3} key={r['key'][:80]}")
        for rp in r['resolved_pages']:
            print(f"     -> pageId={rp.get('pageId')} title={rp.get('title')} folder={rp.get('folder')}")
        if r['attached_local']:
            print(f"     local_attachment={r['attached_local']}")

    return 0


if __name__ == '__main__':
    raise SystemExit(main())

