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
    parser.add_argument(
        "--backend",
        choices=["auto", "hwpx", "hancom"],
        default="auto",
        help="문서 백엔드. auto 는 Windows 가 아니면 hwpx (한글 불필요)",
    )

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def add_common(sp: argparse.ArgumentParser) -> argparse.ArgumentParser:
        # 서브커맨드 뒤에서도 --debug / --lock-timeout 을 쓸 수 있게 한다.
        # SUPPRESS 기본값이라 미지정 시 루트 파서의 값이 유지된다.
        sp.add_argument("--debug", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        sp.add_argument("--lock-timeout", type=float, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        sp.add_argument(
            "--backend",
            choices=["auto", "hwpx", "hancom"],
            default=argparse.SUPPRESS,
            help=argparse.SUPPRESS,
        )
        return sp

    add_common(sub.add_parser("status", help="열린 한/글 창 상태"))

    p_open = add_common(sub.add_parser("open", help="새 문서 또는 파일 열기"))
    p_open.add_argument("path", nargs="?", help="열 파일 경로. 없으면 빈 문서")
    p_open.add_argument("--new", action="store_true", help="기존 창에 붙지 않고 새 한/글 인스턴스")
    p_open.add_argument(
        "--discard",
        action="store_true",
        help="저장하지 않은 수정본을 버리고 엽니다 (파괴적)",
    )

    add_common(sub.add_parser("snapshot", help="제목·본문·표·선택 영역 스냅샷"))

    p_title = add_common(sub.add_parser("insert_title", help="제목 문단 삽입"))
    p_title.add_argument("text")
    p_title.add_argument("--size", type=float, default=20.0, help="글자 크기(pt)")

    p_para = add_common(sub.add_parser("insert_paragraph", help="본문 문단 삽입"))
    p_para.add_argument("text")

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
    p_fmt.add_argument("--fill", default="", help="셀 배경색")
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

    p_save_as = add_common(sub.add_parser("save_as", help="새 경로로 저장 (원본 유지)"))
    p_save_as.add_argument("path")
    p_save_as.add_argument("--format", default="", help="HWP, HWPX, PDF 등. 확장자로 추정")

    p_save = add_common(sub.add_parser("save", help="원본에 저장 — --overwrite 필수"))
    p_save.add_argument(
        "--overwrite",
        action="store_true",
        help="원본 파일을 덮어씁니다. 없으면 거부합니다.",
    )

    p_close = add_common(sub.add_parser("close", help="문서 닫기 — --force 필수"))
    p_close.add_argument("--force", action="store_true", help="저장하지 않고 닫기")

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

    p_hwpx_compare = add_common(
        sub.add_parser(
            "hwpx_compare",
            help=".hwpx 쪽 비교(inspect JSON + 원본 PNG 시트, 한글 불필요)",
        )
    )
    p_hwpx_compare.add_argument("path", help="재현 .hwpx 경로")
    p_hwpx_compare.add_argument(
        "--orig-dir",
        default="",
        help="원본 PNG 디렉터리 (orig_p1.png …)",
    )
    p_hwpx_compare.add_argument(
        "--out-dir",
        dest="output_dir",
        default="",
        help="비교 산출물 디렉터리",
    )

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


def known_commands() -> list[str]:
    return tool_names() + ["mcp"]


def command_is_destructive(command: str) -> bool:
    for spec in TOOLS:
        if spec.name == command:
            return spec.destructive
    return False