# run.py - 대화형 입력 버전

"""
Interactive CLI wrapper for Confluence Wiki Migration Tool
"""

from .config import (
    OLD_BASE, NEW_BASE, OLD_USER, OLD_PASS, NEW_USER, NEW_PASS,
    SPACE, NEW_SPACE, EXPORT_DIR, NEW_PARENT_PAGE_ID, logger
)
from .exporter import export_all
from .importer import import_all
from .config import old_session, new_session
import argparse
import sys


def get_user_input(prompt, default=None, required=False):
    """사용자 입력을 받는 헬퍼 함수"""
    if default:
        prompt = f"{prompt} [기본값: {default}]"
    prompt += ": "

    while True:
        user_input = input(prompt).strip()

        if user_input:
            return user_input
        elif default is not None:
            return default
        elif not required:
            return None
        else:
            print("필수 입력 항목입니다. 다시 입력해주세요.")


def get_yes_no(prompt, default=False):
    """Yes/No 질문"""
    default_text = "Y/n" if default else "y/N"
    user_input = input(f"{prompt} [{default_text}]: ").strip().lower()

    if not user_input:
        return default
    return user_input in ['y', 'yes', '예']


def interactive_mode():
    """대화형 모드로 실행"""
    print("=" * 60)
    print("Confluence Wiki Migration Tool - 대화형 모드")
    print("=" * 60)
    print()

    # 1. 모드 선택
    print("작업 모드를 선택하세요:")
    print("  1) export  - 기존 wiki에서 페이지 다운로드")
    print("  2) import  - 새 wiki로 페이지 업로드")
    print("  3) migrate - export + import 한번에 실행")
    print()

    while True:
        mode_input = input("선택 [1-3]: ").strip()
        if mode_input == '1':
            mode = 'export'
            break
        elif mode_input == '2':
            mode = 'import'
            break
        elif mode_input == '3':
            mode = 'migrate'
            break
        else:
            print("1, 2, 3 중 하나를 선택해주세요.")

    print(f"\n선택된 모드: {mode}")
    print()

    # 2. 페이지 ID 설정
    if mode in ['export', 'migrate']:
        print("Export 설정")
        print("-" * 60)
        print(f"기존 Wiki: {OLD_BASE}")
        print(f"스페이스: {SPACE}")
        print()

        export_all_pages = get_yes_no("전체 페이지를 export 하시겠습니까?", default=True)

        if export_all_pages:
            root_page_id = None
            print("→ 전체 페이지를 export 합니다.")
        else:
            root_page_id = get_user_input(
                "루트 페이지 ID를 입력하세요 (이 페이지와 하위 페이지만 export)",
                required=True
            )
            print(f"→ 페이지 {root_page_id}와 하위 페이지를 export 합니다.")

        inline_images_export = get_yes_no("이미지를 base64 인라인으로 변환하시겠습니까?", default=False)
        print()
    else:
        root_page_id = None
        inline_images_export = False

    # 3. Import 설정
    if mode in ['import', 'migrate']:
        print("Import 설정")
        print("-" * 60)
        print(f"새 Wiki: {NEW_BASE}")
        print(f"스페이스: {NEW_SPACE}")
        print()

        import_all_pages = get_yes_no("export된 전체 페이지를 import 하시겠습니까?", default=True)

        if import_all_pages:
            import_root_page_id = None
            print("→ 전체 페이지를 import 합니다.")
        else:
            import_root_page_id = get_user_input(
                "import할 루트 페이지 ID를 입력하세요 (기존 wiki의 페이지 ID)",
                required=True
            )
            print(f"→ 페이지 {import_root_page_id}와 하위 페이지만 import 합니다.")

        print()
        print("새 wiki에서 부모 페이지를 지정하시겠습니까?")
        print(f"  (기본값: {NEW_PARENT_PAGE_ID if NEW_PARENT_PAGE_ID else '스페이스 루트'})")

        custom_parent = get_yes_no("부모 페이지를 직접 지정하시겠습니까?", default=False)

        if custom_parent:
            target_parent_id = get_user_input(
                "부모 페이지 ID를 입력하세요 (새 wiki의 페이지 ID)",
                default=NEW_PARENT_PAGE_ID
            )
        else:
            target_parent_id = NEW_PARENT_PAGE_ID

        if target_parent_id:
            print(f"→ 부모 페이지: {target_parent_id}")
        else:
            print(f"→ 부모 페이지: 스페이스 루트")

        inline_images_import = get_yes_no("이미지를 base64 인라인으로 변환하시겠습니까?", default=False)
        force_update = get_yes_no("이미 업로드된 페이지도 다시 업로드하시겠습니까?", default=False)
        print()
    else:
        import_root_page_id = None
        target_parent_id = None
        inline_images_import = False
        force_update = False

    # 4. 확인 및 실행
    print("=" * 60)
    print("설정 확인")
    print("=" * 60)
    print(f"모드: {mode}")

    if mode in ['export', 'migrate']:
        print(f"Export - 루트 페이지: {root_page_id if root_page_id else '전체'}")
        print(f"Export - 인라인 이미지: {inline_images_export}")

    if mode in ['import', 'migrate']:
        print(f"Import - 루트 페이지: {import_root_page_id if import_root_page_id else '전체'}")
        print(f"Import - 부모 페이지: {target_parent_id if target_parent_id else '스페이스 루트'}")
        print(f"Import - 인라인 이미지: {inline_images_import}")
        print(f"Import - 강제 업데이트: {force_update}")

    print("=" * 60)
    print()

    if not get_yes_no("위 설정으로 진행하시겠습니까?", default=True):
        print("작업을 취소합니다.")
        return

    print()
    print("작업을 시작합니다...")
    print()

    # 5. 실행
    try:
        if mode == 'export':
            export_all(old_session, OLD_BASE, SPACE,
                       root_page_id=root_page_id,
                       inline_images=inline_images_export)

        elif mode == 'import':
            import_all(
                inline_images=inline_images_import,
                force_update=force_update,
                root_page_id=import_root_page_id,
                target_parent_id=target_parent_id
            )

        elif mode == 'migrate':
            # Export
            logger.info("=" * 60)
            logger.info("STEP 1: Export 시작")
            logger.info("=" * 60)
            export_all(old_session, OLD_BASE, SPACE,
                       root_page_id=root_page_id,
                       inline_images=inline_images_export)

            # Import
            logger.info("")
            logger.info("=" * 60)
            logger.info("STEP 2: Import 시작")
            logger.info("=" * 60)
            import_all(
                inline_images=inline_images_import,
                force_update=force_update,
                root_page_id=import_root_page_id,
                target_parent_id=target_parent_id
            )

        print()
        print("=" * 60)
        print("작업이 완료되었습니다!")
        print("=" * 60)

    except Exception as e:
        logger.error(f"작업 중 오류 발생: {e}")
        print(f"\n오류: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='Confluence Wiki Migration Tool',
        epilog='인자 없이 실행하면 대화형 모드로 실행됩니다.'
    )

    # 선택적 인자들
    parser.add_argument('mode', nargs='?', choices=['export', 'import', 'migrate', 'retry-gliffy'],
                        help='작업 모드 (생략 시 대화형 모드)')
    parser.add_argument('--page-id', default=None,
                        help='루트 페이지 ID (export/import 대상)')
    parser.add_argument('--parent-id', default=None,
                        help='새 wiki에서 부모 페이지 ID (import 시)')
    parser.add_argument('--inline-images', action='store_true',
                        help='이미지를 base64로 인라인 변환')
    parser.add_argument('--workers', type=int, default=8,
                        help='병렬 처리 워커 수')
    parser.add_argument('--force-update', action='store_true',
                        help='이미 업로드된 페이지도 재업로드')
    parser.add_argument('--non-interactive', action='store_true',
                        help='비대화형 모드 (명령줄 인자만 사용)')

    args = parser.parse_args()

    # 대화형 모드 vs 명령줄 모드
    if args.mode is None and not args.non_interactive:
        # 모드가 지정되지 않으면 대화형 모드
        interactive_mode()
    elif args.mode:
        # 명령줄 모드
        if args.mode == 'export':
            export_all(old_session, OLD_BASE, SPACE,
                       root_page_id=args.page_id,
                       inline_images=args.inline_images)

        elif args.mode == 'import':
            import_all(
                inline_images=args.inline_images,
                force_update=args.force_update,
                root_page_id=args.page_id,
                target_parent_id=args.parent_id
            )

        elif args.mode == 'migrate':
            export_all(old_session, OLD_BASE, SPACE,
                       root_page_id=args.page_id,
                       inline_images=args.inline_images)
            import_all(
                inline_images=args.inline_images,
                force_update=args.force_update,
                root_page_id=args.page_id,
                target_parent_id=args.parent_id
            )

        elif args.mode == 'retry-gliffy':
            print('retry-gliffy not implemented in refactor wrapper')
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
