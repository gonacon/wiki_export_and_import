#!/usr/bin/env python3
"""
Gliffy 매크로 변환 테스트
"""
import os
import sys
import tempfile
import shutil

# 모듈 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from wiki_migration.sanitizer import Sanitizer

def test_gliffy_conversion():
    """실제 HTML과 attachments로 gliffy 변환 테스트"""
    
    # 테스트 HTML (실제 page.storage.html에서 발췌)
    html_content = '''<p>결제 수단 정리</p>
<p>
    <ac:structured-macro ac:name="gliffy" ac:schema-version="1" ac:macro-id="024952f8-33c6-4c3e-8850-feab5a7b66fd">
        <ac:parameter ac:name="macroId">52812b7b-2976-44f0-bee9-05b164dd9275</ac:parameter>
        <ac:parameter ac:name="name">ㅇㅇ</ac:parameter>
        <ac:parameter ac:name="pagePin">1</ac:parameter>
    </ac:structured-macro>
</p>
<p>
    <ac:structured-macro ac:name="gliffy" ac:schema-version="1" ac:macro-id="7e57377a-44ae-4c9e-acb5-be6e9dc429ae">
        <ac:parameter ac:name="macroId">6d79ec36-eceb-41ec-96ee-1ddc4d80ae06</ac:parameter>
        <ac:parameter ac:name="displayName">Open poc 결제 로직</ac:parameter>
        <ac:parameter ac:name="name">Open poc 결제 로직</ac:parameter>
        <ac:parameter ac:name="pagePin">2</ac:parameter>
    </ac:structured-macro>
</p>'''
    
    # 임시 디렉토리에 테스트 첨부파일 생성
    with tempfile.TemporaryDirectory() as tmpdir:
        # 테스트 이미지 파일 생성
        open(os.path.join(tmpdir, 'ㅇㅇ.png'), 'w').close()
        open(os.path.join(tmpdir, 'Open poc 결제 로직.png'), 'w').close()
        
        print("=== 테스트 환경 ===")
        print(f"임시 디렉토리: {tmpdir}")
        print(f"첨부파일 목록:")
        for fn in os.listdir(tmpdir):
            print(f"  - {fn}")
        
        print("\n=== 입력 HTML ===")
        print(html_content[:500] + "...")
        
        # Gliffy 매크로 변환
        result = Sanitizer.sanitize_gliffy_macros(html_content, tmpdir)
        
        print("\n=== 변환 결과 ===")
        print(result)
        
        # 검증
        print("\n=== 검증 ===")
        if '<ac:image>' in result:
            print("✅ <ac:image> 태그 생성됨")
        else:
            print("❌ <ac:image> 태그 생성 실패")
        
        if 'ㅇㅇ.png' in result:
            print("✅ 첫번째 이미지(ㅇㅇ.png) 매칭됨")
        else:
            print("❌ 첫번째 이미지 매칭 실패")
        
        if 'Open poc 결제 로직.png' in result:
            print("✅ 두번째 이미지(Open poc 결제 로직.png) 매칭됨")
        else:
            print("❌ 두번째 이미지 매칭 실패")

if __name__ == '__main__':
    test_gliffy_conversion()

