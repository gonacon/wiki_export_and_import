#!/usr/bin/env python3
"""
generate_failed_report.py (export)

Generate a simple HTML report from failed_from_log.json / failed_summary.json.

This implementation embeds the JSON data safely in a <script type="application/json"> block
so the page can parse it without fragile JS string escaping.

This version also supports optional pre-run scripts (aggregation, collection, top CSV)
so it can auto-generate the source JSON if missing.
"""
import sys
import json
import argparse
import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from html import escape

# Ensure repo root is on sys.path so `import scripts._common` works when run as a script
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._common import utils


HTML_TEMPLATE = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Failed items report</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    body{font-family:Arial,Helvetica,sans-serif;padding:16px}
    .controls{margin-bottom:12px;gap:8px;display:flex;flex-wrap:wrap;align-items:center}
    table{border-collapse:collapse;width:100%} th,td{border:1px solid #ddd;padding:8px;vertical-align:top} th{background:#f2f2f2;text-align:left}
    img.thumb{max-width:200px;max-height:120px;object-fit:contain;border:1px solid #ccc;padding:2px;background:#fff}
    .mono{font-family:monospace;white-space:pre-wrap;word-break:break-word}
    input[type=text]{padding:6px;min-width:240px}
    select{padding:6px}
    button{padding:6px 10px}
  </style>
</head>
<body>
  <h1>Failed items report</h1>
  <p>Export dir: <<<EXPORT_DIR>>> — Source: <<<JSON_PATH>>> — items: <<<ITEMS_COUNT>>></p>
  <script id="data" type="application/json"><<<DATA_JSON>>></script>

  <div class="controls">
    <label>Domain: <select id="domainSelect"><option value="">(all)</option></select></label>
    <label>Search: <input type="text" id="searchInput" placeholder="search URL / filename / title / error..."></label>
    <label>Min count: <input type="number" id="minCount" value="1" style="width:80px"></label>
    <label><input type="checkbox" id="thumbToggle" checked> Show thumbnails</label>
    <label>Sort: <select id="sortSelect"><option value="count_desc">count ↓</option><option value="count_asc">count ↑</option><option value="key_asc">key A→Z</option></select></label>
    <button id="applyBtn">Apply</button>
    <button id="exportCsv">Export CSV (current view)</button>
    <button id="resetBtn">Reset</button>
  </div>

  <!-- Interactive table populated from embedded JSON -->
  <table id="resultTable">
    <thead>
      <tr><th>#</th><th>Type</th><th>Count</th><th>Key (URL / Filename)</th><th>Title</th><th>PageId</th><th>PageIds</th><th>PageTitles</th><th>Folders</th><th>Error samples</th><th>Preview</th></tr>
    </thead>
    <tbody></tbody>
  </table>

  <hr>
  <!-- Server-side rendered list (fallback and editor preview) -->
  <ul id="list" class="failed-list"><<<LIST_HTML>>></ul>

  <noscript>
    <p><em>JavaScript disabled — showing a simple list fallback.</em></p>
  </noscript>

  <script>
    const DATA = JSON.parse(document.getElementById('data').textContent || '[]');
    const EXPORT_DIR = <<<EXPORT_DIR>>>;

    function getDomain(key){
      try{
        if(typeof key!=='string') return '';
        if(key.startsWith('http')){
          const u = new URL(key);
          return u.hostname.replace('www.','');
        }
      }catch(e){}
      return '';
    }

    function guessRelPreview(key){
      try{
        if(!key) return null;
        const name = key.startsWith('http')?decodeURIComponent(new URL(key).pathname.split('/').pop()):key;
        for(const it of DATA){
          if(it.folders && it.folders.length){
            for(const f of it.folders){
              const candidate = f.replace(/\.(\/)?,?/,'').replace(/\.$/,'') + '/attachments/' + name;
              return candidate;
            }
          }
        }
      }catch(e){}
      return null;
    }

    function renderTable(items){
      const tbody = document.querySelector('#resultTable tbody');
      tbody.innerHTML = '';
      items.forEach((it, idx)=>{
        const tr = document.createElement('tr');
            const key = it.key || it.title || '';
                const title = it.title || (it.pageTitles||[]).join(';') || '';
                const pageId = it.firstPageId || '';
        const type = it.type || '';
        const count = it.count || 0;
        const pageIds = (it.pageIds||[]).join(';');
        const pageTitles = (it.pageTitles||[]).join(';');
        const folders = (it.folders||[]).join(';');
        const errors = (it.error_samples||[]).join('\\n') || (it.error?String(it.error):'');

        const tdIdx = document.createElement('td'); tdIdx.textContent = idx+1; tr.appendChild(tdIdx);
        const tdType = document.createElement('td'); tdType.textContent = type; tr.appendChild(tdType);
        const tdCount = document.createElement('td'); tdCount.textContent = count; tr.appendChild(tdCount);
        const tdKey = document.createElement('td'); tdKey.style.maxWidth='400px'; tdKey.style.overflow='auto';
        if(typeof key==='string' && key.startsWith('http')){
          const a = document.createElement('a'); a.href=key; a.target='_blank'; a.textContent=key; tdKey.appendChild(a);
        } else {
          tdKey.textContent = key;
        }
        tr.appendChild(tdKey);

        const tdTitle = document.createElement('td'); tdTitle.textContent = title; tr.appendChild(tdTitle);

        const tdPageId = document.createElement('td'); tdPageId.textContent = pageId; tr.appendChild(tdPageId);
        const tdPids = document.createElement('td'); tdPids.textContent = pageIds; tr.appendChild(tdPids);
        const tdPtitles = document.createElement('td'); tdPtitles.textContent = pageTitles; tr.appendChild(tdPtitles);

        const tdF = document.createElement('td'); tdF.textContent = folders; tr.appendChild(tdF);

        const tdErr = document.createElement('td'); tdErr.className='mono'; tdErr.style.maxWidth='300px'; tdErr.textContent = errors; tr.appendChild(tdErr);

        const tdPrev = document.createElement('td');
        // prefer attached_local if present
        const rel = (it.attached_local) ? it.attached_local : guessRelPreview(it.key || it.title || '');
        if(rel && document.location){
          const img = document.createElement('img'); img.className='thumb'; img.src = rel; img.alt = rel; const a = document.createElement('a'); a.href=rel; a.target='_blank'; a.appendChild(img); tdPrev.appendChild(a);
        }
        tr.appendChild(tdPrev);

        tbody.appendChild(tr);
      });
    }

    function populateDomainFilter(){
      const s = document.getElementById('domainSelect');
      const set = new Set();
      for(const it of DATA){
        const domain = getDomain(it.key||'');
        if(domain) set.add(domain);
      }
      const domains = Array.from(set).sort();
      for(const d of domains){
        const o = document.createElement('option'); o.value=d; o.textContent=d; s.appendChild(o);
      }
    }

    function applyFilters(){
      const domain = document.getElementById('domainSelect').value;
      const search = document.getElementById('searchInput').value.trim().toLowerCase();
      const minCount = parseInt(document.getElementById('minCount').value||'1',10)||1;
      const sort = document.getElementById('sortSelect').value;

      let filtered = DATA.filter(it=>{
        if((it.count||0) < minCount) return false;
        if(domain){
          const d = getDomain(it.key||''); if(d!==domain) return false;
        }
        if(search){
          const hay = ((it.key||'') + ' ' + (it.title||'') + ' ' + (it.error_samples||[]).join(' ') + ' ' + (it.error||'')).toLowerCase();
          if(hay.indexOf(search)===-1) return false;
        }
        return true;
      });

      if(sort==='count_desc') filtered.sort((a,b)=>b.count - a.count);
      else if(sort==='count_asc') filtered.sort((a,b)=>a.count - b.count);
      else if(sort==='key_asc') filtered.sort((a,b)=>String(a.key||a.title||'').localeCompare(String(b.key||b.title||'')));

      renderTable(filtered);
    }

    function exportCsv(){
      const rows = [];
      const hdr = ['type','key','title','pageId','count','pageIds','pageTitles','folders','error_samples'];
      rows.push(hdr.join(','));
      const tbody = document.querySelectorAll('#resultTable tbody tr');
      tbody.forEach(tr=>{
        const cols = tr.querySelectorAll('td');
        const type = '"'+cols[1].textContent.replace(/"/g,'""')+'"';
        const key = '"'+cols[3].textContent.replace(/"/g,'""')+'"';
        const title = '"'+cols[4].textContent.replace(/"/g,'""')+'"';
        const pageId = '"'+cols[5].textContent.replace(/"/g,'""')+'"';
        const count = cols[2].textContent;
        const pageIds = '"'+cols[6].textContent.replace(/"/g,'""')+'"';
        const pageTitles = '"'+cols[7].textContent.replace(/"/g,'""')+'"';
        const folders = '"'+cols[8].textContent.replace(/"/g,'""')+'"';
        const errs = '"'+cols[9].textContent.replace(/"/g,'""')+'"';
        rows.push([type,key,title,pageId,count,pageIds,pageTitles,folders,errs].join(','));
      });
      const blob = new Blob([rows.join('\n')], {type: 'text/csv;charset=utf-8;'});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = 'failed_report_filtered.csv'; document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    }

    document.getElementById('applyBtn').addEventListener('click', applyFilters);
    document.getElementById('exportCsv').addEventListener('click', exportCsv);
    document.getElementById('resetBtn').addEventListener('click', ()=>{document.getElementById('searchInput').value='';document.getElementById('domainSelect').value='';document.getElementById('minCount').value='1';document.getElementById('sortSelect').value='count_desc';applyFilters();});

    // init
    populateDomainFilter();
    applyFilters();
  </script>
</body>
</html>
"""


def run_script(script_path: Path, argv=None):
    """Run a Python script in the repo using the current interpreter.

    Returns subprocess returncode.
    """
    cmd = [sys.executable, str(script_path)] + (argv or [])
    print('Running:', ' '.join(cmd))
    return subprocess.call(cmd)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', help='Path to input JSON (export failures)')
    parser.add_argument('--top', type=int, default=None, help='Top N failures to include (omit or use --all to include all)')
    parser.add_argument('--all', action='store_true', help='Include all failures in the report')
    parser.add_argument('--out', type=str, default=None, help='Output HTML path')
    parser.add_argument('--out-dir', type=str, default=None, help='Output directory to place report and artifacts (overrides --out when provided as a dir)')
    parser.add_argument('--run-aggregate', action='store_true', help='Run log aggregation before report')
    parser.add_argument('--run-collect', action='store_true', help='Run page collection before report')
    parser.add_argument('--run-top-csv', action='store_true', help='Run top CSV generation before report')
    parser.add_argument('--run-all', action='store_true', help='Run aggregate, collect and top CSV before report')
    parser.add_argument('--no-auto', action='store_true', help='Do not auto-run aggregate/collect if inputs are missing')
    args = parser.parse_args(argv)

    export_dir = utils.detect_export_dir()
    pages_dir = export_dir / 'pages'
    # Determine output directory and HTML path. New behavior: collect all artifacts into a folder.
    if args.out_dir:
        out_dir = Path(args.out_dir)
        # if user passed a file path accidentally, use its parent
        if out_dir.suffix and (out_dir.suffix == '.html' or out_dir.suffix == '.htm'):
            out_dir = out_dir.parent
    elif args.out:
        # if --out provided and is a directory-like (no .html), use it as dir; otherwise use parent dir
        maybe = Path(args.out)
        if maybe.suffix and (maybe.suffix == '.html' or maybe.suffix == '.htm'):
            out_dir = maybe.parent
        else:
            out_dir = maybe
    else:
        out_dir = export_dir / 'failed_report'

    # If directory already exists and is non-empty, create a timestamped sibling to avoid clobber
    # Only auto-rename when out_dir was not explicitly provided by the user (i.e. using default)
    if (not args.out_dir) and out_dir.exists() and any(out_dir.iterdir()):
        now = datetime.now().strftime('%Y%m%d_%H%M%S')
        out_dir = out_dir.with_name(out_dir.name + '_' + now)

    out_html = (out_dir / 'failed_report.html')

    # Prefer looking for source JSONs in the output directory (out_dir) when present,
    # otherwise fall back to the export_dir locations.
    default_json = None
    fallback_json = None
    try:
        if out_dir and (out_dir.exists() or True):
            cand = out_dir / 'failed_from_log.json'
            cand2 = out_dir / 'failed_summary.json'
            default_json = cand if cand.exists() else None
            fallback_json = cand2 if cand2.exists() else None
        # fallback to export_dir if nothing found in out_dir
        if default_json is None and export_dir is not None:
            cand = export_dir / 'failed_from_log.json'
            if cand.exists():
                default_json = cand
        if fallback_json is None and export_dir is not None:
            cand = export_dir / 'failed_summary.json'
            if cand.exists():
                fallback_json = cand
    except Exception:
        default_json = None
        fallback_json = None

    # scripts to potentially run
    scripts_dir = REPO_ROOT / 'scripts' / 'reports' / 'export'
    agg_script = scripts_dir / 'aggregate_log_failures.py'
    collect_script = scripts_dir / 'collect_failed_pages.py'
    top_script = scripts_dir / 'show_top_failures.py'

    # If user requested run-all, set flags
    if args.run_all:
        args.run_aggregate = True
        args.run_collect = True
        args.run_top_csv = True

    # Determine initial json_path
    json_path = None
    if args.input:
        json_path = Path(args.input)
    else:
        if default_json and default_json.exists():
            json_path = default_json
        elif fallback_json and fallback_json.exists():
            json_path = fallback_json

    # Auto-run aggregate if inputs are missing and not --no-auto
    if json_path is None and not args.no_auto:
        if agg_script.exists():
            rc = run_script(agg_script, argv=['--out-dir', str(out_dir)])
            if rc != 0:
                print('Aggregation failed (rc=', rc, '); aborting report generation')
                return rc
        if default_json and default_json.exists():
            json_path = default_json
        elif fallback_json and fallback_json.exists():
            json_path = fallback_json

    # If still missing and user asked to run specific steps, run them
    if json_path is None:
        if args.run_aggregate and agg_script.exists():
            rc = run_script(agg_script, argv=['--out-dir', str(out_dir)])
            if rc != 0:
                print('Aggregation failed (rc=' + str(rc) + '); continuing to attempt collect')
        if args.run_collect and collect_script.exists():
            rc2 = run_script(collect_script, argv=['--out-dir', str(out_dir)])
            if rc2 != 0:
                print('Collect failed (rc=' + str(rc2) + '); continuing with available JSON')
        # re-evaluate
        if default_json and default_json.exists():
            json_path = default_json
        elif fallback_json and fallback_json.exists():
            json_path = fallback_json

    if json_path is None:
        print('No failure JSON found. Run aggregation script first (scripts/reports/export/aggregate_log_failures.py) or use --run-aggregate')
        return 2

    # Optionally run collect (to generate failed_summary.json) but non-fatal
    if args.run_collect and collect_script.exists():
        if run_script(collect_script, argv=['--out-dir', str(out_dir)]) != 0:
            print('Collect failed; continuing with available JSON')

    items = utils.read_json(json_path)

    # Build pageId -> title map by scanning pages/*/meta.json
    page_map = {}
    try:
        if pages_dir.exists():
            for d in pages_dir.iterdir():
                if not d.is_dir():
                    continue
                meta = d / 'meta.json'
                if meta.exists():
                    try:
                        m = json.loads(meta.read_text(encoding='utf-8'))
                        pid = m.get('id')
                        title = m.get('title')
                        if pid is not None:
                            page_map[str(pid)] = title
                    except Exception:
                        continue
    except Exception:
        pass

    # Optionally run top CSV (do this after loading items so we can pass an appropriate top value when --all is requested)
    if args.run_top_csv and top_script.exists():
        if args.all:
            top_count = len(items)
        elif args.top is not None:
            top_count = args.top
        else:
            top_count = 100
        # Ask the top script to write its CSV directly into our out_dir when possible
        top_outp = out_dir / 'top_failed_detailed.csv'
        run_script(top_script, argv=['--top', str(top_count), '--out', str(top_outp)])

    # Select items according to --top/--all
    if args.all:
        selected_items = items
    elif args.top is not None:
        selected_items = items[:args.top]
    else:
        selected_items = items

    # Normalize pageId(s) and enrich selected items with page titles
    for it in selected_items:
        # If item has a singular 'pageId' (from collect_failed_pages), normalize to list
        if it.get('pageIds') is None or not it.get('pageIds'):
            if it.get('pageId') is not None:
                try:
                    it['pageIds'] = [str(it.get('pageId'))]
                except Exception:
                    it['pageIds'] = []
            else:
                it['pageIds'] = []
        else:
            # ensure values are strings
            it['pageIds'] = [str(p) for p in it.get('pageIds')]

        # Populate a top-level 'title' when available (use existing 'title' or infer from page_map)
        if not it.get('title'):
            pids = it.get('pageIds') or []
            for pid in pids:
                t = page_map.get(str(pid))
                if t:
                    it['title'] = t
                    break

        # Provide a list of resolved page titles (may be empty)
        it['pageTitles'] = [page_map.get(str(pid)) for pid in (it.get('pageIds') or []) if page_map.get(str(pid))]

    # Helper: locate a local attachment file by name under pages_dir
    def find_local_attachment(name):
        if not name:
            return None
        try:
            for root, dirs, files in __import__('os').walk(pages_dir):
                for fn in files:
                    if fn == name or fn.endswith('__' + name) or fn.endswith('-' + name):
                        return __import__('pathlib').Path(root) / fn
                # suffix match case-insensitive
                for fn in files:
                    try:
                        if fn.lower().endswith(name.lower()):
                            return __import__('pathlib').Path(root) / fn
                    except Exception:
                        continue
        except Exception:
            return None
        return None

    # Augment items with a firstPageId and attached_local (relative path from out_dir) when possible
    for it in selected_items:
        pids = it.get('pageIds') or []
        it['firstPageId'] = (str(pids[0]) if pids else None)
        # try to find a local attachment matching the key (URL basename) or any folder-listed attachments
        cand_names = []
        k = it.get('key')
        if isinstance(k, str):
            try:
                if k.startswith('http'):
                    from urllib.parse import urlparse, unquote
                    base = unquote(urlparse(k).path.split('/')[-1])
                else:
                    base = __import__('os').path.basename(k)
                if base:
                    cand_names.append(base)
            except Exception:
                pass
        # also consider title-derived names
        t = it.get('title')
        if t and isinstance(t, str):
            cand_names.append(t)

        attached = None
        for name in cand_names:
            found = find_local_attachment(name)
            if found:
                try:
                    attached = str(__import__('os').path.relpath(str(found), start=str(out_dir)))
                except Exception:
                    attached = str(found)
                break

        # If not found yet, try folders listed in item
        if not attached:
            for f in it.get('folders') or []:
                try:
                    cand = __import__('pathlib').Path(f)
                    attdir = cand / 'attachments'
                    if attdir.exists():
                        for fn in attdir.iterdir():
                            if fn.is_file():
                                attached = str(__import__('os').path.relpath(str(fn), start=str(out_dir)))
                                break
                    if attached:
                        break
                except Exception:
                    continue

        it['attached_local'] = attached

    data_json = json.dumps(selected_items, ensure_ascii=False)

    # Build a server-side HTML list representation so the report is readable
    # even when JavaScript is disabled or an editor preview doesn't run scripts.
    def make_list_html(items_list):
        parts = []
        for it in items_list:
            key = it.get('key') or it.get('title') or ''
            # Render key as clickable link when it looks like a URL
            key_text = escape(str(key))
            href = escape(str(key))
            if str(key).startswith('http://') or str(key).startswith('https://'):
                title_html = f'<a href="{href}" target="_blank" rel="noopener noreferrer">{key_text}</a>'
            else:
                title_html = f'<span>{key_text}</span>'

            type_ = escape(str(it.get('type', '')))
            count = escape(str(it.get('count', '')))

            li = f'<li><div><strong>{title_html}</strong>'
            li += f'<div class="meta">{type_} — count: {count}</div>'

            # show pageIds and titles when available
            pids = it.get('pageIds') or []
            if pids:
                li += f'<div class="meta">pageIds: {escape(", ".join([str(x) for x in pids]))}</div>'
            ptitles = it.get('pageTitles') or []
            if ptitles:
                li += f'<div class="meta">pageTitles: {escape(", ".join([str(x) for x in ptitles]))}</div>'

            # show title explicitly when present
            if it.get('title'):
                li += f'<div class="meta">title: {escape(str(it.get("title")))}</div>'

            # show error or error samples when available
            err = it.get('error')
            samples = it.get('error_samples') or it.get('error_sample') or []
            if err:
                li += f'<div class="meta">error: {escape(str(err))}</div>'
            if samples:
                li += '<details><summary>Examples</summary><ol>'
                for s in samples[:10]:
                    li += f'<li>{escape(str(s))}</li>'
                li += '</ol></details>'

            li += '</li>'
            parts.append(li)
        return '\n'.join(parts)

    list_html = make_list_html(selected_items)

    html = HTML_TEMPLATE
    html = html.replace('<<<DATA_JSON>>>', data_json)
    html = html.replace('<<<LIST_HTML>>>', list_html)
    html = html.replace('<<<EXPORT_DIR>>>', json.dumps(str(export_dir)))
    html = html.replace('<<<JSON_PATH>>>', json.dumps(str(json_path)))
    html = html.replace('<<<ITEMS_COUNT>>>', str(len(items)))

    out_dir.mkdir(parents=True, exist_ok=True)

    # Write HTML
    utils.write_text(out_html, html)
    print('Wrote HTML report to', out_html)

    # Copy source JSON into the output directory for traceability
    try:
        if json_path and json_path.exists():
            dst_json = out_dir / json_path.name
            shutil.copy2(str(json_path), str(dst_json))
            print('Copied source JSON to', dst_json)
    except Exception as e:
        print('Warning: failed to copy source JSON:', e)

    # Write the selected items as a separate JSON file
    try:
        sel_path = out_dir / 'selected_items.json'
        sel_path.write_text(json.dumps(selected_items, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Wrote selected items JSON to', sel_path)
    except Exception as e:
        print('Warning: failed to write selected_items.json:', e)

    # Copy a couple of related CSVs if present (convenience)
    copied = set()
    for name in ('failed_from_log.csv', 'failed_summary.csv'):
        src = export_dir / name
        dst = out_dir / name
        if src.exists():
            try:
                shutil.copy2(str(src), str(dst))
                print('Copied', name, 'to', out_dir)
                copied.add(name)
            except Exception as e:
                print('Warning: failed to copy', name, e)
    # Also copy top CSV if it was written to export_dir or to expected location
    top_cands = [export_dir / 'top_failed_detailed.csv', out_dir / 'top_failed_detailed.csv']
    for t in top_cands:
        if t.exists():
            try:
                dst = out_dir / t.name
                try:
                    if t.resolve() == dst.resolve():
                        print(f'{t.name} already in output directory')
                        continue
                except Exception:
                    pass
                shutil.copy2(str(t), str(dst))
                print('Copied', t.name, 'to', out_dir)
            except Exception as e:
                print('Warning: failed to copy', t, e)

    # Remove originals from export_dir when we've copied them into the report folder
    try:
        if out_dir.resolve() != export_dir.resolve():
            for name in ('failed_from_log.json', 'failed_from_log.csv', 'failed_summary.json', 'failed_summary.csv'):
                src = export_dir / name
                dst = out_dir / name
                if src.exists() and dst.exists():
                    try:
                        src.unlink()
                        print('Removed original from export dir:', src)
                    except Exception as e:
                        print('Warning: failed to remove', src, e)
    except Exception:
        pass

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
