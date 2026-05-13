# python

Confluence 위키 마이그레이션 및 스크립트 저장소.

이 저장소에는 Confluence 페이지를 내보내고 가져오고,
첨부 파일을 관리하고, Gliffy 다이어그램을 처리하는 스크립트가 포함되어 있습니다.

# 목적

이 저장소의 핵심 스크립트는 Confluence 위키를 다른 버전의 위키로 마이그레이션하는 도구입니다.
특히 본 스크립트는 "export: Confluence Server 8.5"에서 데이터를 내보내고,
"import: Confluence 7.19" 환경으로 올리는 처리를 지원하도록 설계되었습니다.

# 사용법 요약

- 내보내기(export): 기존(8.5) 위키에서 페이지와 첨부파일을 로컬로 저장합니다.
- 가져오기(import): 로컬로 저장된 페이지와 첨부파일을 새 위키(7.19)로 업로드합니다.

자세한 사용법과 옵션은 `src/wiki_export_and_import.py` 파일의 상단 도움말 및 인터랙티브 메뉴를 참고하세요.

# 주의

- `wiki_down_upload_export/` 폴더는 기본적으로 `.gitignore`에 포함되어 있어 버전 관리에서 제외됩니다(크기가 클 수 있음). 포함하려면 `.gitignore`에서 해당 항목을 제거하고 Git LFS 사용을 권장합니다.

사용.

- 주요 마이그레이션 도구는 'src/wiki_export_and_import.py'를 참조하세요.

메모들

- 'wiki_down_upload_export/'는 기본적으로 버전 관리에서 제외됩니다(크다).
포함하려면 '.gitignore'에서 제거하고 대용량 파일에 Git LFS를 사용하는 것을 고려하세요.


# 1) 실행 중인 src/run.py의 PID(여러개일 수 있음)
pgrep -af src/run.py        # PID와 커맨드 라인 출력 (권장)
ps aux | grep [d]own_up.py  # ps+grep 방식 (자기 자신 grep 제외)

# 2) 지금 실행하고 PID 바로 얻기 (백그라운드)
python src/run.py & echo $!                 # 즉시 PID 출력
nohup python src/run.py > out.log 2>&1 & echo $!  # 로그 남기며 백그라운드 실행

# 3) (참고) 소스 수정 없이 프로세스 전체 일시정지/재개
kill -STOP <pid>   # 일시정지
kill -CONT <pid>   # 재개
s

737066549 신규 위키 기프티콘개발팀 pageId
728909587 여정근 위키 pageId

[//]: # (폴더 구조 변경 후 실행 방법)
export N_USER="1004592"
export N_PASS='비밀번호'
source .venv/bin/activate
export PYTHONPATH="src"
python -u -m wiki_migration.run
