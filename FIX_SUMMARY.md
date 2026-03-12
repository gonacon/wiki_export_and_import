# Gliffy 매크로 변환 수정 - 간략 정리

## 문제
- Confluence 8.5 → 7.19 import 시 gliffy 매크로가 이미지로 변환 안됨
- 특히 한글 파일명일 경우 매칭 실패

## 원인
**유니코드 정규화(Unicode Normalization) 불일치**

macOS 파일 시스템은 파일명을 자동으로 **NFD 형식**(분해된 한글)으로 저장하지만,
HTML의 한글은 **NFC 형식**(조합된 한글)으로 되어 있어 문자열 비교 실패.

예: `'결제'` 
- NFC: 2글자 (조합된 형태)
- NFD: 8글자 (결 제로 분해)

## 해결
`src/wiki_migration/sanitizer.py` 수정:
1. `unicodedata` 모듈 추가
2. 파일명 비교 시 모두 NFC로 정규화
3. 이미지 파일만 필터링 (폴더 제외)

## 수정 파일
- `/Users/1004592/work/github/wiki_export_and_import/src/wiki_migration/sanitizer.py`

## 테스트 통과 ✅
- 단위 테스트: 두 매크로 모두 정상 변환
- 실제 페이지: 2/2 매크로 변환 성공 (0% fallback)

