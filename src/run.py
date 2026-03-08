"""
Legacy wrapper that exposes the original CLI while delegating functionality
to the refactored modules: config, exporter, importer, sanitizer, utils.
The original single-file implementation is preserved as a backup at
`wiki_export_and_import.py`.
"""

from .config import OLD_BASE, NEW_BASE, OLD_USER, OLD_PASS, NEW_USER, NEW_PASS, SPACE, NEW_SPACE, EXPORT_DIR
from .exporter import export_all
from .importer import import_all
from .config import old_session, new_session
import argparse
import sys
import getpass


def ask(prompt, default=None):
    try:
        suffix = f" [{default}]" if default is not None and default != "" else ""
        val = input(f"{prompt}{suffix}: ").strip()
        if not val:
            return default
        return val
    except (KeyboardInterrupt, EOFError):
        print("\n\n👋 종료합니다.")
        sys.exit(0)


def ask_yes_no(prompt, default=False):
    hint = "Y/n" if default else "y/N"
    val = ask(f"{prompt} ({hint})", default="y" if default else "n")
    return val.lower() in ("y", "yes")


def login(session, base, user, password):
    url = f"{base}/dologin.action"
    data = {
        "os_username": user,
        "os_password": password,
        "login": "Log in",
    }
    r = session.post(url, data=data)
    if r.status_code != 200:
        print(f"로그인 실패: {base} (status={r.status_code})")
        sys.exit(1)
    print(f"로그인 성공: {base}")


def interactive_menu():
    print()
    print("=" * 55)
    print("   Confluence Wiki Migration Tool")
    print("=" * 55)
    print()
    print("  1) export      — 기존 위키 → 로컬 파일")
    print("  2) import      — 로컬 파일 → 새 위키")
    print("  3) migrate     — export + import 연속 실행")
    print("  4) retry-gliffy— 실패한 Gliffy 썸네일 재시도")
    print()

    choice = ask("작업을 선택하세요 (1/2/3/4)", default="1")
    mode_map = {"1": "export", "2": "import", "3": "migrate", "4": "retry-gliffy",
                "export": "export", "import": "import", "migrate": "migrate", "retry-gliffy": "retry-gliffy"}
    mode = mode_map.get(choice)
    if not mode:
        print(f"❌ 잘못된 선택: {choice}")
        sys.exit(1)

    # 인증 정보 입력
    global OLD_USER, OLD_PASS, NEW_USER, NEW_PASS, SPACE, NEW_SPACE, NEW_PARENT_PAGE_ID, EXPORT_DIR, MAX_WORKERS

    if mode in ("export", "migrate", "retry-gliffy"):
        env_user = OLD_USER or ""
        env_pass = OLD_PASS or ""
        if env_user and env_pass:
            print(f"  환경변수 O_USER / O_PASS 감지됨 → 자동 사용")
        else:
            cfg_user = ask("  기존 위키 아이디", default=OLD_USER or "")
            cfg_pass = getpass.getpass("  기존 위키 비밀번호: ") or OLD_PASS
            OLD_USER = cfg_user
            OLD_PASS = cfg_pass

    if mode in ("import", "migrate"):
        env_user = NEW_USER or ""
        env_pass = NEW_PASS or ""
        if env_user and env_pass:
            print(f"  환경변수 N_USER / N_PASS 감지됨 → 자동 사용")
        else:
            cfg_user = ask("  새 위키 아이디", default=NEW_USER or "")
            cfg_pass = getpass.getpass("  새 위키 비밀번호: ") or NEW_PASS
            NEW_USER = cfg_user
            NEW_PASS = cfg_pass

    # 기본 설정
    if mode in ("export", "migrate"):
        SPACE = ask("  기존 위키 Space Key", default=SPACE)
    if mode in ("import", "migrate"):
        NEW_SPACE = ask("  새 위키 Space Key", default=NEW_SPACE)
        parent_input = ask("  새 위키 부모 페이지 ID (없으면 Space 최상위)", default=None)
        NEW_PARENT_PAGE_ID = parent_input if parent_input else None

    EXPORT_DIR = ask("  로컬 저장 경로", default=EXPORT_DIR)

    page_id = None
    if mode in ("export", "migrate"):
        use_page = ask_yes_no("  특정 페이지와 하위 페이지만 가져오시겠어요?", default=False)
        if use_page:
            page_id = ask("  페이지 ID 입력", default=None)
            if not page_id:
                print("❌ 페이지 ID를 입력해야 합니다.")
                sys.exit(1)

    inline_images = False
    if mode in ("export", "migrate"):
        inline_images = ask_yes_no("  이미지를 base64 inline으로 변환할까요?", default=False)

    workers_str = ask("  병렬 다운로드 스레드 수", default=str(8))
    try:
        MAX_WORKERS = int(workers_str)
    except ValueError:
        print("⚠️  숫자가 아니므로 기본값 8 사용")
        MAX_WORKERS = 8

    force_update = False
    if mode in ("import", "migrate"):
        force_update = ask_yes_no("  이미 업로드된 페이지도 강제로 업데이트할까요?", default=False)

    confirm = ask_yes_no("위 설정으로 실행할까요?", default=True)
    if not confirm:
        print("취소되었습니다.")
        sys.exit(0)

    return mode, page_id, inline_images, force_update


def main():
    # 대화형: 인자 없이 실행 시 기존 인터랙티브 메뉴 동작
    if len(sys.argv) == 1:
        mode, page_id, inline_images, force_update = interactive_menu()

        if mode == "export":
            login(old_session, OLD_BASE, OLD_USER, OLD_PASS)
            export_all(old_session, OLD_BASE, SPACE, root_page_id=page_id, inline_images=inline_images)

        elif mode == "import":
            login(new_session, NEW_BASE, NEW_USER, NEW_PASS)
            import src.importer as importer_mod
            importer_mod.config = config
            import_all(inline_images=inline_images, force_update=force_update)

        elif mode == "migrate":
            login(old_session, OLD_BASE, OLD_USER, OLD_PASS)
            login(new_session, NEW_BASE, NEW_USER, NEW_PASS)
            export_all(old_session, OLD_BASE, SPACE, root_page_id=page_id, inline_images=inline_images)
            import src.importer as importer_mod
            importer_mod.config = config
            import_all(inline_images=inline_images, force_update=force_update)

        elif mode == "retry-gliffy":
            login(old_session, OLD_BASE, OLD_USER, OLD_PASS)
            import src.io_utils as io_mod
            io_mod.retry_failed_gliffy()

        return

    # 기존 CLI 방식 (인자가 있을 경우)
    parser = argparse.ArgumentParser(
        description='Confluence Wiki Migration Tool',
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument('mode', choices=['export', 'import', 'migrate', 'retry-gliffy'])
    parser.add_argument('--page-id', default=None)
    parser.add_argument('--inline-images', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--force-update', action='store_true')

    args = parser.parse_args()

    global MAX_WORKERS
    MAX_WORKERS = args.workers

    if args.mode == 'export':
        login(old_session, OLD_BASE, OLD_USER, OLD_PASS)
        export_all(old_session, OLD_BASE, SPACE, root_page_id=args.page_id, inline_images=args.inline_images)

    elif args.mode == 'import':
        login(new_session, NEW_BASE, NEW_USER, NEW_PASS)
        import src.importer as importer_mod
        importer_mod.config = config
        import_all(inline_images=args.inline_images, force_update=args.force_update)

    elif args.mode == 'migrate':
        login(old_session, OLD_BASE, OLD_USER, OLD_PASS)
        login(new_session, NEW_BASE, NEW_USER, NEW_PASS)
        export_all(old_session, OLD_BASE, SPACE, root_page_id=args.page_id, inline_images=args.inline_images)
        import src.importer as importer_mod
        importer_mod.config = config
        import_all(inline_images=args.inline_images, force_update=args.force_update)

    elif args.mode == 'retry-gliffy':
        login(old_session, OLD_BASE, OLD_USER, OLD_PASS)
        import src.io_utils as io_mod
        io_mod.retry_failed_gliffy()


if __name__ == '__main__':
    main()
