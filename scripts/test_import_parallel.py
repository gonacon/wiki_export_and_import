#!/usr/bin/env python3
"""
Test runner for parallel import_all_two_pass using a dummy session to avoid real HTTP calls.
Usage: python3 scripts/test_import_parallel.py
"""
import time
from pathlib import Path
from wiki_migration import importer, config

# backup resume_state
p = Path('wiki_down_upload_export/resume_state.json')
if p.exists():
    p.rename('wiki_down_upload_export/resume_state.json.bak')

class DummyResp:
    def __init__(self, status=200, json_data=None):
        self.status_code = status
        self._json = json_data or {}
        self.headers = {'Content-Type': 'application/json'}
    def json(self):
        return self._json
    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

class DummySession:
    def get(self, url, params=None, timeout=None):
        # simulate title search
        if '/rest/api/content' in url and params and params.get('title'):
            return DummyResp(200, {'results': []})
        # simulate get page
        return DummyResp(200, {'id':'1','version':{'number':1},'body':{'storage':{'value':'<p>orig</p>'}}})
    def post(self, url, json=None, files=None, headers=None):
        # return new id
        return DummyResp(200, {'id': str(int(time.time()*1000) % 1000000)})
    def put(self, url, json=None):
        return DummyResp(200, {'id': url.split('/')[-1]})

config.new_session = DummySession()

# read the example meta.json page id
meta_path = Path('wiki_down_upload_export/pages/0000_기프티콘 PUSH, 푸시/meta.json')
if not meta_path.exists():
    print('meta.json not found:', meta_path)
else:
    import json
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    old_id = meta.get('id')
    print('Running import_all_two_pass for root old_id=', old_id)
    importer.import_all_two_pass(inline_images=False, force_update=True, root_page_id=str(old_id), target_parent_id=None)
    print('Done')

