#!/usr/bin/env python3
"""
매칭 로직 디버그
"""
import os
import re

page_dir = '/Users/1004592/work/github/wiki_export_and_import/wiki_down_upload_export/pages/0015_OPEN POC 결제 로직 파악'
attachments_dir = os.path.join(page_dir, 'attachments')

# 두번째 매크로 파라미터
display_name = "Open poc 결제 로직"
macro_id = "6d79ec36-eceb-41ec-96ee-1ddc4d80ae06"

print("=== 매칭 로직 디버그 ===")
print(f"검색할 display_name: {display_name}")
print(f"검색할 macro_id: {macro_id}")
print(f"\nattachments_dir 내용:")

files = os.listdir(attachments_dir)
image_exts = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp'}

for fn in files:
    file_path = os.path.join(attachments_dir, fn)
    is_dir = os.path.isdir(file_path)
    print(f"  - {fn} {'(폴더)' if is_dir else ''}")

print(f"\n=== 단계별 매칭 테스트 ===")
lower_to_actual = {fn.lower(): fn for fn in files}

# 1단계
print("\n1단계: displayName 정확 일치 (확장자 포함)")
display_lower = display_name.lower()
if display_lower in lower_to_actual:
    actual = lower_to_actual[display_lower]
    print(f"  ✓ 발견: {actual}")
    if any(actual.lower().endswith(ext) for ext in image_exts):
        print(f"  ✓ 이미지 확장자 확인됨")
    else:
        print(f"  ✗ 이미지 확장자 아님 (폴더임)")
else:
    print(f"  ✗ '{display_lower}' 일치하는 파일 없음")

# 2단계
print("\n2단계: displayName + 확장자 조합")
for ext in image_exts:
    key = (display_name + ext).lower()
    if key in lower_to_actual:
        actual = lower_to_actual[key]
        print(f"  ✓ 발견: {key} → {actual}")

# 4단계 (부분 매칭)
print("\n4단계: displayName 부분 매칭")
display_lower = display_name.lower()
found = False
for fn in files:
    if display_lower in fn.lower() and any(fn.lower().endswith(ext) for ext in image_exts):
        print(f"  ✓ 발견: {fn}")
        found = True

if not found:
    print(f"  ✗ 부분 매칭되는 이미지 없음")

print("\n=== 수정 필요 ===")
print("display_name 대소문자 구분이 문제인 것 같음")
print(f"expected: 'Open poc 결제 로직' (입력값)")
print(f"실제파일: 'Open poc 결제 로직.png'")
print(f"lower_to_actual에 있는 키들:")
for key in sorted(lower_to_actual.keys()):
    print(f"  - '{key}' → '{lower_to_actual[key]}'")

