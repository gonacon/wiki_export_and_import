"""
Legacy wrapper that exposes the original CLI while delegating functionality
to the refactored modules: config, exporter, importer, sanitizer, utils.
The original single-file implementation is preserved as a backup at
`wiki_export_and_import.py`.
"""

from .config import OLD_BASE, NEW_BASE, OLD_USER, OLD_PASS, NEW_USER, NEW_PASS, SPACE, NEW_SPACE, EXPORT_DIR
from .exporter import export_all
from .importer import import_all
from .config import old_session, new_session
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description='Confluence Wiki Migration Tool')
    parser.add_argument('mode', choices=['export', 'import', 'migrate', 'retry-gliffy'])
    parser.add_argument('--page-id', default=None)
    parser.add_argument('--inline-images', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--force-update', action='store_true')
    args = parser.parse_args()

    if args.mode == 'export':
        export_all(old_session, OLD_BASE, SPACE, root_page_id=args.page_id, inline_images=args.inline_images)
    elif args.mode == 'import':
        import_all(inline_images=args.inline_images, force_update=args.force_update)
    elif args.mode == 'migrate':
        # login steps omitted; expect env vars or interactive usage in original file
        export_all(old_session, OLD_BASE, SPACE, root_page_id=args.page_id, inline_images=args.inline_images)
        import_all(inline_images=args.inline_images, force_update=args.force_update)
    elif args.mode == 'retry-gliffy':
        print('retry-gliffy not implemented in refactor wrapper; run original backup if needed')


if __name__ == '__main__':
    main()
