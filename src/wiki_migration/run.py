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
import getpass
import json

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


def read_credentials_file(path):
    """간단한 자격증명 파일을 읽음.
    지원 형식:
      - JSON: {"O_USER":"user","O_PASS":"pass"} 또는 {"user":"...","password":"..."}
      - KEY=VALUE 라인 (예: O_USER=, O_PASS=)
      - 첫 줄 사용자명, 둘째 줄 비밀번호
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        logger.error(f"자격증명 파일 읽기 실패: {e} (path={path})")
        return None, None

    # JSON 시도
    try:
        data = json.loads(text)
        # 다양한 키 이름 허용
        user = data.get('O_USER') or data.get('OLD_USER') or data.get('user') or data.get('username')
        pwd = data.get('O_PASS') or data.get('OLD_PASS') or data.get('password') or data.get('pwd')
        return user, pwd
    except Exception:
        pass

    # KEY=VALUE 형식
    user = pwd = None
    for line in text.splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            k = k.strip(); v = v.strip()
            if k in ('O_USER', 'OLD_USER', 'user', 'username'):
                user = v
            if k in ('O_PASS', 'OLD_PASS', 'password', 'pwd'):
                pwd = v
    if user or pwd:
        return user, pwd

    # 마지막으로 두 줄 형식
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) >= 2:
        return lines[0].strip(), lines[1].strip()
    return None, None


def save_credentials_file(path, user, pwd):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(f"O_USER={user}\nO_PASS={pwd}\n")
        logger.info(f"자격증명 파일 저장 완료: {path}")
    except Exception as e:
        logger.warning(f"자격증명 파일 저장 실패: {e} (path={path})")


def obtain_credentials(default_user, default_pass, label='OLD'):
    """환경변수에 설정된 값이 있으면 그 값을 반환. 없으면 대화형으로 입력하거나 파일에서 로드.
    반환: (user, pass)
    """
    # 이미 값이 있으면 그대로 사용
    if default_user and default_pass:
        return default_user, default_pass

    print(f"{label} 로그인 정보가 설정되어 있지 않습니다.")
    # 먼저 파일에서 불러오기 시도
    if get_yes_no("자격증명 파일에서 로드하시겠습니까? (예: credentials.json 또는 .env)", default=True):
        path = get_user_input("파일 경로를 입력하세요", default='./credentials.txt')
        user, pwd = read_credentials_file(path)
        if user and pwd:
            print("파일에서 자격증명을 읽었습니다.")
            if get_yes_no("이 자격증명을 환경변수로 저장하시겠습니까? (파일에 다시 저장됨)", default=False):
                save_credentials_file(path, user, pwd)
            return user, pwd
        else:
            print("파일에서 자격증명을 읽지 못했습니다. 수동으로 입력합니다.")

    # 수동 입력
    user = get_user_input(f"{label} 계정 사용자명 (빈칸이면 취소)", required=False)
    if not user:
        print("로그인 정보가 제공되지 않았습니다. 로그인을 건너뜁니다.")
        return None, None
    pwd = getpass.getpass(f"{label} 계정 비밀번호: ")
    if get_yes_no("입력한 자격증명을 파일로 저장하시겠습니까?", default=False):
        path = get_user_input("저장할 파일 경로", default='./credentials.txt')
        save_credentials_file(path, user, pwd)
    return user, pwd


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
                    export_workers = int(str(workers_input))
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
            # 로그인 정보 확보: 환경변수값이 없으면 파일 또는 입력으로 받아옴
            user, pwd = obtain_credentials(OLD_USER, OLD_PASS, label='OLD')
            try:
                login(old_session, OLD_BASE, user, pwd)
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
            user, pwd = obtain_credentials(NEW_USER, NEW_PASS, label='NEW')
            try:
                login(new_session, NEW_BASE, user, pwd)
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
            user, pwd = obtain_credentials(OLD_USER, OLD_PASS, label='OLD')
            try:
                login(old_session, OLD_BASE, user, pwd)
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
            user, pwd = obtain_credentials(NEW_USER, NEW_PASS, label='NEW')
            try:
                login(new_session, NEW_BASE, user, pwd)
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
        try:
            # 이미 import된 config 모듈의 MAX_WORKERS도 갱신하여 import 모듈들이
            # CLI로 전달된 워커 수를 반영하도록 한다.
            from . import config
            config.MAX_WORKERS = args.workers
            logger.info(f"MAX_WORKERS set to {args.workers} from CLI")
        except Exception:
            # 안전하게 실패 허용: 환경변수만 설정되어 있어도 다른 실행 경로에서 동작함
            pass

    # 대화형 모드 vs 명령줄 모드
    if args.mode is None and not args.non_interactive:
        # 모드가 지정되지 않으면 대화형 모드
        interactive_mode()
    elif args.mode:
        # 명령줄 모드
        if args.mode == 'export':
            # CLI 모드: non-interactive이면 환경변수에 의존, 아니면 부족한 정보는 프롬프트로 수집
            if args.non_interactive:
                user, pwd = OLD_USER, OLD_PASS
                if not user or not pwd:
                    logger.error("비대화형 모드인데 OLD_USER/O_PASS가 설정되어 있지 않습니다.")
                    print("비대화형 모드에서는 O_USER/O_PASS 환경변수를 설정해야 합니다.")
                    sys.exit(1)
            else:
                user, pwd = (OLD_USER, OLD_PASS) if (OLD_USER and OLD_PASS) else obtain_credentials(OLD_USER, OLD_PASS, label='OLD')

            try:
                login(old_session, OLD_BASE, user, pwd)
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
            if args.non_interactive:
                user, pwd = NEW_USER, NEW_PASS
                if not user or not pwd:
                    logger.error("비대화형 모드인데 N_USER/N_PASS가 설정되어 있지 않습니다.")
                    print("비대화형 모드에서는 N_USER/N_PASS 환경변수를 설정해야 합니다.")
                    sys.exit(1)
            else:
                user, pwd = (NEW_USER, NEW_PASS) if (NEW_USER and NEW_PASS) else obtain_credentials(NEW_USER, NEW_PASS, label='NEW')

            try:
                login(new_session, NEW_BASE, user, pwd)
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
            if args.non_interactive:
                user, pwd = NEW_USER, NEW_PASS
                if not user or not pwd:
                    logger.error("비대화형 모드인데 N_USER/N_PASS가 설정되어 있지 않습니다.")
                    print("비대화형 모드에서는 N_USER/N_PASS 환경변수를 설정해야 합니다.")
                    sys.exit(1)
            else:
                user, pwd = (NEW_USER, NEW_PASS) if (NEW_USER and NEW_PASS) else obtain_credentials(NEW_USER, NEW_PASS, label='NEW')

            try:
                login(new_session, NEW_BASE, user, pwd)
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

