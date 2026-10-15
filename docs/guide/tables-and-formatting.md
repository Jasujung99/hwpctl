# 표와 서식

[← README](../../README.md) · [문서 목록](../README.md)

## 표 칸 안쪽 여백 (셀 안 여백)

글자가 칸 테두리에 붙는 문제는 표 바깥 여백이 아니라 **셀 안쪽 여백** 문제입니다.

- `create_table` 은 새 표의 모든 칸에 기본 안여백 **좌우 3.5mm / 상하 2.0mm** 를 적용합니다.
  한/글 기본값(1.8/0.5mm)보다 넉넉합니다. `--cell-padding "3.0,1.5"` 로 바꾸거나
  `--cell-padding none` 으로 끌 수 있습니다.
- 이미 있는 표는 `set_cell_margin` 으로:

```bat
hwpctl set_cell_margin --table 0                        :: 0번 표 전체 칸, 기본 3.5/2.0mm
hwpctl set_cell_margin --table 0 --left 4 --right 4 --top 2 --bottom 2
hwpctl set_cell_margin --table 0 --range A1:D4          :: 해당 칸들만
```

원본의 표 전역 기본값인 `TABLE/INSIDEMARGIN`까지 맞춰야 할 때는 별도 명령을 씁니다.
이 명령은 개별 칸의 `CELL/CELLMARGIN`을 덮어쓰지 않으므로, 셀별 여백과 표 기본값을
구분해 재현할 수 있습니다.

```bat
hwpctl set_table_inside_margin --table 0 --left 4 --right 4 --top 1.5 --bottom 1.5
```

`create_table`의 기본 여백과 `set_cell_margin --table N`은 여전히 표의 실제 셀 주소를
순회하며 각 셀의 `CELLMARGIN`을 적용합니다. Undo 기록에는 적용한 셀 수가 그대로
들어갑니다. 반면 `set_table_inside_margin`은 네이티브 표 속성 액션 한 번으로
`INSIDEMARGIN`만 바꾸며 Undo 한 단위입니다.

## 한글 2022 실측 서식 명령

MCP/Engine 시그니처(같은 이름의 CLI도 제공):

```python
set_col_width(widths, table=None, column=None, unit="mm")  # unit: mm | ratio
set_table_grid(table, column_widths_mm, row_heights_mm)      # 병합 전 완전 직사각 표, mm
get_col_width(table=None, column=None)                     # 결과 단위: mm
set_row_height(height, table=None, row=None)               # mm, row는 1부터
get_row_height(table=None, row=None)                       # 결과 단위: mm
merge_cells(cell_range, table=None)
set_valign(align, table=None, cell_range="")               # top | center | bottom
insert_paragraph(text="", runs=None, paragraph=None, page_break_before=False, terminate=True)
# paragraph: align, *_margin_mm, first_line_indent_mm, *_spacing_mm,
#            line_spacing_percent, break_latin_word, break_non_latin_word
# runs: text, bold, italic, superscript, subscript, kerning, font 또는 font_slots, size, color,
#       underline/strikeout(bool 또는 {enabled,color,type,shape}), text_shadow,
#       letter_spacing_percent, width_scale_percent
write_cell(table, cell, paragraphs)                         # A1, 마지막 문단 뒤 빈 문단 없음
move_to_cell(table, cell)                                   # A1, 문서 변경·Undo 없음
set_table_properties(table, page_break="cell", repeat_header=True, cell_spacing_mm=0.0)
set_table_position(table, position)                         # inline/floating JSON 객체
set_table_inside_margin(table, left=3.5, right=3.5, top=2.0, bottom=2.0)  # TABLE/INSIDEMARGIN, mm
format_paragraph_by_text(text, font="", font_slots=None, ...)
insert_text_box(text, width_mm, height_mm, fill=None, line=None, shadow=None, text_shadow=None,
                font="", font_slots=None, ...)
set_cell_fill(fill, table=None, cell_range="")
exit_table(destination="body")  # body 또는 중첩 표의 바로 바깥 parent; Undo 없음
set_format(..., font="", font_slots=None, text_shadow=None)
set_cell_border(sides="all", line_type="Solid", width="0.12mm",
                color="#000000", table=None, cell_range="")
set_style(style)                                           # 예: "개요 1"
set_pagedef(paper_width=None, paper_height=None, left=None, right=None,
            top=None, bottom=None, header=None, footer=None, gutter=None,
            landscape=None, apply="current")
page(goto=None, break_page=False)
set_page_number(position="bottom_center", separator="-") # 예: - 1 -
set_page_visibility(hide_header=False, hide_footer=False, hide_master_page=False,
                    hide_border=False, hide_fill=False, hide_page_num=False)
restart_page_number(number=1)
list_documents()  # 문서 활성화·저장·닫기 없이 모든 열린 문서 메타데이터 읽기
```

- 열·행 치수는 `GetCellWidth` 없이 `TablePropertyDialog`의
  `ShapeTableCell.Width/Height`를 읽고, 설정할 때 `ShapeCellSize=1`을 씁니다.
  `ratio`는 현재 표 전체 폭을 유지하며 모든 열의 비율을 지정합니다.
- 병합은 `TableCellBlock` → `TableCellBlockExtend` → 셀 이동 →
  `TableMergeCell` 순서입니다. `TableMergeCell` 단독 호출은 하지 않습니다.
- 세로 정렬은 `TableVAlignTop/Center/Bottom`이며 결과의 `vert_align`은 각각
  `0/1/2`입니다.
- 테두리는 `CellBorderFill`을 사용합니다. 왼쪽 색 항목은 한글 2022의 실제
  철자인 `BorderCorlorLeft`를 사용합니다. 내부 가로선 `TypeHorz`는 오류로
  거부합니다.
- 쪽 나누기는 `BreakPage`, 쪽 수는 `PageCount`입니다.
- `set_style("개요 1")`은 pyhwpx가 있으면 해당 API를 쓰고, 창 고정 때문에 COM으로
  연결된 경우에는 문서 HWPML을 **메모리에서 읽기만** 하여 스타일 이름을 ID로 해석한 뒤
  네이티브 `Style` 액션을 실행합니다. HWPML을 저장·주입하지 않으며, 한글 2022에서
  COM 예외가 나는 `HwpOutlineType`/`HwpOutlineStyle` 직접 호출도 하지 않습니다.
- 편집 전후에 한/글 대화상자를 확인하며, 떠 있으면 대신 누르지 않고 한국어
  오류로 중단합니다. SendKeys와 자동저장은 사용하지 않습니다.

CLI 예:

```bat
hwpctl set_col_width --table 0 --widths 1,2,1 --unit ratio
hwpctl set_table_grid --table 0 --column-widths-mm 30,60,30 --row-heights-mm 10,12,10
hwpctl get_col_width --table 0
hwpctl set_row_height --table 0 --row 2 --height 12
hwpctl merge_cells --table 0 --range A1:B1
hwpctl set_valign center --table 0 --range A1:C2
hwpctl set_cell_border --table 0 --range A1:C2 --sides all --color #333333
hwpctl set_table_properties --table 0 --page-break cell --repeat-header --cell-spacing-mm 0
hwpctl set_table_position --table 0 --position "{\"mode\":\"inline\",\"outside_margin_mm\":[0.5,0.5,0.5,0.5]}"
hwpctl set_table_inside_margin --table 0 --left 4 --right 4 --top 1.5 --bottom 1.5
hwpctl set_style "개요 1"
hwpctl set_pagedef --paper-width 210 --paper-height 297 --left 20 --right 20
hwpctl page --break
hwpctl set_page_visibility --hide-page-num
hwpctl restart_page_number --number 1
```

저장 없이 시험하려면 빈 문서에서 다음처럼 실행하고, 결과 확인 뒤 `undo`로
직전 명령을 되돌립니다. `save`/`save_as`를 호출하지 않는 한 자동으로 저장되지
않습니다.

```bat
hwpctl open --new
hwpctl create_table --rows 2 --cols 3
hwpctl set_table_grid --table 0 --column-widths-mm 30,60,30 --row-heights-mm 12,12
hwpctl set_valign center --table 0
hwpctl layout_review --table 0
hwpctl page
hwpctl undo
```

`set_table_grid`는 셀 병합 전에만 사용합니다. 여러 쪽으로 이어지는 표도 모든 실제
셀에 너비와 높이를 함께 적용해 열·행 블록 선택이 쪽 경계에서 끊기는 한/글 2022
경로를 피합니다. 완료 뒤에는 호출 전 커서 위치를 복원합니다.

중첩 표 앞뒤처럼 문단 끝을 자동으로 넣으면 안 되는 경우에는
`insert_paragraph --no-terminate`를 쓰고, 다음 문단 경계는 호출자가 명시적으로
만듭니다.
