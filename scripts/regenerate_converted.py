#!/usr/bin/env python3
"""
Regenerate page.storage.converted.html for all exported pages.
Usage: python3 scripts/regenerate_converted.py [EXPORT_PAGES_DIR]
Defaults to wiki_down_upload_export/pages in repo root.
"""
import sys
import os
import traceback

ROOT_DEFAULT = os.path.join(os.path.dirname(__file__), '..', 'wiki_down_upload_export', 'pages')
ROOT_DEFAULT = os.path.normpath(ROOT_DEFAULT)

def main(root_dir=None):
    root = root_dir or ROOT_DEFAULT
    print(f"Root pages dir: {root}")
    if not os.path.isdir(root):
        print("ERROR: root pages dir does not exist:", root)
        return 2

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
    try:
        from wiki_migration.sanitizer import Sanitizer
        from wiki_migration.utils import fix_url_images_in_html
    except Exception as e:
        print("ERROR: failed to import project modules:", e)
        traceback.print_exc()
        return 3

    import requests

    session = requests.Session()

    total = 0
    converted = 0
    skipped = 0
    failed = []

    for name in sorted(os.listdir(root)):
        folder = os.path.join(root, name)
        if not os.path.isdir(folder):
            continue
        total += 1
        in_path = os.path.join(folder, 'page.storage.html')
        out_path = os.path.join(folder, 'page.storage.converted.html')
        att_dir = os.path.join(folder, 'attachments')
        if not os.path.exists(in_path):
            skipped += 1
            print(f"SKIP(no page.storage.html): {name}")
            continue
        try:
            with open(in_path, 'r', encoding='utf-8') as f:
                raw = f.read()
            repaired = Sanitizer.repair_broken_confluence_links(raw)
            converted_html = fix_url_images_in_html(repaired, att_dir, session)
            # normalize any remaining ri:attachment refs (remove nested ri:page etc.)
            try:
                converted_html = Sanitizer.normalize_ri_attachment_refs(converted_html)
            except Exception:
                pass
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(converted_html)
            converted += 1
            print(f"OK: {name} -> page.storage.converted.html")
        except Exception as e:
            failed.append((name, str(e)))
            print(f"FAILED: {name} -> {e}")
            traceback.print_exc()

    print('\nSummary:')
    print(f'  total folders: {total}')
    print(f'  converted: {converted}')
    print(f'  skipped (no page.storage.html): {skipped}')
    print(f'  failed: {len(failed)}')
    if failed:
        for n, err in failed:
            print(f'    - {n}: {err}')
    return 0

if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(main(arg))
