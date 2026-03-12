#!/usr/bin/env python3
"""
매칭 로직 상세 디버그
"""
import os
import sys
import logging

# 로깅 설정
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')
logger = logging.getLogger('wiki_migrate')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# sanitizer 코드를 직접 테스트
import re
import html

page_dir = '/Users/1004592/work/github/wiki_export_and_import/wiki_down_upload_export/pages/0015_OPEN POC 결제 로직 파악'
attachments_dir = os.path.join(page_dir, 'attachments')

# 두번째 매크로의 내용
gliffy_html = '''<ac:structured-macro ac:name="gliffy" ac:schema-version="1" ac:macro-id="7e57377a-44ae-4c9e-acb5-be6e9dc429ae">
        <ac:parameter ac:name="macroId">6d79ec36-eceb-41ec-96ee-1ddc4d80ae06</ac:parameter>
        <ac:parameter ac:name="displayName">Open poc 결제 로직</ac:parameter>
        <ac:parameter ac:name="name">Open poc 결제 로직</ac:parameter>
        <ac:parameter ac:name="pagePin">2</ac:parameter>
    </ac:structured-macro>'''

PARAM_RE = re.compile(r'<ac:parameter\s+ac:name="([^"]+)"\s*>(.*?)</ac:parameter>', re.DOTALL | re.IGNORECASE)

def _extract(macro_html):
    return {m.group(1).strip(): m.group(2).strip() for m in PARAM_RE.finditer(macro_html)}

params = _extract(gliffy_html)
print("=== 추출된 파라미터 ===")
for key, value in params.items():
    print(f"  {key}: '{value}'")

display_name = params.get('displayName') or params.get('name') or ''
print(f"\n최종 display_name: '{display_name}'")

# 매칭 로직 실행
print("\n=== 파일 매칭 로직 실행 ===")

files = os.listdir(attachments_dir)
image_exts = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp'}

# 이미지 파일만 필터링
image_files = [fn for fn in files if any(fn.lower().endswith(ext) for ext in image_exts)]
print(f"\n이미지 파일 목록 ({len(image_files)}개):")
for fn in image_files:
    print(f"  - {fn}")

# 파일명을 소문자로 매핑
lower_to_actual = {fn.lower(): fn for fn in image_files}
print(f"\nlower_to_actual 맵:")
for key, value in lower_to_actual.items():
    print(f"  '{key}' → '{value}'")

# 1단계: displayName + 이미지 확장자
print(f"\n=== 1단계: displayName + 확장자 ===")
display_lower = display_name.lower()
print(f"display_lower: '{display_lower}'")
for ext in image_exts:
    key = display_lower + ext
    print(f"  테스트 '{key}':", end=" ")
    if key in lower_to_actual:
        print(f"✓ 매칭 → {lower_to_actual[key]}")
    else:
        print("✗")

# 2단계: displayName 정확 일치
print(f"\n=== 2단계: displayName 정확 일치 ===")
if display_lower in lower_to_actual:
    print(f"  ✓ '{display_lower}' 매칭 → {lower_to_actual[display_lower]}")
else:
    print(f"  ✗ '{display_lower}' 미매칭")

# 4단계: 부분 매칭
print(f"\n=== 4단계: 부분 매칭 ===")
found = False
for fn in image_files:
    if display_lower in fn.lower():
        print(f"  ✓ '{display_lower}' in '{fn.lower()}' → {fn}")
        found = True
        
if not found:
    print(f"  ✗ '{display_lower}' 포함하는 파일 없음")

