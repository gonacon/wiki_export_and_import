#!/usr/bin/env python3
"""
인코딩 비교 디버그
"""
import os

page_dir = '/Users/1004592/work/github/wiki_export_and_import/wiki_down_upload_export/pages/0015_OPEN POC 결제 로직 파악'
attachments_dir = os.path.join(page_dir, 'attachments')

files = os.listdir(attachments_dir)
image_exts = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp'}
image_files = [fn for fn in files if any(fn.lower().endswith(ext) for ext in image_exts)]

print("=== 파일명 인코딩 비교 ===")
target = "Open poc 결제 로직.png"
display_name = "Open poc 결제 로직"

print(f"\n검색 대상: '{target}'")
print(f"  - repr: {repr(target)}")
print(f"  - 길이: {len(target)}")
print(f"  - bytes: {target.encode('utf-8')}")

print(f"\ndisplay_name: '{display_name}'")
print(f"  - repr: {repr(display_name)}")
print(f"  - 길이: {len(display_name)}")
print(f"  - bytes: {display_name.encode('utf-8')}")

print(f"\n실제 파일들:")
for fn in image_files:
    print(f"  '{fn}'")
    print(f"    - repr: {repr(fn)}")
    print(f"    - 길이: {len(fn)}")
    print(f"    - bytes: {fn.encode('utf-8')}")
    if fn.lower() == target.lower():
        print(f"    ✓ lower() 비교 일치")
    else:
        print(f"    ✗ lower() 비교 불일치")
        fn_lower = fn.lower()
        target_lower = target.lower()
        print(f"      fn.lower() = {repr(fn_lower)} ({len(fn_lower)})")
        print(f"      target.lower() = {repr(target_lower)} ({len(target_lower)})")
        # 문자별 비교
        print(f"      문자별 비교:")
        max_len = max(len(fn_lower), len(target_lower))
        for i in range(max_len):
            f_char = fn_lower[i] if i < len(fn_lower) else '(없음)'
            t_char = target_lower[i] if i < len(target_lower) else '(없음)'
            match = '✓' if f_char == t_char else '✗'
            print(f"        [{i}] '{f_char}' vs '{t_char}' {match}")

