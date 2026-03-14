#!/usr/bin/env python3
"""
Download images referenced by <ri:url> in page.storage.html, save them with unique names,
and produce a converted HTML where <ri:url> tags are replaced by <ri:attachment ri:filename="..."/>.
Target page: pages/5174_APNs
"""
import os
import re
import sys
import hashlib
import html as htmlmod
from urllib.parse import unquote
from urllib.request import Request, urlopen

ROOT = os.path.dirname(os.path.dirname(__file__))
PAGE_DIR = os.path.join(ROOT, 'wiki_down_upload_export', 'pages', '5174_APNs')
SRC_HTML = os.path.join(PAGE_DIR, 'page.storage.html')
OUT_HTML = os.path.join(PAGE_DIR, 'page.storage.converted.fixed.html')
ATT_DIR = os.path.join(PAGE_DIR, 'attachments')

URL_RE = re.compile(r'<ri:url\s+ri:value="([^"]+)"\s*/?>', re.IGNORECASE)
IMAGE_BLOCK_RE = re.compile(r'(<ac:image\b[^>]*>)(.*?)(</ac:image>)', re.DOTALL | re.IGNORECASE)

if not os.path.exists(PAGE_DIR):
    print('Page dir not found:', PAGE_DIR)
    sys.exit(1)
if not os.path.exists(SRC_HTML):
    print('Source HTML not found:', SRC_HTML)
    sys.exit(2)
if not os.path.isdir(ATT_DIR):
    os.makedirs(ATT_DIR)

with open(SRC_HTML, 'r', encoding='utf-8') as f:
    src = f.read()

# normalize &amp; occurrences when extracting
urls = []
for m in URL_RE.finditer(src):
    u = m.group(1).replace('&amp;', '&')
    urls.append(u)

unique_urls = []
for u in urls:
    if u not in unique_urls:
        unique_urls.append(u)

print(f'Found {len(urls)} ri:url occurrences, {len(unique_urls)} unique URLs')

mapping = {}  # url -> saved filename

hdr = {'User-Agent': 'Mozilla/5.0 (compatible)'}

for url in unique_urls:
    # compute safe basename and unique prefix
    parsed_name = os.path.basename(unquote(url.split('?',1)[0]))
    if not parsed_name:
        print('skip (no basename):', url)
        continue
    url_hash = hashlib.sha1(url.encode('utf-8')).hexdigest()[:8]
    save_name = f"{url_hash}__{parsed_name}"
    save_path = os.path.join(ATT_DIR, save_name)

    # if file already exists (maybe from previous runs), reuse
    if os.path.exists(save_path):
        print('already have', save_name)
        mapping[url] = save_name
        continue

    # attempt download
    try:
        req = Request(url, headers=hdr)
        with urlopen(req, timeout=30) as resp:
            content = resp.read()
            # write
            with open(save_path, 'wb') as wf:
                wf.write(content)
        print('downloaded', url, '->', save_name)
        mapping[url] = save_name
    except Exception as e:
        print('download failed for', url, e)
        # fallback: if attachments contains parsed_name exactly, map to it
        candidate = None
        for fn in os.listdir(ATT_DIR):
            if fn == parsed_name:
                candidate = fn
                break
        if candidate:
            print('fallback to existing', candidate)
            mapping[url] = candidate

# Now produce converted HTML by replacing ri:url inside <ac:image> blocks

def replace_in_image_block(match):
    open_tag = match.group(1) or ''
    inner = match.group(2) or ''
    close_tag = match.group(3) or ''
    url_m = URL_RE.search(inner)
    if not url_m:
        return match.group(0)
    url = url_m.group(1).replace('&amp;', '&')
    saved = mapping.get(url)
    if not saved:
        # leave unchanged
        return match.group(0)
    # build attachment tag
    safe = htmlmod.escape(saved, quote=True)
    new_inner = URL_RE.sub(f'<ri:attachment ri:filename="{safe}"/>', inner)
    return open_tag + new_inner + close_tag

out = IMAGE_BLOCK_RE.sub(replace_in_image_block, src)

with open(OUT_HTML, 'w', encoding='utf-8') as f:
    f.write(out)

print('Wrote converted HTML to', OUT_HTML)
print('Mapping:')
for k,v in mapping.items():
    print(k, '->', v)
print('Attachments listing:')
for fn in sorted(os.listdir(ATT_DIR)):
    print(' -', fn)

