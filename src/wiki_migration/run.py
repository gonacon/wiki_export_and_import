# run.py - 대화형 입력 버전

"""
Interactive CLI wrapper for Confluence Wiki Migration Tool
"""
import os

from .config import (
    OLD_BASE, NEW_BASE, OLD_USER, OLD_PASS, NEW_USER, NEW_PASS,
    SPACE, NEW_SPACE, MAX_WORKERS, NEW_PARENT_PAGE_ID, logger, login
)
from .exporter import export_all
from .importer import import_all, import_all_two_pass
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


# run.py - interactive_mode() 함수 전체 교체

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

    # 2. Export 설정
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

        # ✨ 워커 수 입력 추가
        # ✨ CPU 코어 수 자동 감지
        import multiprocessing
        cpu_count = multiprocessing.cpu_count()
        recommended_workers = min(cpu_count, 16)  # 최대 16개 권장

        print()
        print(f"시스템 CPU 코어 수: {cpu_count}")
        print(f"권장 워커 수: {recommended_workers} (현재 기본값: {MAX_WORKERS})")
        custom_workers = get_yes_no("워커 수를 직접 입력하시겠습니까?", default=False)


        if custom_workers:
            while True:
                workers_input = get_user_input(
                    f"워커 수를 입력하세요 (1-32, 권장: {recommended_workers})",
                    default=str(recommended_workers)  # 권장값을 기본값으로
                )
                try:
                    export_workers = int(workers_input)
                    if export_workers < 1:
                        print("워커 수는 1 이상이어야 합니다.")
                        continue
                    if export_workers > cpu_count * 2:
                        print(f"⚠️  경고: 워커 수({export_workers})가 CPU 코어 수({cpu_count})의 2배를 초과합니다.")
                        if not get_yes_no("계속 진행하시겠습니까?", default=False):
                            continue
                    print(f"→ 워커 수: {export_workers}")
                    break
                except ValueError:
                    print("유효한 숫자를 입력해주세요.")
        else:
            export_workers = recommended_workers  # 기본값 대신 권장값 사용
            print(f"→ 워커 수: {export_workers} (권장값)")

        print()
    else:
        root_page_id = None
        inline_images_export = False
        export_workers = MAX_WORKERS

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

        # 2-Pass 옵션
        use_two_pass = get_yes_no("2-Pass Import를 사용하시겠습니까? (내부 링크 변환 개선)", default=True)
        print()
    else:
        import_root_page_id = None
        target_parent_id = None
        inline_images_import = False
        force_update = False
        use_two_pass = False

    # 4. 확인 및 실행
    print("=" * 60)
    print("설정 확인")
    print("=" * 60)
    print(f"모드: {mode}")

    if mode in ['export', 'migrate']:
        print(f"Export - 루트 페이지: {root_page_id if root_page_id else '전체'}")
        print(f"Export - 인라인 이미지: {inline_images_export}")
        print(f"Export - 워커 수: {export_workers}")  # ✨ 추가

    if mode in ['import', 'migrate']:
        print(f"Import - 루트 페이지: {import_root_page_id if import_root_page_id else '전체'}")
        print(f"Import - 부모 페이지: {target_parent_id if target_parent_id else '스페이스 루트'}")
        print(f"Import - 인라인 이미지: {inline_images_import}")
        print(f"Import - 강제 업데이트: {force_update}")
        print(f"Import - 2-Pass: {use_two_pass}")  # ✨ 추가

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
            # 로그인 후 export 실행
            try:
                login(old_session, OLD_BASE, OLD_USER, OLD_PASS)
            except Exception as e:
                logger.error(f"로그인 실패로 export 중단: {e}")
                print(f"로그인 실패: {e}")
                return
            export_all(old_session, OLD_BASE, SPACE,
                       root_page_id=root_page_id,
                       inline_images=inline_images_export,
                       workers=export_workers)  # ✨ 추가

        elif mode == 'import':
            # 로그인 후 import 실행
            try:
                login(new_session, NEW_BASE, NEW_USER, NEW_PASS)
            except Exception as e:
                logger.error(f"로그인 실패로 import 중단: {e}")
                print(f"로그인 실패: {e}")
                return
            if use_two_pass:
                logger.info("🚀 2-Pass Import 모드로 실행합니다.")
                import_all_two_pass(
                    inline_images=inline_images_import,
                    force_update=force_update,
                    root_page_id=import_root_page_id,
                    target_parent_id=target_parent_id
                )
            else:
                logger.info("1-Pass Import 모드로 실행합니다.")
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
            try:
                login(old_session, OLD_BASE, OLD_USER, OLD_PASS)
            except Exception as e:
                logger.error(f"로그인 실패로 export 중단: {e}")
                print(f"로그인 실패: {e}")
                return
            export_all(old_session, OLD_BASE, SPACE,
                       root_page_id=root_page_id,
                       inline_images=inline_images_export,
                       workers=export_workers)  # ✨ 추가

            # Import
            logger.info("")
            logger.info("=" * 60)
            logger.info("STEP 2: Import 시작")
            logger.info("=" * 60)
            try:
                login(new_session, NEW_BASE, NEW_USER, NEW_PASS)
            except Exception as e:
                logger.error(f"로그인 실패로 import 중단: {e}")
                print(f"로그인 실패: {e}")
                return

            if use_two_pass:
                logger.info("🚀 2-Pass Import 모드로 실행합니다.")
                import_all_two_pass(
                    inline_images=inline_images_import,
                    force_update=force_update,
                    root_page_id=import_root_page_id,
                    target_parent_id=target_parent_id
                )
            else:
                logger.info("1-Pass Import 모드로 실행합니다.")
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
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='Confluence Wiki Migration Tool',
        epilog='인자 없이 실행하면 대화형 모드로 실행됩니다.'
    )

    # 선택적 인자들
    parser.add_argument('mode', nargs='?', choices=['export', 'import', 'import2', 'migrate', 'retry-gliffy'],
                        help='작업 모드 (import2 = 2-Pass Import, 생략 시 대화형 모드)')
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
    parser.add_argument('--two-pass', action='store_true',
                        help='2-Pass Import 사용 (링크 변환 개선)')

    # 이제 모든 인자가 등록되었으므로 한 번만 파싱합니다.
    args = parser.parse_args()

    # --workers가 설정되면 환경변수로 전달 (기존 동작 유지)
    if getattr(args, 'workers', None) is not None:
        os.environ['MAX_WORKERS'] = str(args.workers)

    # 대화형 모드 vs 명령줄 모드
    if args.mode is None and not args.non_interactive:
        # 모드가 지정되지 않으면 대화형 모드
        interactive_mode()
    elif args.mode:
        # 명령줄 모드
        if args.mode == 'export':
            try:
                login(old_session, OLD_BASE, OLD_USER, OLD_PASS)
            except Exception as e:
                logger.error(f"로그인 실패로 export 중단: {e}")
                print(f"로그인 실패: {e}")
                sys.exit(1)
            export_all(old_session, OLD_BASE, SPACE,
                       root_page_id=args.page_id,
                       inline_images=args.inline_images,
                       workers=args.workers)

        elif args.mode == 'import' or args.mode == 'import2':
            # import2 또는 --two-pass 플래그가 있으면 2-Pass Import
            # 로그인
            try:
                login(new_session, NEW_BASE, NEW_USER, NEW_PASS)
            except Exception as e:
                logger.error(f"로그인 실패로 import 중단: {e}")
                print(f"로그인 실패: {e}")
                sys.exit(1)
            if args.mode == 'import2' or args.two_pass:
                logger.info("2-Pass Import 모드로 실행합니다.")
                import_all_two_pass(
                    inline_images=args.inline_images,
                    force_update=args.force_update,
                    root_page_id=args.page_id,
                    target_parent_id=args.parent_id
                )
            else:
                # 기존 1-Pass Import
                logger.info("1-Pass Import 모드로 실행합니다.")
                import_all(
                    inline_images=args.inline_images,
                    force_update=args.force_update,
                    root_page_id=args.page_id,
                    target_parent_id=args.parent_id
                )

        elif args.mode == 'migrate':
            export_all(old_session, OLD_BASE, SPACE,
                       root_page_id=args.page_id,
                       inline_images=args.inline_images,
                       workers=args.workers)

            # migrate도 2-Pass 옵션 지원
            try:
                login(new_session, NEW_BASE, NEW_USER, NEW_PASS)
            except Exception as e:
                logger.error(f"로그인 실패로 import 중단: {e}")
                print(f"로그인 실패: {e}")
                sys.exit(1)
            if args.two_pass:
                logger.info("2-Pass Import 모드로 실행합니다.")
                import_all_two_pass(
                    inline_images=args.inline_images,
                    force_update=args.force_update,
                    root_page_id=args.page_id,
                    target_parent_id=args.parent_id
                )
            else:
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

