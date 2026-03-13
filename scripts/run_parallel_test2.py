#!/usr/bin/env python3
"""
Run a controlled parallel import test using sample folder 0000_기프티콘개발팀
"""
import logging
import time
import json
from pathlib import Path
from wiki_migration import importer, config

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
print('START test')

folder = Path('wiki_down_upload_export/pages/0000_기프티콘개발팀')
meta_path = folder / 'meta.json'
if not meta_path.exists():
    print('meta.json not found for sample folder:', folder)
    raise SystemExit(1)
meta = json.loads(meta_path.read_text(encoding='utf-8'))
root_old_id = str(meta.get('id'))
print('Using sample root_old_id=', root_old_id)

class DummyResp:
    def __init__(self, status=200, json_data=None):
        self.status_code = status
        self._json = json_data or {}
        self.headers = {'Content-Type': 'application/json'}
        self.content = b''
    def json(self):
        return self._json
    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

class DummySession:
    def get(self, url, params=None, timeout=None):
        if '/rest/api/content' in url and params and params.get('title'):
            return DummyResp(200, {'results': []})
        return DummyResp(200, {'id':'1','version':{'number':1},'body':{'storage':{'value':'<p>orig</p>'}}})
    def post(self, url, json=None, files=None, headers=None):
        return DummyResp(200, {'id': str(int(time.time()*1000) % 1000000)})
    def put(self, url, json=None):
        return DummyResp(200, {'id': url.split('/')[-1]})

config.new_session = DummySession()
# importer module imported new_session at import-time; override it too for testing
importer.new_session = DummySession()

print('Starting import_all_two_pass (parallel) ...')
importer.import_all_two_pass(inline_images=False, force_update=True, root_page_id=root_old_id, target_parent_id=None)
print('import_all_two_pass finished')

# show resume_state summary
rs_path = Path('wiki_down_upload_export/resume_state.json')
if rs_path.exists():
    rs = json.loads(rs_path.read_text(encoding='utf-8'))
    print('resume_state: downloaded=', len(rs.get('downloaded', [])), 'uploaded=', len(rs.get('uploaded', [])), 'page_map=', len(rs.get('page_map', {})))
else:
    print('resume_state.json not found')

print('END test')

