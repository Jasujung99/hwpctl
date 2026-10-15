# 변경 기록

주요 변경 사항을 이 문서에 기록합니다. 버전은 [Semantic Versioning](https://semver.org/)을
따릅니다. 0.x 동안에는 MCP 도구 이름·인자·결과 형식이 바뀌면 **Breaking**으로 표시하고
부 버전을 올립니다. 각 릴리스는 [릴리스 체크리스트](docs/dev/RELEASE_CHECKLIST.md)의 한글 2022
실기 확인을 거친 뒤 태그를 붙입니다.

## [Unreleased]

### Added

- `hwpctl.textart`: 한글 2022 `12.0.0.850`에서 실측한 글맵시 사실(모양 55종의 COM 번호↔HWPX 이름,
  정렬·글꼴 스타일 값, 여러 줄 저장 표기)과 한/글 없이 `.hwpx`·`.hwpml`의 글맵시를 읽는 리더 (#30 준비)
- 합성 글맵시 테스트 자료 `tests/fixtures/textart/`(HWPX·HWPML 3세트)와 출처 기록

## [0.1.0] - 2026-10-15

첫 공개 릴리스입니다. 열린 한글 2022 문서를 MCP·CLI로 편집하는 54개 도구를 제공합니다.

검증 환경: Windows 11, 한글 2022 `12.0.0.850`, Python 3.13, pywin32 312(`win32com` 백엔드),
MCP Python SDK 1.29. CI는 Windows·Linux에서 Python 3.10·3.12로 실행합니다.

### 편집 도구

- **문서·창**: `status`, `list_documents`(활성화 없이 모든 문서 열거), `doctor`(작업 전 읽기 전용
  점검), `open`(인자 없이 활성 창 재고정, 경로 열기, `--new` 새 문서), `snapshot`,
  `set_edit_marks`(조판·문단부호 보기를 명시적으로 설정)
- **문단·글자**: `insert_title`, `insert_paragraph`(글자 런·문단 레이아웃·줄 간격·
  `--no-terminate`), `format_paragraph_by_text`, `set_format`(글자 그림자 포함), `set_style`,
  `replace_selection`. 문자권별 글꼴 `font_slots`로 한양 HFT 글꼴의 글꼴 타입까지 지정
- **표**: `create_table`(기본 칸 안여백 3.5/2.0mm), `fill_cells`, `write_cell`(구조화 문단으로
  원자적 교체), `set_table_grid`(병합 전 격자 정밀 적용), `set_col_width`/`get_col_width`,
  `set_row_height`/`get_row_height`, `merge_cells`, `set_valign`, `set_cell_border`,
  `set_cell_margin`, `set_table_inside_margin`, `set_table_properties`(쪽 나눔·제목 행 반복·
  셀 간격), `set_table_position`(글자처럼 취급/떠 있음·바깥 여백), `move_to_cell`,
  `exit_table`(중첩 표 한 단계 탈출), `layout_review`, `set_cell_fill`(단색·선형·방사형 2색)
- **개체**: `insert_chart`(한/글 네이티브 차트, 검증 빌드에서 사용 비권장 — [#33](https://github.com/Jasujung99/hwpctl/issues/33)), `insert_image`, `insert_text_box`(채우기·선·
  그림자·세로 정렬·세로쓰기·위치), `insert_shape`(사각형·타원·선)
- **쪽**: `page`, `insert_section`, `set_pagedef`, `set_page_number`, `set_page_visibility`,
  `restart_page_number`
- **문단 앵커 교정**: `recreate_inline_table_before_paragraph`,
  `trim_blank_paragraphs_before_body` (클립보드·HWPML 주입 없이 구조 보존)
- **결과 확인**: `render_page`(쪽 렌더), `compare_render`(원본·결과 글자 줄 위치를 mm로 비교)
- **저장·되돌리기**: `save_as`, `save`, `close`, `close_all`, `undo`
- **한/글 없이 HWPX**: `hwpx_status`, `hwpx_inspect`
- **실험 기능**: `reference_to_spec`(HWPML/HWPX/캡처 번들 → 작성 명세와 손실 보고서),
  `build_document`(명세 사전 검사 후 새 소유 문서 작성, `--session attached` 지원)

### 안전

- 자동 저장하지 않습니다. `save_as`는 새 경로만 받고, 기존 파일에는 `--overwrite`가 필요하며
  원본 경로는 거부합니다. 원본 덮어쓰기는 `save --overwrite`, 닫기는 `--force`, 수정본 폐기는
  `--discard`를 요구합니다.
- 명령 단위 잠금으로 한 번에 하나의 작성기만 동작합니다.
- 편집 전후에 한/글 대화상자를 확인하고, 떠 있으면 대신 누르지 않고 한국어 오류로 중단합니다.
- 각 명령의 실제 Undo 단계 수를 기록합니다(그림·글상자 등 실측). 명령이 중간에 실패해도
  이미 실행된 편집은 Undo 이력에 남깁니다.
- 3색 이상 그라데이션은 한/글 2022가 채우기 전체를 조용히 버리므로 실행 전에 거부합니다.
- MCP HTTP 연결은 loopback과 토큰으로 제한합니다. 기본 연결은 로컬 stdio입니다.

### 연결과 플랫폼

- Claude Code, Codex, Cursor, Gemini CLI, Grok Build용 MCP 설정 예제
- 검증 기준 백엔드는 `win32com`(pywin32)입니다. `pyhwpx`는 선택 extra(`.[pyhwpx]`)이며
  창을 고정하기 전 연결에서만 쓰입니다.
- Windows COM 없이도 HWPX 계층·MCP 도구 목록·오류 종료 코드(3)·공개 파일을 검증하는 Linux
  CI 계약
- 태그를 푸시하면 테스트·빌드 후 GitHub Release에 wheel·sdist를 첨부하는 릴리스 워크플로

### 문서

- README를 한국어·영어 병기 첫 화면으로 정리하고, 상세 내용은 [사용 가이드](docs/guide/)로 분리
- [알려진 한계](KNOWN_LIMITATIONS.md), [보안 정책](SECURITY.md), [기여 안내](CONTRIBUTING.md),
  [제3자 고지](THIRD_PARTY_NOTICES.md)
- 도구 레퍼런스 표 순서와 README 대표 도구 표를 CI가 실제 도구 목록과 대조

### 출시 전에 고친 주요 문제

- `build_document`의 소유 세션 정리: 한글 2022가 마지막 문서를 닫으면 경로 없는 빈 문서를 자동으로
  새로 만들어, 작성이 성공해도 `ok: false`가 되고 숨은 한/글 프로세스가 남던 문제. 소유 인스턴스에
  자동 생성된 빈 문서만 남았을 때만 종료하고, 경로가 있거나 수정된 문서가 있으면 종료하지 않습니다.
- 글상자가 크기 지정과 무관하게 1mm로 만들어지던 문제
- `insert_image`의 크기가 mm→HwpUnit으로 두 번 변환되던 문제
- 문서 끝 개체 뒤로 캐럿을 옮기지 못해 도형·글상자 삽입이 실패하던 문제
- 한 문단의 글자 런이 앞 런의 장평·자간·굵게 등을 의도치 않게 이어받던 문제
- 도구 레퍼런스 예시를 `fill_cells` → `move_to_cell`(마지막 셀) → `exit_table` 순서로 바로잡음
- 창 고정으로 `win32com`에 연결된 경우에도 문서 스타일 이름(`개요 1` 등)을 적용하도록 수정
- `open --new` 이후 명령이 고정된 창을 계속 쓰도록, 인자 없는 `open`은 문서를 만들지 않고
  재고정만 하도록 정리

### 알려진 한계

- `insert_chart`는 검증 빌드에서 데이터 편집 대화상자가 떠 호출이 멈추고 표 데이터가 반영되지 않습니다
  ([#33](https://github.com/Jasujung99/hwpctl/issues/33)). README 대표 도구에서 뺐고, MCP 도구 설명에도 경고를 넣었습니다.
- 글자 그러데이션(글맵시)은 아직 도구가 없습니다 ([#30](https://github.com/Jasujung99/hwpctl/issues/30)).
- MCP Python SDK 2.x는 지원하지 않습니다 ([#29](https://github.com/Jasujung99/hwpctl/issues/29)).
- `reference_to_spec`·`build_document`의 ChartML·일부 서식 변환과 네이티브 저장·재열기 실기는
  미완료입니다 ([#25](https://github.com/Jasujung99/hwpctl/issues/25)).
- 전체 목록: [알려진 한계](KNOWN_LIMITATIONS.md)

### 개발 기반

사용자 기능은 아니지만 이번 릴리스에 포함된 내부 기반입니다. 4계층 통합 대장·검증 기록,
읽기 전용 참조 HWPML 캡처·구조 비교 라이브러리(`hwpctl.reference`), 범용 HWPX 런·문단·표 작성
라이브러리, 미사용 서식 정의 정리 함수 등은 [개발 문서](docs/dev/INTEGRATION_STATUS.md)를 보세요.

[Unreleased]: https://github.com/Jasujung99/hwpctl/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Jasujung99/hwpctl/releases/tag/v0.1.0
