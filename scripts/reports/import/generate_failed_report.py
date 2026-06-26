#!/usr/bin/env python3
"""
generate_failed_report.py (import)

Initial template for import-side failure report. The import log format may
be different from export; adapt parsing logic as needed. By default this
script expects a JSON input (e.g. import_failed.json) and renders a simple
HTML indicating the items. This is a starting point for import-reporting.
"""
import argparse
import json
from pathlib import Path
import sys

# ensure repo root on path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._common import utils


HTML_TEMPLATE = """<!doctype html><html><head><meta charset='utf-8'><title>Import Failures</title></head><body>
<h1>Import Failures (placeholder)</h1>
<p>Input JSON: <<<JSON_PATH>>></p>
<pre><<<DATA>>></pre>
</body></html>
"""


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', help='Path to input JSON (import failures)')
    parser.add_argument('--out', help='Output HTML path', default=None)
    args = parser.parse_args(argv)

    import_dir = utils.detect_import_dir()
    input_path = Path(args.input) if args.input else (import_dir / 'import_failed.json')
    if not input_path.exists():
        print('No import failure JSON found at', input_path)
        return 2

    data = utils.read_json(input_path)
    html = HTML_TEMPLATE.replace('<<<JSON_PATH>>>', str(input_path)).replace('<<<DATA>>>', json.dumps(data, ensure_ascii=False, indent=2))
    out_path = Path(args.out) if args.out else (import_dir / 'import_failed_report.html')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    utils.write_text(out_path, html)
    print('Wrote import failure report to', out_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

