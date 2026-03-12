# Gliffy 매크로 변환 - 수정사항 보고서

## 문제점
Confluence 8.5에서 export한 페이지를 7.19 버전에 import할 때, gliffy 매크로가 제대로 이미지로 변환되지 않는 문제가 발생했습니다.

### 구체적인 사례
```html
<ac:structured-macro ac:name="gliffy" ac:schema-version="1" ac:macro-id="024952f8-33c6-4c3e-8850-feab5a7b66fd">
    <ac:parameter ac:name="macroId">52812b7b-2976-44f0-bee9-05b164dd9275</ac:parameter>
    <ac:parameter ac:name="name">ㅇㅇ</ac:parameter>
    <ac:parameter ac:name="pagePin">1</ac:parameter>
</ac:structured-macro>
```

## 원인 분석

### 1. 파일 매칭 알고리즘 미흡
- attachments 폴더에 `ㅇㅇ.png` (이미지)와 `ㅇㅇ` (폴더) 모두 존재
- 폴더까지 포함한 파일명 비교로 인해 이미지 파일 필터링 실패

### 2. 유니코드 정규화(Normalization) 문제 ⚠️ **핵심**
- **HTML에서의 한글**: NFC 형식 (조합된 형태)
  - `'Open poc 결제 로직'` = 14자
- **macOS 파일 시스템**: NFD 형식 (분해된 형태)
  - `'Open poc 결제 로직'` = 24자 (각 한글이 음절별로 분해)
  
예시:
- NFC: `'결'` = 1글자 (E4 B2 B0 in UTF-8)
- NFD: `'결'` = 4글자 (E1 84 80 E1 85 A7 E1 86 AF in UTF-8)

이로 인해 단순 문자열 비교로는 매칭 불가능했습니다.

## 해결방안

### 수정 내용 (src/wiki_migration/sanitizer.py)

#### 1. 유니코드 정규화 모듈 import 추가
```python
import unicodedata
```

#### 2. `_find_matching_image()` 함수 개선
```python
def _find_matching_image(attachments_dir, display_name, macro_id):
    # ...
    # 이미지 파일만 필터링 (폴더 제외)
    image_files = [fn for fn in files if any(fn.lower().endswith(ext) for ext in image_exts)]
    
    # NFC 정규화를 적용한 파일명 맵 생성
    normalized_map = {}
    for fn in image_files:
        fn_nfc = unicodedata.normalize('NFC', fn)
        fn_nfc_lower = fn_nfc.lower()
        normalized_map[fn_nfc_lower] = fn
    
    # 검색 문자열도 NFC로 정규화
    def normalize_for_search(s):
        return unicodedata.normalize('NFC', s).lower()
    
    # 우선순위 1: displayName + 확장자
    # 우선순위 2: displayName 정확 일치
    # 우선순위 3: macroId
    # 우선순위 4-5: 부분 매칭
```

### 주요 개선사항
- ✅ 이미지 파일만 필터링하여 폴더 제외
- ✅ 파일명과 검색 문자열을 모두 NFC 정규화
- ✅ 우선순위를 displayName + 확장자로 상향 조정
- ✅ 부분 매칭 시에도 정규화 적용

## 테스트 결과

### 단위 테스트
```
=== 검증 ===
✅ <ac:image> 태그 생성됨
✅ 첫번째 이미지(ㅇㅇ.png) 매칭됨
✅ 두번째 이미지(Open poc 결제 로직.png) 매칭됨
```

### 실제 페이지 테스트 (0015_OPEN POC 결제 로직 파악)
```
발견된 Gliffy 매크로 개수: 2
<ac:image> 태그로 변환된 매크로: 2  ✅
Fallback 메시지로 표시된 매크로: 0   ✅

변환 결과:
- <ac:image><ri:attachment ri:filename="ㅇㅇ.png" /></ac:image>
- <ac:image><ri:attachment ri:filename="Open poc 결제 로직.png" /></ac:image>
```

## 영향 범위
- `Sanitizer.sanitize_gliffy_macros()` 함수
- importer.py에서 호출되는 모든 페이지 import 작업
- 특히 한글 파일명을 가진 gliffy 매크로

## 추가 고려사항
1. 이 수정은 다른 언어(일본어, 중국어 등)의 문자도 정규화하므로 전체 언어에 대응 가능
2. Windows 파일 시스템(NTFS)은 일반적으로 NFC 형식 사용하지만, 정규화를 하는 것이 더 안전
3. 로깅 디버그 메시지 추가로 향후 매칭 문제 추적 용이

