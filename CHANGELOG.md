# 변경 기록

주요 변경 사항을 이 문서에 기록합니다. 버전은 [Semantic Versioning](https://semver.org/)을
따르며, 첫 GitHub Release는 한글 2022 수동 검증을 통과한 뒤 `v0.1.0`으로 게시합니다.

## [Unreleased]

### Added

- CLI/MCP `set_edit_marks`: 조판·문단부호 표시를 명시적으로 설정하고 읽어서 검증.
  반복 호출 시 토글하지 않으며 본문이나 Undo 이력을 변경하지 않음.
- 내부 순수 함수 `compact_formatting_xml`: 미사용 글자·문단 서식 정의만 검사·정리.
  문단·도형 앵커는 삭제하지 않으며, 공개 파일 수정 명령으로 제공하지 않음.

- 문자권별 글꼴 사양 `font_slots`: `hangul`/`hanja`/`japanese`/`latin`/
  `other`/`symbol`/`user`별로 `{name, type: ttf|hft}`를 지정한다. 한양 전용
  HFT 글꼴은 `FaceName*`과 `FontType*`을 하나의 네이티브 `CharShape` 액션으로
  적용하며 기존 단일 `font`와 동시에 지정하면 실행 전에 거부한다.
- 구조화 문단 `insert_paragraph(..., terminate=True)`: `terminate=false`로
  `BreakPara` 자동 생성을 끄고 중첩 표 앞뒤의 문단 경계를 호출자가 정확히 제어
- 병합 전 완전 직사각 표의 모든 실제 셀에 열 너비·행 높이를 함께 적용하는
  `set_table_grid(table, column_widths_mm, row_heights_mm)`: 쪽 경계를 넘는 표 격자를
  명시적으로 고정하고, 원래 커서를 복원하며 hwpctl Undo 한 단위로 기록
- 비파괴 표 탐색 `move_to_cell(table, cell)` 및 중첩 표 한 단계 탈출
  `exit_table(destination="parent")`: 마지막 셀·목록 문맥을 검증해 본문 또는 부모
  표를 과도하게 건너뛰지 않음
- 비공개 참조 문서를 위한 실험적 읽기 전용 HWPML 캡처·구조 비교 계층
  `hwpctl.reference`: 원본 해시를 열기 전후 확인하고, 스타일 ID·빈 문단·공유 표
  테두리에 강한 구조 보고서를 원문·경로 없이 만든다. 이 계층은 아직 CLI/MCP 작성
  명령이 아니며, 도형·그라데이션·시각 레이아웃은 명시적으로 미지원 상태로 남긴다.
- 원본 구조를 이미지·클립보드·HWPML로 평면화하지 않는 문단 앵커 교정 API
  `recreate_inline_table_before_paragraph(...)`, `trim_blank_paragraphs_before_body(...)`:
  검증된 1×1 인라인 표를 답변 앞에 재생성하고 질문→빈 문단→답변의 문단부호를 보존
- 실행 중인 모든 한/글 문서를 문서 단위로 닫는 명시적 파괴 명령
  `close_all(force=true)` / `close_all --force` (문서 Close 뒤 남는 빈 창은 해당 인스턴스 Quit으로 종료)
- 구조화 문단 API `insert_paragraph(text, runs, paragraph, page_break_before)`와
  원자적 표 셀 교체 `write_cell(table, cell, paragraphs)`: 글자 런, 자간·장평,
  위/아래첨자·밑줄·취소선의 색·type·shape·kerning, 문단 정렬·여백·들여쓰기·줄간격·
  라틴/비라틴 단어 줄바꿈을 CLI·MCP·Engine에서 동일하게 제공
- 본문 텍스트를 평면화하지 않는 네이티브 쪽 번호 `set_page_number(position, separator)`
- 표의 네이티브 쪽 나눔·제목 행 반복·셀 간격 `set_table_properties(table, page_break, repeat_header, cell_spacing_mm)`와
  inline/floating 위치·바깥 여백 `set_table_position(table, position)`
- 현재 쪽의 표시 요소를 숨기는 `set_page_visibility(...)`와 현재 위치부터 번호를
  다시 시작하는 `restart_page_number(number)`
- 편집 가능한 글상자 `insert_text_box`: 단색/선형 그라데이션, 선, 도형 그림자,
  글자 그림자와 inline/floating 배치
- 표 셀의 단색/선형 그라데이션 `set_cell_fill`, `set_format(text_shadow=...)`
- CLI·MCP·Engine 공통의 채우기·그림자·선·좌표 검증과 한글 2022 COM 구현
- 한글 없이 `.hwpx`를 다루는 준비 계층(`hwpctl/hwpx`, extra `hwpx`, `hwpx_status` / `hwpx_inspect`)
- Codex, Claude Code, Cursor, Gemini CLI, Grok Build용 로컬 MCP 설정 예제
- 공개용 보안 정책, 알려진 한계, 기여 안내와 릴리스 체크리스트
- 표 너비·높이, 셀 병합·정렬·테두리, 쪽 설정, 스타일과 레이아웃 검토 문서
- Windows COM extra 없이 Python 3.10·3.12에서 HWPX·MCP 도구 목록·오류 종료 코드·
  공개 파일을 검증하는 Linux CI 계약

### Changed

- `open --new` 이후의 후속 명령이 고정된 한글 창을 계속 사용하도록 창 핀을 갱신
- 인자 없는 `open`을 비파괴 활성 창 재고정으로 바꾸어, 닫혔거나 재시작된 창 핀을
  복구하고 새 문서 생성은 명시적인 `open --new`로 한정
- 로컬 클라이언트는 stdio를 기본으로 사용하고 HTTP는 선택 연결로 구분

### Fixed

- `insert_title`, `fill_cells`, `set_format`가 중간 실패한 경우에도 이미 실행된
  한/글 편집 액션을 Undo 이력에 남겨 반쯤 적용된 변경을 안전하게 되돌릴 수 있도록 수정
- 창 핀 때문에 win32com으로 연결된 경우에도 문서 스타일 이름을 적용할 수 있도록,
  읽기 전용 메모리 HWPML에서 스타일 ID를 해석해 기존 네이티브 `Style` 액션으로 연결
- README 도구 표를 실제 공개 도구와 맞추고, `insert_image`·오류 종료 코드·예제 성격·
  HWPX PPM 비교 라이브러리의 현재 범위를 정확히 문서화
- 신년 카드 예제 배경 이미지의 GPT 계열 생성 출처와 배포 시 권리 확인 범위를 고지

### Security

- 원본 덮어쓰기·닫기·수정본 폐기에 명시 플래그 요구
- `save_as`도 기존 대상 파일에는 `overwrite=true` / `--overwrite`를 요구하고,
  원본과 같은 경로는 계속 `save --overwrite`로만 저장
- MCP HTTP 연결을 loopback과 토큰으로 제한
