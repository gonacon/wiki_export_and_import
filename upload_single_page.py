#!/usr/bin/env python3
"""
2096_비즈콘 Business Process Flow (old_id: 371008643) 단독 업로드 스크립트
부모 페이지 ID: 761314269
"""
import sys
import os

# src 모듈 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from wiki_migration.config import (
    NEW_BASE, NEW_USER, NEW_PASS, new_session, login, NEW_SPACE
)
from wiki_migration.importer import import_all
from wiki_migration.run import read_credentials_file

if __name__ == '__main__':
    target_page_id = '371008643'
    target_parent_id = '761314269'  # https://wiki.skplanet.com/pages/viewpage.action?pageId=761314269
    
    print("=" * 60)
    print(f"🚀 페이지 ID [{target_page_id}] (2096_비즈콘 Business Process Flow) 단독 업로드")
    print(f"타깃 Confluence: {NEW_BASE}")
    print(f"타깃 Space: {NEW_SPACE}")
    print(f"부모 Page ID: {target_parent_id}")
    print("=" * 60)

    # 1. credentials.txt 자동 읽기
    user = NEW_USER
    pwd = NEW_PASS

    if not (user and pwd):
        cred_path = './credentials.txt'
        if os.path.exists(cred_path):
            file_user, file_pwd = read_credentials_file(cred_path)
            if file_user and file_pwd:
                user, pwd = file_user, file_pwd

    if not (user and pwd):
        print("❌ credentials.txt 에서 로그인 정보를 읽지 못했습니다.")
        sys.exit(1)

    print(f"🔐 로그인 시도 (계정: {user})...")
    try:
        login(new_session, NEW_BASE, user, pwd)
        print("✅ 로그인 성공!")
    except Exception as e:
        print(f"❌ 로그인 실패: {e}")
        sys.exit(1)

    print(f"📤 페이지 ID [{target_page_id}] 업로드를 진행합니다...\n")

    # 2. 단독 페이지 import (부모 ID 761314269 지정)
    import_all(force_update=True, root_page_id=target_page_id, target_parent_id=target_parent_id)
    print("\n✨ 단독 업로드 프로세스 완료!")
