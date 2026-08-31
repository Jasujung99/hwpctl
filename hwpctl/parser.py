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

    p_status = sub.add_parser("status", help="열린 한/글 창 상태")
    p_status.add_argument("--json", action="store_true", default=True, help=argparse.SUPPRESS)

    p_open = sub.add_parser("open", help="새 문서 또는 파일 열기")
    p_open.add_argument("path", nargs="?", help="열 파일 경로. 없으면 빈 문서")
    p_open.add_argument("--new", action="store_true", help="기존 창에 붙지 않고 새 한/글 인스턴스")
    p_open.add_argument(
        "--discard",
        action="store_true",
        help="저장하지 않은 수정본을 버리고 엽니다 (파괴적)",
    )

    sub.add_parser("snapshot", help="제목·본문·표·선택 영역 스냅샷")

    p_title = sub.add_parser("insert_title", help="제목 문단 삽입")
    p_title.add_argument("text")
    p_title.add_argument("--size", type=float, default=20.0, help="글자 크기(pt)")

    p_para = sub.add_parser("insert_paragraph", help="본문 문단 삽입")
    p_para.add_argument("text")

    p_table = sub.add_parser("create_table", help="표 만들기")
    p_table.add_argument("--rows", type=int, required=True)
    p_table.add_argument("--cols", type=int, required=True)
    p_table.add_argument("--header-fill", default="", help="첫 행 배경색. 예: gray, #D9D9D9")
    p_table.add_argument("--no-header", action="store_true", help="1행을 제목행으로 두지 않음")

    p_fill = sub.add_parser("fill_cells", help="표 셀 채우기")
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

    p_fmt = sub.add_parser("set_format", help="서식 적용")
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

    p_repl = sub.add_parser("replace_selection", help="선택 영역 교체")
    p_repl.add_argument("text")

    sub.add_parser("undo", help="직전 명령을 한 덩어리로 되돌리기")

    p_page = sub.add_parser("page", help="쪽 읽기 또는 이동")
    p_page.add_argument("--goto", type=int, default=None, metavar="N", help="1부터")

    p_save_as = sub.add_parser("save_as", help="새 경로로 저장 (원본 유지)")
    p_save_as.add_argument("path")
    p_save_as.add_argument("--format", default="", help="HWP, HWPX, PDF 등. 확장자로 추정")

    p_save = sub.add_parser("save", help="원본에 저장 — --overwrite 필수")
    p_save.add_argument(
        "--overwrite",
        action="store_true",
        help="원본 파일을 덮어씁니다. 없으면 거부합니다.",
    )

    p_close = sub.add_parser("close", help="문서 닫기 — --force 필수")
    p_close.add_argument("--force", action="store_true", help="저장하지 않고 닫기")

    p_mcp = sub.add_parser("mcp", help="MCP 서버 (stdio 또는 localhost HTTP)")
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