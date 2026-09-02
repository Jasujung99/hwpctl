"""CLI 인자 파서. 한/글에 의존하지 않아 리눅스에서도 단위 테스트한다."""

from __future__ import annotations

import argparse
import json
from typing import Any, Sequence

from hwpctl import __version__
from hwpctl.tools import TOOLS, tool_names


class KoreanHelpFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hwpctl",
        description=(
            "한/글 2022 라이브 코파일럿 브리지.\n"
            "채팅 클라이언트는 이 CLI/MCP 에만 붙고, 한/글 조작은 여기서만 한다."
        ),
        formatter_class=KoreanHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"hwpctl {__version__}")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="예외 스택을 표시합니다. 기본은 한국어 한 줄 오류만 출력합니다.",
    )
    parser.add_argument(
        "--lock-timeout",
        type=float,
        default=8.0,
        metavar="SEC",
        help="작성 잠금 대기 시간(초)",
    )

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def add_common(sp: argparse.ArgumentParser) -> argparse.ArgumentParser:
        # 서브커맨드 뒤에서도 --debug / --lock-timeout 을 쓸 수 있게 한다.
        # SUPPRESS 기본값이라 미지정 시 루트 파서의 값이 유지된다.
        sp.add_argument("--debug", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        sp.add_argument("--lock-timeout", type=float, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        return sp

    add_common(sub.add_parser("status", help="열린 한/글 창 상태"))
    add_common(
        sub.add_parser(
            "list_documents",
            help="실행 중인 모든 한/글 문서를 활성화 없이 읽기 전용으로 열거",
        )
    )

    p_open = add_common(
        sub.add_parser("open", help="활성 창 재고정, 파일 열기 또는 새 문서 만들기")
    )
    p_open.add_argument("path", nargs="?", help="열 파일 경로. 없으면 활성 창을 재고정")
    p_open.add_argument("--new", action="store_true", help="기존 창에 붙지 않고 새 한/글 인스턴스")
    p_open.add_argument(
        "--discard",
        action="store_true",
        help="저장하지 않은 수정본을 버리고 엽니다 (파괴적)",
    )

    add_common(sub.add_parser("snapshot", help="제목·본문·표·선택 영역 스냅샷"))

    p_format_paragraph = add_common(
        sub.add_parser(
            "format_paragraph_by_text",
            help="정확히 일치하는 일반 본문 한 문단의 글자·문단 서식 적용",
        )
    )
    p_format_paragraph.add_argument("--text", required=True, help="정확히 일치해야 하는 한 문단")
    p_format_paragraph.add_argument("--font", default="", help="글꼴 이름")
    p_format_paragraph.add_argument("--size", type=float, default=None, help="글자 크기(pt)")
    p_format_paragraph.add_argument("--bold", action=argparse.BooleanOptionalAction, default=None)
    p_format_paragraph.add_argument("--italic", action=argparse.BooleanOptionalAction, default=None)
    p_format_paragraph.add_argument("--color", default="", help="글자색. 이름 또는 #RRGGBB")
    p_format_paragraph.add_argument(
        "--letter-spacing-percent", type=int, default=None, help="자간(%, -50~50)"
    )
    p_format_paragraph.add_argument(
        "--width-scale-percent", type=int, default=None, help="장평(%, 50~200)"
    )
    p_format_paragraph.add_argument("--paragraph", default="", help="문단 서식 JSON 객체")
    p_format_paragraph.add_argument("--occurrence", type=int, default=1, help="앞에서 몇 번째 일치")
    p_format_paragraph.add_argument(
        "--dry-run", action="store_true", help="찾기·전체 문단 검증만 하고 수정하지 않음"
    )

    p_recreate_inline = add_common(
        sub.add_parser(
            "recreate_inline_table_before_paragraph",
            help="검증한 1×1 인라인 표를 본문 문단 앞으로 재생성하고 기존 표만 제거",
        )
    )
    p_recreate_inline.add_argument("--old-table", type=int, required=True, help="교체할 기존 표 번호(0부터)")
    p_recreate_inline.add_argument(
        "--expected-table-text",
        required=True,
        help="기존 표 A1과 정확히 일치해야 하는 질문 문자열",
    )
    p_recreate_inline.add_argument(
        "--before-text",
        required=True,
        help="새 질문 표 뒤에 와야 하는 정확한 일반 본문 답변 문단",
    )
    p_recreate_inline.add_argument(
        "--table-spec",
        required=True,
        help="source 정규화 1×1 inline 표 JSON 객체",
    )
    p_recreate_inline.add_argument(
        "--blank-paragraph",
        required=True,
        help="질문과 답변 사이 Enter 하나의 source 빈 문단 JSON 객체",
    )
    p_recreate_inline.add_argument(
        "--dry-run", action="store_true", help="기존 표·답변 문단 검증만 하고 수정하지 않음"
    )

    p_trim_blank = add_common(
        sub.add_parser(
            "trim_blank_paragraphs_before_body",
            help="본문 답변 앞의 연속 빈 문단을 지정 개수만 남김",
        )
    )
    p_trim_blank.add_argument("--text", required=True, help="정확히 일치해야 하는 일반 본문 답변 문단")
    p_trim_blank.add_argument("--keep", type=int, default=1, help="남길 빈 문단 수(기본 1)")
    p_trim_blank.add_argument("--dry-run", action="store_true", help="빈 문단 수만 읽고 수정하지 않음")

    p_title = add_common(sub.add_parser("insert_title", help="제목 문단 삽입"))
    p_title.add_argument("text")
    p_title.add_argument("--size", type=float, default=20.0, help="글자 크기(pt)")

    p_para = add_common(sub.add_parser("insert_paragraph", help="본문 문단 삽입"))
    p_para.add_argument("text", nargs="?", default="", help="단순 문단 텍스트")
    p_para.add_argument(
        "--runs",
        default="",
        help="문단 안 글자 런 JSON 배열. text와 함께 지정할 수 없음",
    )
    p_para.add_argument(
        "--paragraph",
        default="",
        help="정렬·여백·들여쓰기·줄간격 JSON 객체",
    )
    p_para.add_argument(
        "--page-break-before",
        action="store_true",
        help="이 문단 앞에서 네이티브 쪽 나누기",
    )

    p_table = add_common(sub.add_parser("create_table", help="표 만들기 (기본 칸 안여백 3.5/2.0mm)"))
    p_table.add_argument("--rows", type=int, required=True)
    p_table.add_argument("--cols", type=int, required=True)
    p_table.add_argument("--header-fill", default="", help="첫 행 배경색. 예: gray, #D9D9D9")
    p_table.add_argument("--no-header", action="store_true", help="1행을 제목행으로 두지 않음")
    p_table.add_argument(
        "--cell-padding",
        default="3.5,2.0",
        metavar="MM",
        help="새 표 모든 칸의 안쪽 여백(mm). '좌우,상하' 또는 '좌,우,상,하'. none 이면 미적용",
    )

    p_table_properties = add_common(
        sub.add_parser("set_table_properties", help="표의 쪽 나눔·제목 행 반복·셀 간격 지정")
    )
    p_table_properties.add_argument("--table", type=int, required=True, help="표 번호(0부터)")
    p_table_properties.add_argument(
        "--page-break",
        choices=["none", "table", "cell"],
        default="cell",
        help="쪽 경계에서 표 나눔 방식 (기본 cell)",
    )
    p_table_properties.add_argument(
        "--repeat-header",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="쪽마다 첫 행을 제목 행으로 반복 (기본 true)",
    )
    p_table_properties.add_argument(
        "--cell-spacing-mm",
        type=float,
        default=0.0,
        help="셀 사이 간격(mm, 기본 0)",
    )

    p_table_position = add_common(
        sub.add_parser("set_table_position", help="표의 inline/floating 위치와 바깥 여백 지정")
    )
    p_table_position.add_argument("--table", type=int, required=True, help="표 번호(0부터)")
    p_table_position.add_argument(
        "--position",
        required=True,
        help=(
            "표 위치 JSON 객체. 예: "
            "'{\"mode\":\"inline\",\"outside_margin_mm\":[0.5,0.5,0.5,0.5]}' 또는 "
            "'{\"mode\":\"floating\",\"x_mm\":10,\"y_mm\":20,\"wrap\":\"top_and_bottom\"}'"
        ),
    )

    p_margin = add_common(sub.add_parser("set_cell_margin", help="표 칸 안쪽 여백(mm) 지정"))
    p_margin.add_argument("--table", type=int, default=None, help="표 번호(0부터). 범위 없으면 표 전체 칸")
    p_margin.add_argument("--range", dest="cell_range", default="", help="셀 범위. 예: A1:D4")
    p_margin.add_argument("--left", type=float, default=3.5, help="좌측 여백(mm)")
    p_margin.add_argument("--right", type=float, default=3.5, help="우측 여백(mm)")
    p_margin.add_argument("--top", type=float, default=2.0, help="상단 여백(mm)")
    p_margin.add_argument("--bottom", type=float, default=2.0, help="하단 여백(mm)")

    p_col = add_common(sub.add_parser("set_col_width", help="표 열 너비를 mm 또는 비율로 지정"))
    p_col.add_argument("--widths", required=True, help="너비 목록. 예: 30 또는 1,2,1")
    p_col.add_argument("--unit", choices=["mm", "ratio"], default="mm")
    p_col.add_argument("--table", type=int, default=None, help="표 번호(0부터)")
    p_col.add_argument("--column", type=int, default=None, help="열 번호(1부터, mm 단일값 전용)")

    p_get_col = add_common(sub.add_parser("get_col_width", help="표 열 너비(mm) 읽기"))
    p_get_col.add_argument("--table", type=int, default=None, help="표 번호(0부터)")
    p_get_col.add_argument("--column", type=int, default=None, help="열 번호(1부터)")

    p_row_height = add_common(sub.add_parser("set_row_height", help="표 행 높이(mm) 지정"))
    p_row_height.add_argument("--height", type=float, required=True, help="행 높이(mm)")
    p_row_height.add_argument("--table", type=int, default=None, help="표 번호(0부터)")
    p_row_height.add_argument("--row", type=int, default=None, help="행 번호(1부터)")

    p_get_row = add_common(sub.add_parser("get_row_height", help="표 행 높이(mm) 읽기"))
    p_get_row.add_argument("--table", type=int, default=None, help="표 번호(0부터)")
    p_get_row.add_argument("--row", type=int, default=None, help="행 번호(1부터)")

    p_merge = add_common(sub.add_parser("merge_cells", help="셀 범위 합치기"))
    p_merge.add_argument("--range", dest="cell_range", required=True, help="셀 범위. 예: A1:B2")
    p_merge.add_argument("--table", type=int, default=None, help="표 번호(0부터)")

    p_valign = add_common(sub.add_parser("set_valign", help="표 셀 세로 정렬"))
    p_valign.add_argument("align", choices=["top", "center", "bottom"])
    p_valign.add_argument("--table", type=int, default=None, help="표 번호(0부터)")
    p_valign.add_argument("--range", dest="cell_range", default="", help="셀 범위. 예: A1:D4")

    p_border = add_common(sub.add_parser("set_cell_border", help="표 셀 테두리 지정"))
    p_border.add_argument(
        "--sides",
        default="all",
        help="all 또는 left,right,top,bottom 조합. TypeHorz는 미지원",
    )
    p_border.add_argument("--line-type", default="Solid", help="HwpLineType 이름")
    p_border.add_argument("--width", default="0.12mm", help="HwpLineWidth 값")
    p_border.add_argument("--color", default="#000000", help="테두리 색")
    p_border.add_argument("--table", type=int, default=None, help="표 번호(0부터)")
    p_border.add_argument("--range", dest="cell_range", default="", help="셀 범위. 예: A1:D4")

    p_image = add_common(
        sub.add_parser("insert_image", help="그림 파일(PNG/JPG 등)을 본문 또는 표 칸에 삽입")
    )
    p_image.add_argument("path", help="넣을 그림 파일 경로")
    p_image.add_argument("--table", type=int, default=None, help="표 번호(0부터)")
    p_image.add_argument("--cell", default="", help="넣을 칸. 예: A2")
    p_image.add_argument(
        "--size-option",
        dest="size_option",
        type=int,
        default=3,
        choices=[0, 1, 2, 3],
        help="0=원본, 1=크기 지정, 2=셀 맞춤, 3=셀 맞춤·비율 유지(기본)",
    )
    p_image.add_argument("--width", dest="width_mm", type=float, default=0.0, help="너비(mm)")
    p_image.add_argument("--height", dest="height_mm", type=float, default=0.0, help="높이(mm)")

    p_text_box = add_common(
        sub.add_parser("insert_text_box", help="편집 가능한 글상자 삽입")
    )
    p_text_box.add_argument("text", help="글상자 안의 텍스트. 빈 글상자는 ''로 지정")
    p_text_box.add_argument("--width", dest="width_mm", type=float, required=True, help="너비(mm)")
    p_text_box.add_argument("--height", dest="height_mm", type=float, required=True, help="높이(mm)")
    p_text_box.add_argument(
        "--fill",
        default="",
        help="단색 색상 또는 JSON 채우기. 예: #D9EAF7 / '{\"type\":\"linear_gradient\",...}'",
    )
    p_text_box.add_argument(
        "--line",
        default="",
        help="테두리 JSON. 예: '{\"color\":\"#336699\",\"width_mm\":0.3}'",
    )
    p_text_box.add_argument(
        "--shadow",
        default="",
        help="도형 그림자 JSON. 예: '{\"color\":\"#000000\",\"alpha\":96,\"offset_x_mm\":1,\"offset_y_mm\":1}'",
    )
    p_text_box.add_argument(
        "--text-shadow",
        dest="text_shadow",
        default="",
        help="글자 그림자 JSON. 색·오프셋만 지원하며 alpha는 생략 또는 0",
    )
    p_text_box.add_argument(
        "--margin",
        default="none",
        help="글상자 안쪽 여백(mm). 현재 한/글 설치본에서 지원되지 않으면 명확히 실패; 기본 none",
    )
    p_text_box.add_argument(
        "--position",
        default="inline",
        help="inline 또는 floating 좌표 JSON. 예: '{\"mode\":\"floating\",\"x_mm\":10,\"y_mm\":20}'",
    )
    p_text_box.add_argument("--bold", action=argparse.BooleanOptionalAction, default=None)
    p_text_box.add_argument("--italic", action=argparse.BooleanOptionalAction, default=None)
    p_text_box.add_argument("--font", default="", help="글꼴 이름")
    p_text_box.add_argument("--size", type=float, default=None, help="글자 크기(pt)")
    p_text_box.add_argument("--align", default="center", choices=["left", "center", "right", "justify"])
    p_text_box.add_argument("--color", default="", help="글자색. 이름 또는 #RRGGBB")

    p_chart = add_common(
        sub.add_parser("insert_chart", help="표 데이터로 한/글 네이티브 차트 삽입 (그림 아님)")
    )
    p_chart.add_argument("--table", type=int, default=None, help="데이터 표 번호(0부터)")
    p_chart.add_argument("--range", dest="cell_range", default="", help="데이터 셀 범위. 예: A1:B10")
    p_chart.add_argument(
        "--type",
        dest="chart_type",
        default="line",
        choices=["line", "column", "bar", "pie"],
        help="차트 종류. 인생 그래프는 line(꺾은선)",
    )
    p_chart.add_argument("--index", dest="chart_index", type=int, default=0, help="그룹 내 레이아웃 번호")
    p_chart.add_argument(
        "--no-dialog",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="데이터 편집 대화상자 띄우지 않기 (한글 2022 이상)",
    )

    p_fill = add_common(sub.add_parser("fill_cells", help="표 셀 채우기"))
    p_fill.add_argument("--table", type=int, default=0, help="표 번호 (0부터)")
    p_fill.add_argument(
        "--cells",
        default="",
        help='JSON 2차원 배열 또는 {"A1":"값"} 객체',
    )
    p_fill.add_argument(
        "--cell",
        action="append",
        default=[],
        metavar="ADDR=TEXT",
        help="개별 셀. 여러 번 지정 가능. 예: --cell A1=항목",
    )

    p_write_cell = add_common(
        sub.add_parser("write_cell", help="표 셀 내용을 구조화 문단·글자 런으로 교체")
    )
    p_write_cell.add_argument("--table", type=int, required=True, help="표 번호(0부터)")
    p_write_cell.add_argument("--cell", required=True, help="셀 주소. 예: A1")
    p_write_cell.add_argument(
        "--paragraphs",
        required=True,
        help="text/runs/paragraph 문단 객체의 JSON 배열",
    )

    add_common(
        sub.add_parser(
            "exit_table",
            help="현재 표의 마지막 셀에서 일반 본문으로 이동 (MoveRight 후 셀 밖 검증)",
        )
    )

    p_cell_fill = add_common(
        sub.add_parser("set_cell_fill", help="표 셀 범위에 단색/선형 그라데이션 채우기")
    )
    p_cell_fill.add_argument(
        "--fill",
        required=True,
        help="단색 색상 또는 JSON 채우기. 예: #D9D9D9 / '{\"type\":\"linear_gradient\",...}'",
    )
    p_cell_fill.add_argument("--table", type=int, default=None, help="표 번호(0부터)")
    p_cell_fill.add_argument("--range", dest="cell_range", default="", help="셀 범위. 예: A1:D4")

    p_layout = add_common(
        sub.add_parser(
            "layout_review",
            help="표를 채운 뒤 항상 실행: 줄바꿈·행 높이·본문 폭·쪽 수 검토/수정",
        )
    )
    p_layout.add_argument("--table", type=int, default=None, help="표 번호(0부터). 없으면 모든 표")
    p_layout.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 너비/높이를 바꾸지 않고 계획만 JSON으로 출력",
    )

    p_fmt = add_common(sub.add_parser("set_format", help="서식 적용"))
    p_fmt.add_argument("--bold", action=argparse.BooleanOptionalAction, default=None)
    p_fmt.add_argument("--italic", action=argparse.BooleanOptionalAction, default=None)
    p_fmt.add_argument("--font", default="", help="글꼴 이름")
    p_fmt.add_argument("--size", type=float, default=None, help="글자 크기(pt)")
    p_fmt.add_argument("--align", default="", choices=["", "left", "center", "right", "justify"])
    p_fmt.add_argument("--color", default="", help="글자색. 이름 또는 #RRGGBB")
    p_fmt.add_argument("--fill", default="", help="셀 배경색 또는 채우기 JSON")
    p_fmt.add_argument(
        "--text-shadow",
        dest="text_shadow",
        default="",
        help="글자 그림자 JSON. 예: '{\"color\":\"#000000\",\"offset_x_mm\":1,\"offset_y_mm\":1}' (alpha 미지원)",
    )
    p_fmt.add_argument("--table", type=int, default=None)
    p_fmt.add_argument("--row", type=int, default=None, help="1부터. 표의 해당 행")
    p_fmt.add_argument("--range", dest="cell_range", default="", help="셀 범위. 예: A1:D1")

    p_style = add_common(sub.add_parser("set_style", help="현재 문단에 문서 스타일 적용"))
    p_style.add_argument("style", help='스타일 이름. 예: "개요 1"')

    p_repl = add_common(sub.add_parser("replace_selection", help="선택 영역 교체"))
    p_repl.add_argument("text")

    add_common(sub.add_parser("undo", help="직전 명령을 한 덩어리로 되돌리기"))

    p_page = add_common(sub.add_parser("page", help="쪽 읽기 또는 이동"))
    p_page.add_argument("--goto", type=int, default=None, metavar="N", help="1부터")
    p_page.add_argument(
        "--break",
        dest="break_page",
        action="store_true",
        help="캐럿 위치에서 BreakPage로 쪽 나누기",
    )

    p_page_number = add_common(
        sub.add_parser("set_page_number", help="네이티브 쪽 번호 위치와 구분 문자 설정")
    )
    p_page_number.add_argument(
        "--position",
        default="bottom_center",
        choices=[
            "top_left",
            "top_center",
            "top_right",
            "bottom_left",
            "bottom_center",
            "bottom_right",
        ],
        help="쪽 번호 위치",
    )
    p_page_number.add_argument(
        "--separator",
        default="-",
        help="숫자 양쪽에 넣을 한 글자 구분 문자. 빈 문자열이면 생략",
    )

    p_page_visibility = add_common(
        sub.add_parser("set_page_visibility", help="현재 쪽의 머리말·꼬리말·쪽 번호 등 숨기기")
    )
    p_page_visibility.add_argument(
        "--hide-header",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="머리말 숨기기",
    )
    p_page_visibility.add_argument(
        "--hide-footer",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="꼬리말 숨기기",
    )
    p_page_visibility.add_argument(
        "--hide-master-page",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="바탕쪽 숨기기",
    )
    p_page_visibility.add_argument(
        "--hide-border",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="쪽 테두리 숨기기",
    )
    p_page_visibility.add_argument(
        "--hide-fill",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="쪽 채우기 숨기기",
    )
    p_page_visibility.add_argument(
        "--hide-page-num",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="쪽 번호 숨기기",
    )

    p_restart_page_number = add_common(
        sub.add_parser("restart_page_number", help="현재 위치부터 네이티브 쪽 번호 다시 시작")
    )
    p_restart_page_number.add_argument(
        "--number",
        type=int,
        default=1,
        help="새 시작 번호(1~999999, 기본 1)",
    )

    p_pagedef = add_common(sub.add_parser("set_pagedef", help="용지 크기·여백·가로/세로 지정"))
    p_pagedef.add_argument("--paper-width", type=float, default=None, help="용지 폭(mm)")
    p_pagedef.add_argument("--paper-height", type=float, default=None, help="용지 길이(mm)")
    p_pagedef.add_argument("--left", type=float, default=None, help="왼쪽 여백(mm)")
    p_pagedef.add_argument("--right", type=float, default=None, help="오른쪽 여백(mm)")
    p_pagedef.add_argument("--top", type=float, default=None, help="위쪽 여백(mm)")
    p_pagedef.add_argument("--bottom", type=float, default=None, help="아래쪽 여백(mm)")
    p_pagedef.add_argument("--header", type=float, default=None, help="머리말 여백(mm)")
    p_pagedef.add_argument("--footer", type=float, default=None, help="꼬리말 여백(mm)")
    p_pagedef.add_argument("--gutter", type=float, default=None, help="제본 여백(mm)")
    p_pagedef.add_argument(
        "--landscape",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="가로 방향(--landscape) 또는 세로 방향(--no-landscape)",
    )
    p_pagedef.add_argument(
        "--apply",
        choices=["current", "all", "new"],
        default="current",
        help="현재 구역, 모든 구역, 새 구역 적용",
    )

    p_save_as = add_common(
        sub.add_parser("save_as", help="새 경로로 저장 (기존 파일은 --overwrite 필수)")
    )
    p_save_as.add_argument("path")
    p_save_as.add_argument("--format", default="", help="HWP, HWPX, PDF 등. 확장자로 추정")
    p_save_as.add_argument(
        "--overwrite",
        action="store_true",
        help="원본이 아닌 기존 대상 파일을 덮어씁니다. 없으면 거부합니다.",
    )

    p_save = add_common(sub.add_parser("save", help="원본에 저장 — --overwrite 필수"))
    p_save.add_argument(
        "--overwrite",
        action="store_true",
        help="원본 파일을 덮어씁니다. 없으면 거부합니다.",
    )

    p_close = add_common(sub.add_parser("close", help="문서 닫기 — --force 필수"))
    p_close.add_argument("--force", action="store_true", help="저장하지 않고 닫기")

    p_close_all = add_common(
        sub.add_parser("close_all", help="열려 있는 모든 한/글 문서 닫기 — --force 필수")
    )
    p_close_all.add_argument("--force", action="store_true", help="저장하지 않고 모든 문서 닫기")

    p_hwpx_status = add_common(
        sub.add_parser(
            "hwpx_status",
            help="python-hwpx 상태·선택적 .hwpx 요약 (한글 불필요)",
        )
    )
    p_hwpx_status.add_argument("path", nargs="?", help=".hwpx 경로. 없으면 라이브러리 상태만")

    p_hwpx_inspect = add_common(
        sub.add_parser(
            "hwpx_inspect",
            help=".hwpx 문단·런·셀 서식 그룹 읽기 (한글 불필요)",
        )
    )
    p_hwpx_inspect.add_argument("path", help=".hwpx 경로")

    p_mcp = add_common(sub.add_parser("mcp", help="MCP 서버 (stdio 또는 localhost HTTP)"))
    p_mcp.add_argument("--http", action="store_true", help="streamable HTTP 를 localhost 에 바인드")
    p_mcp.add_argument("--host", default="127.0.0.1")
    p_mcp.add_argument("--port", type=int, default=18765)
    p_mcp.add_argument("--token", default="", help="HTTP 토큰. 없으면 HWPCTL_TOKEN")
    p_mcp.add_argument("--list-tools", action="store_true", help="도구 목록만 출력 (한/글 불필요)")

    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def parse_cells_json(raw: str) -> Any:
    """fill_cells --cells 값을 파이썬 객체로."""
    if not raw or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"--cells JSON 을 해석할 수 없습니다: {exc}") from exc


def parse_cell_assignments(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise argparse.ArgumentTypeError(f"--cell 는 ADDR=TEXT 형식이어야 합니다: {item}")
        addr, text = item.split("=", 1)
        addr = addr.strip()
        if not addr:
            raise argparse.ArgumentTypeError(f"--cell 주소가 비었습니다: {item}")
        out[addr] = text
    return out


def parse_json_or_raw(raw: str | None) -> Any:
    """구조화 서식 CLI 값은 JSON, 간단한 색/inline 값은 문자열로 보존한다.

    ``--fill #D9D9D9`` 처럼 짧은 값은 모델이 자주 쓰므로 JSON만 강제하지 않는다.
    실제 형식·범위 검증은 CLI와 MCP가 동일하게 Engine에서 수행한다.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def known_commands() -> list[str]:
    return tool_names() + ["mcp"]


def command_is_destructive(command: str) -> bool:
    for spec in TOOLS:
        if spec.name == command:
            return spec.destructive
    return False
