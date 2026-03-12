#!/usr/bin/env python3
"""
실제 페이지 폴더에서 gliffy 매크로 변환 테스트
"""
import os
import sys

# 모듈 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from wiki_migration.sanitizer import Sanitizer

def test_actual_page():
    """실제 0015_OPEN POC 결제 로직 파악 페이지로 테스트"""
    
    page_dir = '/Users/1004592/work/github/wiki_export_and_import/wiki_down_upload_export/pages/0015_OPEN POC 결제 로직 파악'
    page_storage = os.path.join(page_dir, 'page.storage.html')
    attachments_dir = os.path.join(page_dir, 'attachments')
    
    print("=== 실제 페이지 테스트 ===")
    print(f"페이지 디렉토리: {page_dir}")
    print(f"page.storage.html 존재: {os.path.exists(page_storage)}")
    print(f"attachments 디렉토리 존재: {os.path.exists(attachments_dir)}")
    
    if os.path.exists(attachments_dir):
        print(f"\n첨부파일 목록:")
        for fn in os.listdir(attachments_dir):
            file_path = os.path.join(attachments_dir, fn)
            if os.path.isfile(file_path):
                size = os.path.getsize(file_path)
                print(f"  - {fn} ({size} bytes)")
            else:
                print(f"  - {fn}/ (폴더)")
    
    if os.path.exists(page_storage):
        print("\n=== 변환 전 HTML (처음 500자) ===")
        with open(page_storage, 'r', encoding='utf-8') as f:
            html_content = f.read()
        print(html_content[:500])
        
        # gliffy 매크로 개수 세기
        import re
        gliffy_count = len(re.findall(r'ac:name="gliffy"', html_content, re.IGNORECASE))
        print(f"\n발견된 Gliffy 매크로 개수: {gliffy_count}")
        
        # 변환 수행
        print("\n=== Gliffy 매크로 변환 중... ===")
        result = Sanitizer.sanitize_gliffy_macros(html_content, attachments_dir)
        
        # 변환 결과 확인
        print("\n=== 변환 후 검증 ===")
        converted_count = len(re.findall(r'<ac:image>', result, re.IGNORECASE))
        fallback_count = len(re.findall(r'gliffy-macro-fallback', result))
        
        print(f"<ac:image> 태그로 변환된 매크로: {converted_count}")
        print(f"Fallback 메시지로 표시된 매크로: {fallback_count}")
        
        # 결과 출력
        print("\n=== 변환 결과 (gliffy 부분만) ===")
        lines = result.split('\n')
        for i, line in enumerate(lines):
            if 'gliffy' in line.lower() or 'ac:image' in line.lower():
                # 주변 3줄 출력
                start = max(0, i - 1)
                end = min(len(lines), i + 2)
                for j in range(start, end):
                    print(f"{j}: {lines[j]}")
                print()
        
        # 파일로 저장
        output_file = '/Users/1004592/work/github/wiki_export_and_import/test_output_gliffy.html'
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(result)
        print(f"\n✅ 변환 결과 저장: {output_file}")

if __name__ == '__main__':
    test_actual_page()

