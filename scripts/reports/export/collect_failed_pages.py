#!/usr/bin/env python3
"""
collect_failed_pages.py (export)

Collects failed page info under EXPORT_DIR and writes failed_summary.json/csv.
Moved into scripts/reports/export and uses scripts._common.utils.
"""
import sys
import json
import csv
from pathlib import Path
from typing import Optional

# ensure repo root on path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._common import utils

export_dir: Optional[Path] = None
PAGES_DIR: Optional[Path] = None
FAILED_JSON: Optional[Path] = None
FAILED_GLIFFY: Optional[Path] = None
INVALID_JSON: Optional[Path] = None

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp'}


def load_json_safe(path):
    if not path.exists():
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: failed to load JSON {path}: {e}", file=sys.stderr)
        return None


def find_page_folder_by_id(page_id):
    # defensive: ensure PAGES_DIR set and exists before iterating
    if PAGES_DIR is None:
        return None
    if not PAGES_DIR.exists():
        return None
    for root in PAGES_DIR.rglob('*'):
        if root.is_dir():
            meta_p = root / 'meta.json'
            if meta_p.exists():
                try:
                    with open(meta_p, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                    if str(meta.get('id')) == str(page_id):
                        return root, meta
                except Exception:
                    continue
    return None


def collect_attachments(folder):
    att_dir = folder / 'attachments'
    images = []
    others = []
    if not att_dir.exists():
        return images, others
    for fn in sorted([p.name for p in att_dir.iterdir() if p.is_file()]):
        ext = Path(fn).suffix.lower()
        if ext in IMAGE_EXTS:
            images.append(fn)
        else:
            others.append(fn)
    return images, others


def run_collect(export_dir: Path):
    global PAGES_DIR, FAILED_JSON, FAILED_GLIFFY, INVALID_JSON
    PAGES_DIR = export_dir / 'pages'
    FAILED_JSON = export_dir / 'failed_pages.json'
    FAILED_GLIFFY = export_dir / 'failed_gliffy.json'
    INVALID_JSON = export_dir / 'invalid_pages.json'

    # Ensure the export_dir exists so we can write summary artifacts into it
    try:
        export_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        # If mkdir fails for any reason, we'll let the subsequent file writes raise
        pass

    failed = load_json_safe(FAILED_JSON) or []
    failed_gliffy = load_json_safe(FAILED_GLIFFY) or []
    invalid = load_json_safe(INVALID_JSON) or []

    summary = []

    for item in failed:
        page_id = item.get('id')
        error = item.get('error')
        folder_meta = find_page_folder_by_id(page_id)
        if folder_meta:
            folder, meta = folder_meta
            title = meta.get('title')
            images, others = collect_attachments(folder)
        else:
            title = None
            images = []
            others = []
            folder = None
        summary.append({
            'pageId': page_id,
            'title': title,
            'folder': str(folder) if folder else None,
            'error': error,
            'images': images,
            'other_attachments': others,
            'type': 'page_failure'
        })

    for item in failed_gliffy:
        page_id = item.get('pageId')
        page_title = item.get('pageTitle')
        macro_id = item.get('macroId')
        display = item.get('displayName')
        folder = item.get('folder')
        images = []
        others = []
        if folder and (Path(folder) / 'attachments').exists():
            imgs, oth = collect_attachments(Path(folder))
            images = imgs
            others = oth
        summary.append({
            'pageId': page_id,
            'title': page_title,
            'folder': folder,
            'error': f'gliffy_failure macroId={macro_id} displayName={display}',
            'images': images,
            'other_attachments': others,
            'gliffy_macroId': macro_id,
            'gliffy_displayName': display,
            'type': 'gliffy_failure'
        })

    for item in invalid:
        summary.append({
            'pageId': None,
            'title': None,
            'folder': None,
            'error': f'invalid_item: {item}',
            'images': [],
            'other_attachments': [],
            'type': 'invalid_item'
        })

    out_json = export_dir / 'failed_summary.json'
    out_csv = export_dir / 'failed_summary.csv'
    try:
        with open(out_json, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f'Wrote: {out_json}')
    except Exception as e:
        print(f'Error writing JSON summary: {e}', file=sys.stderr)

    try:
        with open(out_csv, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            header = ['pageId', 'title', 'folder', 'error', 'images', 'other_attachments', 'type']
            writer.writerow(header)
            for s in summary:
                writer.writerow([
                    s.get('pageId'),
                    s.get('title'),
                    s.get('folder'),
                    s.get('error'),
                    ';'.join(s.get('images') or []),
                    ';'.join(s.get('other_attachments') or []),
                    s.get('type')
                ])
        print(f'Wrote: {out_csv}')
    except Exception as e:
        print(f'Error writing CSV summary: {e}', file=sys.stderr)

    if not summary:
        print('No failed items were found.')
        return 0

    print('\nSummary of failed items:')
    for s in summary:
        print('-' * 60)
        print(f"type: {s.get('type')}")
        print(f"pageId: {s.get('pageId')}")
        print(f"title: {s.get('title')}")
        print(f"folder: {s.get('folder')}")
        print(f"error: {s.get('error')}")
        print(f"images({len(s.get('images') or [])}): {', '.join(s.get('images') or [])}")
        if s.get('type') == 'gliffy_failure':
            print(f"gliffy_macroId: {s.get('gliffy_macroId')}, displayName: {s.get('gliffy_displayName')}")

    return 0

def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--out-dir', type=str, default=None, help='Directory to read input and write failed_summary.json/csv')
    args = parser.parse_args(argv)

    export_dir = utils.detect_export_dir()
    if args.out_dir:
        export_dir = Path(args.out_dir)

    return run_collect(export_dir)


if __name__ == '__main__':
    raise SystemExit(main())

