#!/usr/bin/env bash
# upload-to-confluence.sh
# 사용법: bash upload-to-confluence.sh
# 필요: curl, jq, python3
# 파일 gradle-to-skplanet-nexus-migration-confluence.xml 이 스크립트와 동일한 경로에 존재해야 함
#PYTHONUNBUFFERED=1;N_USER=1004592;N_PASS=yosk0625!@

set -euo pipefail

# ====== 설정 (사용자 환경에 맞게 수정) ======
BASE_URL="https://wiki.skplanet.com"        # Confluence 기본 URL (ex: https://wiki.skplanet.com)
PAGE_ID="749243619"                         # 주신 pageId
SPACE_KEY="~1004592"                        # 주신 space_key
TITLE="11번가 Gradle 프로젝트의 라이브러리 SKPlanet Nexus로 마이그레이션하기"

# 인증 (절대 파일/스크린 캡처 등으로 노출 금지)
# Confluence Cloud: 이메일:API_TOKEN 형태 사용
# Confluence Server: username:password 또는 username:APIToken(서버 설정에 따라)
# 요청에 따라 사용자명과 토큰을 하드코딩합니다. 보안상 권장되지 않으므로 사용 후 파일을 안전하게 처리하세요.
CONFLUENCE_USER="1004592"
CONFLUENCE_TOKEN='yosk0625!@'
echo "[WARN] 스크립트에 하드코딩된 인증정보를 사용합니다. 파일 노출에 주의하세요."

# 업로드할 스토리지 포맷 파일
SOURCE_FILE="gradle-to-skplanet-nexus-migration-confluence.xml"
if [ ! -f "$SOURCE_FILE" ]; then
  echo "[ERROR] 파일 없음: $SOURCE_FILE"
  exit 1
fi
# =============================================

# 1) 현재 페이지 버전 조회
echo "[INFO] 현재 페이지 버전 확인..."
CURR_JSON=$(curl -s -u "${CONFLUENCE_USER}:${CONFLUENCE_TOKEN}" \
  "${BASE_URL}/rest/api/content/${PAGE_ID}?expand=version")

if [ -z "$CURR_JSON" ]; then
  echo "[ERROR] 페이지 조회 실패. URL/인증을 확인하세요."
  exit 1
fi

CUR_VER=$(echo "$CURR_JSON" | jq -r '.version.number // empty')
if [ -z "$CUR_VER" ]; then
  echo "[ERROR] 현재 버전 정보를 읽지 못했습니다. 출력:"
  echo "$CURR_JSON" | jq .
  exit 1
fi
NEW_VER=$((CUR_VER + 1))
echo "[INFO] 현재 버전: $CUR_VER  -> 업데이트할 버전: $NEW_VER"

# 2) body(스토리지 XML) 읽기
BODY_CONTENT=$(cat "$SOURCE_FILE")

# 3) JSON payload 생성 및 PUT 전송 (jq로 JSON 생성 — python 바이너리 문제 회피)
echo "[INFO] 페이지 업데이트 중..."
# jq의 --rawfile로 원문(body)을 읽어 안전하게 JSON에 포함합니다.
jq -Rn --arg id "$PAGE_ID" --arg title "$TITLE" --arg space "$SPACE_KEY" --arg ver "$NEW_VER" --rawfile body "$SOURCE_FILE" '
  ($ver | tonumber) as $v |
  {
    id: $id,
    type: "page",
    title: $title,
    space: { key: $space },
    version: { number: $v },
    body: { storage: { value: $body, representation: "storage" } }
  }
' >/tmp/confluence_payload.json

# 위에서 생성된 /tmp/confluence_payload.json 을 사용하여 PUT 요청
HTTP_RESULT=$(curl -s -o /tmp/confluence_response.json -w "%{http_code}" \
  -u "${CONFLUENCE_USER}:${CONFLUENCE_TOKEN}" \
  -X PUT \
  -H "Content-Type: application/json" \
  --data-binary @/tmp/confluence_payload.json \
  "${BASE_URL}/rest/api/content/${PAGE_ID}")

if [ "$HTTP_RESULT" = "200" ]; then
  echo "[OK] 페이지 업데이트 성공 (HTTP 200)"
  echo "응답 요약:"
  jq -r '.id, .title, .version.number' /tmp/confluence_response.json
  echo "페이지 링크: ${BASE_URL}/pages/viewpage.action?pageId=${PAGE_ID}"
  exit 0
else
  echo "[ERROR] 업데이트 실패. HTTP 상태: $HTTP_RESULT"
  echo "서버 응답:"
  cat /tmp/confluence_response.json | jq .
  exit 1
fi
