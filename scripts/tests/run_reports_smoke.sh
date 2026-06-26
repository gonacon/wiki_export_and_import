#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
SCRIPTS=${ROOT}/scripts/reports/export
EXPORT_DIR=${ROOT}/wiki_down_upload_export

echo "Running smoke tests for report pipeline..."

python3 ${SCRIPTS}/aggregate_log_failures.py || { echo 'aggregate failed'; exit 2; }
python3 ${SCRIPTS}/collect_failed_pages.py || { echo 'collect failed'; exit 3; }
python3 ${SCRIPTS}/show_top_failures.py --top 10 || { echo 'show_top failed'; exit 4; }
python3 ${SCRIPTS}/generate_failed_report.py --top 10 --out ${EXPORT_DIR}/failed_report_smoke.html || { echo 'report failed'; exit 5; }

echo "Checking outputs..."
[ -f "${EXPORT_DIR}/failed_from_log.json" ] || { echo 'missing failed_from_log.json'; exit 6; }
[ -f "${EXPORT_DIR}/failed_summary.json" ] || { echo 'missing failed_summary.json'; exit 7; }
[ -f "${EXPORT_DIR}/top_failed_detailed.csv" ] || { echo 'missing top_failed_detailed.csv'; exit 8; }
[ -f "${EXPORT_DIR}/failed_report_smoke.html" ] || { echo 'missing failed_report_smoke.html'; exit 9; }

echo "Smoke test passed: outputs present."
exit 0

