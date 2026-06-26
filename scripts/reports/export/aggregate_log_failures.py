#!/usr/bin/env python3
"""
Aggregate failures from the most recent backup migrate.log into JSON/CSV.
Moved into scripts/reports/export and uses scripts._common.utils.detect_export_dir().
"""
import re
import json
import csv
from collections import defaultdict
from pathlib import Path
import sys

# ensure repo root on path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._common import utils

export_dir = utils.detect_export_dir()
BACKUPS = export_dir / 'backups'

url_re = re.compile(r'URL 이미지 다운로드 실패 \[([^]]+)\]:\s*(.*)')
att_re = re.compile(r'첨부파일 다운로드 실패 \[([^]]+)\]:\s*(.*)')
pageid_re = re.compile(r'pageId=(\d+)')
att_dir_re = re.compile(r'attachments_dir=([^)\s]+)')


def run_aggregation(export_dir: Path):
    """Run aggregation and write outputs into export_dir."""
    BACKUPS = export_dir / 'backups'

    # find latest backup folder that contains migrate.log
    latest = None
    if BACKUPS.exists() and BACKUPS.is_dir():
        entries = sorted([p for p in BACKUPS.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
        for d in entries:
            if (d / 'migrate.log').exists():
                latest = d
                break

    if latest is None:
        log_path = export_dir / 'migrate.log'
    else:
        log_path = latest / 'migrate.log'

    if not log_path.exists():
        print('No migrate.log found in backups or root. Checked backups and root:', BACKUPS, export_dir)
        return 1, None, None

    out_json = export_dir / 'failed_from_log.json'
    out_csv = export_dir / 'failed_from_log.csv'

    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = [l.rstrip('\n') for l in f]

    entries = []
    for i, line in enumerate(lines):
        if 'URL 이미지 다운로드 실패' in line:
            m = url_re.search(line)
            if m:
                key = m.group(1)
                err = m.group(2)
            else:
                br = re.search(r"\[([^]]+)\]", line)
                key = br.group(1) if br else line
                err = line
            pageId = None
            folder = None
            for j in range(max(0, i-60), i):
                l = lines[j]
                m2 = pageid_re.search(l)
                if m2:
                    pageId = m2.group(1)
                    break
                m3 = att_dir_re.search(l)
                if m3:
                    folder = m3.group(1)
                    break
            entries.append({'type': 'url_failure', 'key': key, 'error': err, 'pageId': pageId, 'folder': folder, 'line': i+1})
        elif '첨부파일 다운로드 실패' in line:
            m = att_re.search(line)
            if m:
                key = m.group(1)
                err = m.group(2)
            else:
                br = re.search(r"\[([^]]+)\]", line)
                key = br.group(1) if br else line
                err = line
            pageId = None
            folder = None
            for j in range(max(0, i-60), i):
                l = lines[j]
                m2 = pageid_re.search(l)
                if m2:
                    pageId = m2.group(1)
                    break
                m3 = att_dir_re.search(l)
                if m3:
                    folder = m3.group(1)
                    break
            entries.append({'type': 'attachment_failure', 'key': key, 'error': err, 'pageId': pageId, 'folder': folder, 'line': i+1})

    # aggregate
    agg = defaultdict(lambda: {'count': 0, 'type': None, 'errors': [], 'pageIds': set(), 'folders': set()})
    for e in entries:
        k = e['key']
        a = agg[k]
        a['count'] += 1
        a['type'] = e['type']
        if len(a['errors']) < 5:
            a['errors'].append(e['error'])
        if e['pageId']:
            a['pageIds'].add(e['pageId'])
        if e['folder']:
            a['folders'].add(e['folder'])

    out = []
    for k, v in agg.items():
        out.append({
            'key': k,
            'type': v['type'],
            'count': v['count'],
            'error_samples': v['errors'],
            'pageIds': sorted(v['pageIds']),
            'folders': sorted(v['folders'])
        })

    out.sort(key=lambda x: x['count'], reverse=True)

    try:
        with open(out_json, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        with open(out_csv, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['type', 'key', 'count', 'pageIds', 'folders', 'error_samples'])
            for it in out:
                writer.writerow([it['type'], it['key'], it['count'], ';'.join(it['pageIds']), ';'.join(it['folders']), ' | '.join(it['error_samples'])])
    except Exception as e:
        print('Error writing aggregated outputs:', e)
        return 1, log_path, out_json

    return 0, log_path, out_json


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--out-dir', type=str, default=None, help='Directory to write failed_from_log.json/csv')
    args = parser.parse_args(argv)

    export_dir = utils.detect_export_dir()
    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        out_dir = export_dir

    out_dir.mkdir(parents=True, exist_ok=True)
    rc, log_path, out_json = run_aggregation(out_dir)
    if rc != 0:
        return rc
    print('Parsed log:', log_path)
    print('Wrote:', out_json)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


if __name__ == '__main__':
    raise SystemExit(main())


