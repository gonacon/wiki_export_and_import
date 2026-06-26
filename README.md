# Wiki Export and Import

Confluence 위키 마이그레이션 및 스크립트 저장소.

이 저장소에는 Confluence 페이지를보내고 가져오고,
첨부 파일을 관리하고, Gliffy 다이어그램을 처리하는 스크립트가 포함되어 있습니다.

# 목적

이 저장소의 핵심 스크립트는 Confluence 위키를 다른 버전의 위키로 마이그레이션하는 도구입니다.
특히 본 스크립트는 "export: Confluence Server 8.5"에서 데이터를보내고,
"import: Confluence 7.19" 환경으로 올리는 처리를 지원하도록 설계되었습니다.

# 사용법 요약
-보내기(export): 기존(8.5) 위키에서 페이지와 첨부파일을 로컬로 저장합니다.
-보내기(export): 기존(8.5) 위키에서 페이지와 첨부파일을 로컬로 저장합니다.
- 가져오기(import): 로컬로 저장된 페이지와 첨부파일을 새 위키(7.19)로 업로드합니다.

## 실행

권장 진입점은 `src/wiki_migration/run.py`입니다. 저장소 루트에서 인자 없이 실행하면 대화형 모드로 동작합니다.

```bash
source .venv/bin/activate
cd /path/to/wiki_export_and_import
python3 -m src.wiki_migration.run
```

대안 (동일 저장소 루트에서):

```bash
export PYTHONPATH=src
python3 -m wiki_migration.run
```

비대화형 export 예시:

```bash
python3 -m src.wiki_migration.run export --page-id 343146642 --workers 10
```

주요 환경변수:

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `EXPORT_DIR` | export 결과 디렉터리 | `./wiki_down_upload_export` |
| `REQUEST_TIMEOUT` | REST API/첨부파일 요청 타임아웃(초) | `30` |
| `MAX_WORKERS` | 병렬 워커 수 | `8` |
| `OLD_BASE` | 기존 wiki URL | `https://wiki.11stcorp.com` |
| `NEW_BASE` | 신규 wiki URL | `https://wiki.skplanet.com` |
| `SPACE` | export 대상 스페이스 키 | `GFTCDEV` |
| `NEW_SPACE` | import 대상 스페이스 키 | `~1004592` |
| `O_USER`, `O_PASS` | 기존 wiki 계정 | 없음 |
| `N_USER`, `N_PASS` | 신규 wiki 계정 | 없음 |

레거시 단일 파일 `src/wiki_export_and_import.py`도 남아 있지만, 신규 작업은 `src/wiki_migration` 패키지를 사용하세요.

## Export 결과 확인

기본 export 결과는 `wiki_down_upload_export/` 아래에 생성됩니다.

| 파일/폴더 | 설명 |
|-----------|------|
| `pages/` | 페이지별 HTML, Markdown, 첨부파일 |
| `resume_state.json` | 성공한 페이지 ID (`downloaded`) 등 재개 상태 |
| `migrate.log` | 실행 전체 로그 (첨부파일/이미지 부분 실패 포함) |
| `failed_pages.json` | **페이지 단위 export 실패** 시에만 생성 |
| `failed_uploads.json` | import 실패 시 생성 (export와는 별도) |

페이지 본문 export가 모두 성공하면 `failed_pages.json`은 생성되지 않습니다.
이 경우에도 첨부파일·URL 이미지 다운로드는 개별적으로 실패할 수 있으며, 이 내역은 `migrate.log`에만 남습니다.

빠른 확인 예시:

```bash
# 페이지 export 완료 여부
grep "Export 완료" wiki_down_upload_export/migrate.log

# 성공한 페이지 수
python3 - <<'PY'
import json
print(len(json.load(open("wiki_down_upload_export/resume_state.json"))["downloaded"]))
PY

# 첨부파일/이미지 부분 실패 건수
grep -c "첨부파일 다운로드 실패" wiki_down_upload_export/migrate.log
grep -c "URL 이미지 다운로드 실패" wiki_down_upload_export/migrate.log
```

## 실패 재시도 동작

| 구분 | 완료 후 자동 재시도 | 재실행 시 동작 |
|------|---------------------|----------------|
| Export (페이지) | 없음 | `resume_state.json`의 `downloaded`에 없는 페이지만 처리 |
| Import | 없음 | `resume_state.json`의 `uploaded`에 없는 페이지만 처리 |
| Gliffy 썸네일 | 없음 | `retry_failed_gliffy()` 함수는 있으나 CLI(`retry-gliffy`)는 미연결 |

주의:

- Export를 다시 시작할 때 기존 `pages/` 폴더가 있으면 백업 후 `resume_state.json`도 함께 이동하므로, **실패 페이지만 이어서 export하기 어렵습니다.**
- Import는 같은 export 결과로 다시 실행하면 **성공한 페이지는 건너뛰고 실패분만 재시도**합니다.
- 첨부파일/이미지 부분 실패는 `failed_pages.json`에 남지 않습니다. `migrate.log` 또는 아래 리포트 스크립트로 확인하세요.

# 주의

- `wiki_down_upload_export/` 폴더는 기본적으로 `.gitignore`에 포함되어 있어 버전 관리에서 제외됩니다(크기가 클 수 있음). 포함하려면 `.gitignore`에서 해당 항목을 제거하고 Git LFS 사용을 권장합니다.
- `credentials.txt` 등 자격증명 파일은 `.gitignore`에 포함되어 있으며, 커밋하지 마세요.

# 운영 메모

## 실행 중인 프로세스 확인

```bash
pgrep -af wiki_migration.run   # PID와 커맨드 라인 출력 (권장)
```

백그라운드 실행 예시:

```bash
nohup python3 -m src.wiki_migration.run > out.log 2>&1 & echo $!
```

프로세스 일시정지/재개:

```bash
kill -STOP <pid>   # 일시정지
kill -CONT <pid>   # 재개
```

## 위키 pageId 참고

- `737066549` 신규 위키 기프티콘개발팀 pageId
- `728909587` 여정근 위키 pageId

## 환경변수 예시 (import)

```bash
export N_USER="1004592"
export N_PASS='비밀번호'
source .venv/bin/activate
python3 -m src.wiki_migration.run
```

## Scripts: Reports

리포트 관련 스크립트는 `scripts/reports/` 아래로 정리되어 있습니다. Export(보내기) 실패 리포트 사용 예시는 아래와 같습니다.

- 빠른 실행(권장):

```bash
python3 scripts/reports/export/generate_failed_report.py --top 200 --out wiki_down_upload_export/failed_report.html
```

- 통합 CLI:

```bash
python3 scripts/failures.py export report --top 200 --out wiki_down_upload_export/failed_report.html
```

`generate_failed_report.py`는 **페이지 단위 실패(`failed_pages.json`)뿐 아니라 `migrate.log`의 첨부파일/이미지 다운로드 실패**도 집계할 수 있습니다. 페이지 export는 성공했지만 일부 리소스만 실패한 경우에도 리포트 생성을 권장합니다.

주의: `aggregate_log_failures.py`는 `backups/` 아래 **가장 최근 백업의 `migrate.log`를 우선** 읽습니다. 백업이 없을 때만 `EXPORT_DIR/migrate.log`를 사용합니다. export 직후 리포트를 만들 때는 현재 로그가 아닌 이전 백업 로그를 읽을 수 있으니, 필요하면 백업 폴더를 확인하세요.

통합 실행 (한 번에 집계 → 수집 → top CSV → 리포트 생성)

`generate_failed_report.py`는 단일 진입점으로 동작하도록 확장되어, 필요한 경우 로그 집계(`aggregate`), 실패 페이지 수집(`collect`), 상위 상세 CSV(`top`)를 자동으로 실행한 뒤 HTML 리포트를 생성할 수 있습니다.

예시:

1) 자동으로 부족한 입력을 채우고 리포트 생성(권장):

```bash
python3 scripts/reports/export/generate_failed_report.py --top 200 --out wiki_down_upload_export/failed_report.html
```

2) 강제로 전체 파이프라인 실행 (aggregate, collect, top 모두 실행):

```bash
python3 scripts/reports/export/generate_failed_report.py --run-all --top 500 --out wiki_down_upload_export/failed_report.html
```

3) aggregate/collect 만 실행하고 리포트는 건너뛰려면(개발용):

```bash
python3 scripts/reports/export/aggregate_log_failures.py
python3 scripts/reports/export/collect_failed_pages.py
```

개별 단계 스크립트:

- `scripts/reports/export/aggregate_log_failures.py`
- `scripts/reports/export/collect_failed_pages.py`
- `scripts/reports/export/show_top_failures.py`

과거 최상위 경로(`scripts/generate_failed_report.py`, `scripts/aggregate_log_failures.py` 등)는 제거되었습니다. 자동화(크론/CI)에서는 위 `scripts/reports/export/` 또는 `scripts/failures.py` 경로를 사용하세요.
