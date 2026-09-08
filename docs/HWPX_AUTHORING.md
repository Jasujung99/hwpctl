# HWPX 범용 작성·검사 (1차 통합)

로컬 `origin/fixtures/gongo-doc1`의 `dfa1011` → `e8eaf9c` → `bdf7497`에서
범용 변경만 선별했다. 공고 전용 `gongo.py`, 원본 HWP/PNG, 생성 바이너리는
포함하지 않는다. main의 이미지 비교·네이티브 편집 기능도 유지한다.

## 공식 진입점

아래는 라이브러리 API다. 새 CLI/MCP 작성 명령이나 범용 importer를 추가하지 않았다.

```python
from hwpctl.hwpx import (
    new_document, set_page_setup, insert_paragraph, set_paragraph_runs,
    apply_paragraph_format, create_table_and_fill, save_document, inspect_hwpx,
)

doc = new_document()
try:
    set_page_setup(doc, paper_size="A4", orientation="portrait")
    paragraph = insert_paragraph(doc, "")
    set_paragraph_runs(doc, [
        {"text": "일반 본문 ", "size": 11},
        {"text": "강조", "bold": True, "color": "#FF0000"},
    ], paragraph=paragraph)
    apply_paragraph_format(doc, paragraph=paragraph, line_spacing_percent=150)
    create_table_and_fill(doc, 2, 2, [["항목", "값"], ["합성", "예제"]],
                          column_widths_mm=[40, 100], header_fill="#EEEEEE")
    # Use a caller-selected NEW output. save_document retains its existing
    # library save contract; it is not Engine.save_as's overwrite guard.
    save_document(doc, "synthetic.hwpx")
finally:
    doc.close()
report = inspect_hwpx("synthetic.hwpx")
```

- `append_run`, `set_paragraph_runs`, 확장 `set_run_props`: 런별 서식,
  글꼴 선언, 기준 글자 서식의 굵게·기울임·밑줄 상속.
- `apply_paragraph_format`: 본문/셀 문단의 정렬·줄간격·여백·아래 테두리.
  셀 문단 처리를 위한 임시 본문 문단은 제거한다.
- `create_table_and_fill`: 실제 표, 열 폭·높이·헤더 채움·테두리.
  비유한/비양수 치수는 삽입 전에 거부한다. 기존 API의 범위 밖 입력 셀을
  잘라내는 동작은 그대로이며, 완전한 입력 모델 검증기는 아니다.
- `set_page_setup`: python-hwpx 페이지 설정을 감싸 HWPX 쪽 방향 토큰을 적용.
  A4 가로·세로는 별도 한/글 opt-in 테스트로 확인한다.
- `inspect_hwpx`: 기존 출력 필드를 유지하며 런·밑줄·테두리·표 치수·쪽 속성을
  추가한다. `runs[].text`는 최대 40자 샘플이며 원문 완전성 검사에 쓰면 안 된다.

런 교체는 구역·표 등 비텍스트 자식을 유지한다. 잘못된 후속 런 서식을 먼저
검증하지만 전체 ZIP 트랜잭션이나 모든 편집 실패의 rollback을 보장하지 않는다.
그림이 없는 문서만을 성공으로 판정하지 않으며 시각적 동일성도 주장하지 않는다.

## 참조 내보내기의 공통 구현

```python
from hwpctl.reference import export_hwpml_readonly, export_pdf_readonly

# Explicit private analysis outputs; not an authoring route.
export_hwpml_readonly("reference.hwp", "private/reference.hwpml")
export_pdf_readonly("reference.hwp", "private/reference.pdf")
```

두 함수는 기존 `capture_hwpml_readonly`와 격리 COM·읽기 전용 열기·원본 해시
확인·소유 인스턴스 종료를 공유한다. 기존 산출물은 거부하고, PDF는 임시 위치에서
생성·원본 무변경 확인 후 게시한다. 메모리 HWPML의 XML 선언과 파일 인코딩을 맞춘다.
결과 메타데이터에는 원본 경로/본문을 넣지 않지만, 산출물 자체에는 원문이 있으므로
공개 Git에 넣으면 안 된다. `com_page_count`는 물리 PDF 쪽수 검증이 아니다.

`export_reference_bundle_readonly(source, output_dir)`는 HWPML과 그림 자산을 함께
내보낸다. `IMAGE/BinItem`이 참조하는 명시적 `Embedding` 자산만 소유 COM이 살아
있는 동안 복사하고 SHA-256을 검사한다. 연결 파일은 따라가지 않는다. 누락/연결
자산은 manifest에 `extracted: false`로 남으며 `assets_complete`도 false다.
이 값은 IMAGE 참조 추출의 완결성이지 모든 문서 개체나 시각적 완전성이 아니다.
빈 디렉터리라도 기존 출력은 거부한다. 원본 해시 확인 후 결과를 복사하고
`manifest.json`을 마지막에 게시한다. 디스크 복사 오류에는 부분 디렉터리가 남을
수 있으므로 manifest 없는 결과를 완료로 사용하지 않는다. 옛 스크립트는 보존한다.

## 후속 후보의 4계층 연결

| 책임 | 기준 코드·진입점 | 계약 |
| --- | --- | --- |
| 패키지·입출력 | `hwpctl.hwpx`, `reference.export` | 편집 가능한 HWPX 작성과 읽기 전용 분석 내보내기를 분리 |
| 문서 모델·입력 분석 | `reference.model`, `analyze_hwpml` | 정규 관찰 모델·미지원 제어·누락 서식 참조·다중 구역/표를 보고. 작성 명세를 자동 생성하지 않음 |
| 구성·조판 | 기존 `layout.py`, `hwpctl.units` | HU/mm/pt 변환은 한 번만 반올림. 문단 여백 1/2 같은 문서별 보정은 적용하지 않음 |
| 검증 | `solve_grid_tracks`, 구조 비교기, 검사·회귀 테스트 | 병합 폭의 정확한 유리수 제약 풀이. 정보 부족/모순을 임의 분배·스케일 보정으로 숨기지 않음 |

```python
from hwpctl.reference import analyze_hwpml, solve_grid_tracks
from hwpctl.units import mm_to_hwpunit

# hwpml_text is already captured in memory; no app or files opened here.
analysis = analyze_hwpml(hwpml_text)
analysis.require_supported()  # Fail on detected unsupported facts before writing.
evidence = solve_grid_tracks(3, [(0, 2, 301), (1, 2, 501), (0, 3, 601)])
assert evidence.status == "exact"  # tracks_hwp = (100, 201, 300), in raw HU
offset = mm_to_hwpunit(-12.017)  # signed offsets are valid; sizes have stricter guards
```

분석기는 FAQ 변환기의 읽기 전용 사전 분석 책임을 옮긴 것이다. 기존 문서별 변환기의
전체 스타일·자산 별칭·작성 JSON 변환을 승격한 것은 아니다. `require_supported`는
검출된 문제를 차단할 뿐 모든 미지원 기능의 완전 탐지나 시각 동일성을 인증하지 않는다.
작성은 기존 합성 FAQ 드라이버의 명세 검증과 공개 `Engine.dispatch` 계약을 별도로
거친다. 관찰 모델을 작성 명세인 것처럼 직접 dispatch하지 않는다.

격자 검증의 `exact`는 주어진 정수 HU 등식에서의 결과다. 실제 측정치의 1 HU 차이도
`inconsistent`일 수 있다. 표 도형의 외곽 폭과 셀 트랙 폭을 자동으로 같게 만들지 않는다.
정보 부족의 `None`은 추정 너비로 바꾸지 않는다. 이 검증기를 자동 조판기로 쓰지 않는다.
HWPX 검사기는 줄간격 원시 값·종류·단위를 구분하며 고정 HU를 percent로 표시하지 않는다.

검증 위치: `tests/test_hwpx_writer.py`, `tests/test_reference_export.py`, `tests/test_reference_candidates.py`,
`tests/test_hangul_live_integration.py`. 추가 후보는
[후속 목록](INTEGRATION_CANDIDATES.md)에서 이번 변경과 분리한다.
