# 도구 레퍼런스

[← README](../../README.md) · [문서 목록](../README.md)

MCP 도구와 CLI 하위 명령은 같은 이름·같은 함수입니다. 아래 표의 순서는 `hwpctl.tools`의 공개 순서와
같아야 하며 CI(`tests/test_public_docs.py`)가 검사합니다.

CLI 와 MCP 는 **같은 함수**를 부릅니다. 성공 시 JSON, 실패 시 stderr 한국어.

<!-- hwpctl-tool-catalog:start -->
| 이름 | 하는 일 |
|---|---|
| `status` | 창 제목, 경로, 수정 여부, 쪽, 한/글 버전 |
| `list_documents` | 실행 중인 모든 한/글 문서의 창·경로·수정 여부·쪽 수를 **활성화 없이** 읽기 전용으로 열거. 경로 없는 초안은 `unsaved: true` |
| `doctor` | 작업 전 환경 점검(읽기 전용): 한/글 응답·대화상자·창 없는 잔재 프로세스·고정 창·`--font` 글꼴 설치/재시작 필요 여부·hwpctl 최신성 |
| `render_page` | 고정 문서의 한 쪽을 BMP/PPM으로 렌더(`CreatePageImage`). 표 안 캐럿이어도 쪽 전체를 그림. 문서 변경 없음 |
| `compare_render` | 원본·결과 쪽 이미지에서 영역별 글자 줄 상자를 찾아 위치·크기 차이(mm) 보고. 한/글·COM 불필요 |
| `open` | 인자 없이는 활성 창 재고정, 경로는 파일 열기, `--new`는 새 문서. 파일 교체 전 수정본은 `--discard` |
| `snapshot` | 제목·본문·표·선택 영역 읽기. 캐럿·선택은 원래대로 복원 |
| `set_edit_marks` | 조판·문단부호 보기를 명시적으로 설정. 본문·다른 보기 옵션 보존 |
| `format_paragraph_by_text` | 정확히 일치하는 일반 본문 문단의 글자·문단 서식 적용 |
| `recreate_inline_table_before_paragraph` | 검증한 1×1 질문 표를 답변 앞에 재생성. Cut/Paste·클립보드·HWPML 미사용 |
| `trim_blank_paragraphs_before_body` | 정확한 답변 앞의 연속 빈 문단을 지정 개수만 남김 |
| `insert_title` | 제목 문단 (가운데, 굵게, 큰 글씨). 서식은 제목에만. Undo 1단위 |
| `insert_paragraph` | 본문 문단·글자 런·문단 레이아웃. `--no-terminate`로 문단 경계를 호출자가 제어. Undo 1단위 |
| `insert_section` | 현재 본문 위치에서 다음 구역 시작 |
| `create_table` | 표. `--header-fill gray`, 기본 칸 안여백 3.5/2.0mm. Undo 1단위 |
| `set_table_properties` | 표의 쪽 나눔(`none`/`table`/`cell`)·제목 행 반복·셀 간격 |
| `set_table_position` | 표의 글자처럼 취급/떠 있는 위치·바깥 여백 |
| `fill_cells` | 셀 값. JSON 배열 또는 `A1=값`. Undo 1단위 |
| `write_cell` | 표 셀을 구조화 문단·글자 런으로 원자적 교체. Undo 1단위 |
| `move_to_cell` | 지정 표의 A1 셀로 이동. 문서 변경·Undo 없음 |
| `exit_table` | 현재 표의 마지막 셀에서 본문 또는 바로 바깥 부모 셀로 이동. 이동 뒤 문맥 검증 |
| `layout_review` | 표 줄바꿈·행 높이·본문 폭·쪽 수 검토/수정. `--dry-run`은 계획만 |
| `set_cell_margin` | 표 칸 **안쪽 여백**(mm). `--no-has-margin`은 셀별 여백을 해제하고 표 기본값 상속 |
| `set_table_inside_margin` | 표 기본 안쪽 여백(`TABLE/INSIDEMARGIN`, mm). 셀별 여백은 보존 |
| `set_col_width` | 열 너비를 mm·비율로 설정 |
| `set_table_grid` | 병합 전 표의 열·행 격자를 모든 실제 셀에 정밀 적용 |
| `get_col_width` | 현재 열 또는 지정 표의 열 너비(mm) 조회 |
| `set_row_height` | 현재 행 또는 지정 행 높이(mm) 설정 |
| `get_row_height` | 현재 행 또는 지정 행 높이(mm) 조회 |
| `merge_cells` | `TableCellBlock` 선택 범위의 셀 합치기 |
| `set_valign` | 셀 세로 정렬: `top` / `center` / `bottom` |
| `set_cell_border` | 셀 테두리. `TypeHorz`는 한글 2022 미지원 |
| `insert_chart` | 표 데이터로 **한/글 네이티브 차트** 삽입 (그림 아님) |
| `insert_image` | 그림 파일(PNG/JPG 등)을 본문 또는 표 칸에 삽입. floating 위치 지정 가능 |
| `insert_text_box` | 편집 가능한 글상자. 구조화 문단, 채우기·테두리·그림자·위치 지정 가능 |
| `insert_shape` | 편집 가능한 사각형·타원·선 삽입 |
| `set_cell_fill` | 표 셀 범위의 단색/선형/방사형 그라데이션 채우기 |
| `set_format` | 글꼴·문자권별 HFT 글꼴·크기·굵게·정렬·셀 색·글자 그림자. `--range` 는 요청 칸에만 |
| `set_style` | 현재 문단에 문서 스타일 적용. 예: `개요 1` |
| `replace_selection` | 블록 선택 영역 교체. 선택 없으면 거부 |
| `undo` | 직전 hwpctl 명령을 한/글 Undo 한 덩어리로. 기록 없으면 거부 |
| `page` | 현재 쪽·`PageCount` 읽기 / `--goto N` 이동 / `--break` 쪽 나누기 |
| `set_page_number` | 네이티브 쪽 번호의 위치·양쪽 구분 문자 설정 |
| `set_page_visibility` | 현재 쪽의 머리말·꼬리말·바탕쪽·테두리·채우기·쪽 번호 숨김 |
| `restart_page_number` | 현재 위치부터 네이티브 쪽 번호 다시 시작 |
| `set_pagedef` | 용지 크기·여백·가로/세로 방향 |
| `reference_to_spec` | HWPML/HWPX/캡처 번들을 v2 작성 명세와 손실 보고서로 변환 |
| `build_document` | v1/v2 명세를 검사한 뒤 새 소유 한/글 세션에서 HWP/HWPX 생성 |
| `save_as` | **새 경로** 저장. 기존 대상은 **`--overwrite` 필수**, 원본 경로는 거부 |
| `save` | 원본 덮어쓰기. **`--overwrite` 필수** |
| `close` | 닫기. **`--force` 필수** |
| `close_all` | 열려 있는 모든 한/글 문서 닫기. **`--force` 필수** |
| `hwpx_status` | `python-hwpx` 설치 여부·선택적 `.hwpx` 요약. **한글 불필요** |
| `hwpx_inspect` | `.hwpx` 문단·런·셀 서식 그룹. **한글·잠금 불필요** |
<!-- hwpctl-tool-catalog:end -->

도구 목록만 (한/글 불필요):

```bash
hwpctl mcp --list-tools
```

문서 변환과 작성은 명세 전체를 먼저 검사할 수 있습니다. `--dry-run`은 결과 파일이나
한/글 창을 만들지 않습니다. 실제 변환의 출력 디렉터리와 작성 결과 경로는 새
경로여야 합니다.

> 두 명령은 **실험 기능**입니다. 명세 검사·dry-run·손실 보고는 자동 회귀로
> 검증됐으며, 새 작성기의 한/글 저장·재열기와 ChartML 보존은 미완료입니다.
> 변환 손실이 있으면 실행 명세를 내보내지 않습니다. 현재 제공 범위는
> [작성 상태](../dev/AUTHORING_COMPLETION.md), 남은 구현·실기는
> [후속 이슈 #25](https://github.com/Jasujung99/hwpctl/issues/25)에 기록합니다.

```powershell
hwpctl reference_to_spec C:\source\sample.hwpx C:\output\converted --dry-run
hwpctl reference_to_spec C:\source\sample.hwpx C:\output\converted
hwpctl build_document C:\output\converted\spec.json C:\output\rebuilt.hwpx --dry-run
hwpctl build_document C:\output\converted\spec.json C:\output\rebuilt.hwpx
```

표를 고를 때 기존 `--table 0` 번호를 계속 쓸 수 있습니다. 중첩 표는
`{"root":0,"children":[{"cell":"A1","index":0}]}`처럼 부모 표, 부모 셀,
그 셀 안에서의 자식 표 번호를 지정합니다. `set_table_properties`에는 `--page-break
keep`, `--keep-repeat-header`, `--keep-cell-spacing`으로 특정 속성을 유지할 수
있습니다.

모델이 「사업계획서, 4열 8행 표, 첫 행 회색」을 이렇게 매핑하면 됩니다.

```bat
hwpctl insert_title 사업계획서
hwpctl create_table --rows 8 --cols 4 --header-fill gray
hwpctl fill_cells --table 0 --cells "[[\"항목\",\"내용\",\"담당\",\"기한\"]]"
hwpctl exit_table
hwpctl insert_paragraph "표 다음 본문"
hwpctl layout_review
hwpctl save_as "%USERPROFILE%\Documents\사업계획서-초안.hwpx"
```

서식이 섞인 문단과 표 셀은 평면화하지 않고 구조화 값으로 작성할 수 있습니다.

```bat
hwpctl insert_paragraph --runs "[{\"text\":\"Q. \",\"bold\":true,\"underline\":true},{\"text\":\"문의 내용\",\"font\":\"함초롬돋움\"}]" --paragraph "{\"align\":\"justify\",\"first_line_indent_mm\":-8,\"line_spacing_percent\":150,\"break_latin_word\":\"keep_word\",\"break_non_latin_word\":\"keep_word\"}"
hwpctl write_cell --table 0 --cell A1 --paragraphs "[{\"runs\":[{\"text\":\"항목\",\"bold\":true}],\"paragraph\":{\"align\":\"center\"}}]"
```

한양 전용 글꼴처럼 글꼴 타입까지 정확히 지정해야 할 때는 `font` 대신
`font_slots`를 씁니다. 문자권은 `hangul`, `hanja`, `japanese`, `latin`, `other`,
`symbol`, `user`이고, 각 값은 비어 있지 않은 `name`과 `type: "ttf" | "hft"`입니다.
`font`와 `font_slots`는 함께 쓸 수 없습니다. 이 사양은 `runs`, `set_format`,
`format_paragraph_by_text`, `insert_text_box`에서 동일하게 지원합니다.

```bat
hwpctl insert_paragraph --runs "[{\"text\":\"제목\",\"font_slots\":{\"hangul\":{\"name\":\"한양견고딕\",\"type\":\"hft\"},\"latin\":{\"name\":\"Arial\",\"type\":\"ttf\"}}}]"
hwpctl set_format --font-slots "{\"hangul\":{\"name\":\"한양견고딕\",\"type\":\"hft\"}}"
```

서브커맨드 이름은 밑줄입니다 (`insert_title`, `fill_cells`).

## 표 편집 뒤 항상 레이아웃 검토

`create_table`, `fill_cells`, `set_format`, `set_cell_margin`, `insert_chart` 등으로
표를 만들거나 채운 뒤에는 **항상 `layout_review`를 한 번 실행합니다.** 편집 명령과
자동으로 묶지는 않습니다. 한/글 잠금과 Undo 단위를 섞지 않기 위해 별도 명령으로
호출해야 합니다.

```bat
hwpctl layout_review                         :: 문서의 모든 표를 검토하고 기본적으로 수정
hwpctl layout_review --table 0               :: 0번 표만 검토하고 수정
hwpctl layout_review --table 0 --dry-run     :: 수정하지 않고 JSON 계획만 출력
```

셀의 조판 줄 수는 한글 2022의 `MoveLineEnd` 위치 진행과 `KeyIndicator` 셀 주소를
함께 확인해 실측합니다. 명시적 줄바꿈보다 조판 줄 수가 많을 때만 열 너비로 인한
줄바꿈으로 판정합니다. 한글 2022 Automation에는 문자열 조판 폭을 직접 재는 API가
없으므로 필요한 목표 열 너비는 글자 크기와 유니코드 문자 폭으로 추정하며, 열 하나가
본문 폭의 45% 또는 기존 너비의 1.6배를 넘지 않게 제한합니다. 표 폭은 용지 폭에서
좌우·제본·표 바깥 여백을 뺀 범위를 넘기지 않습니다.
