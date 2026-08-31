from __future__ import annotations

import pytest

from hwpctl.parser import (
    build_parser,
    known_commands,
    parse_args,
    parse_cell_assignments,
    parse_cells_json,
)
from hwpctl.tools import tool_catalog, tool_names


def test_required_commands_exist() -> None:
    names = set(tool_names())
    for required in (
        "status",
        "open",
        "snapshot",
        "insert_title",
        "insert_paragraph",
        "create_table",
        "fill_cells",
        "set_cell_margin",
        "insert_chart",
        "set_format",
        "replace_selection",
        "undo",
        "page",
        "save_as",
    ):
        assert required in names
    assert "mcp" in known_commands()


def test_status_parse() -> None:
    ns = parse_args(["status"])
    assert ns.command == "status"


def test_open_new_and_path() -> None:
    ns = parse_args(["open", "--new"])
    assert ns.new is True
    assert ns.path is None
    ns = parse_args(["open", "C:/docs/a.hwp", "--discard"])
    assert ns.path.endswith("a.hwp")
    assert ns.discard is True


def test_insert_title_and_paragraph() -> None:
    ns = parse_args(["insert_title", "사업계획서", "--size", "22"])
    assert ns.text == "사업계획서"
    assert ns.size == 22
    ns = parse_args(["insert_paragraph", "본문입니다."])
    assert ns.text == "본문입니다."


def test_create_table_header_fill() -> None:
    ns = parse_args(["create_table", "--rows", "8", "--cols", "4", "--header-fill", "gray"])
    assert ns.rows == 8
    assert ns.cols == 4
    assert ns.header_fill == "gray"
    assert ns.no_header is False
    assert ns.cell_padding == "3.5,2.0"  # 새 표 기본 칸 안여백(mm)


def test_create_table_cell_padding_override() -> None:
    ns = parse_args(["create_table", "--rows", "2", "--cols", "2", "--cell-padding", "none"])
    assert ns.cell_padding == "none"


def test_set_cell_margin_parse() -> None:
    ns = parse_args(
        ["set_cell_margin", "--table", "0", "--range", "A1:D4", "--left", "4", "--top", "1.5"]
    )
    assert ns.command == "set_cell_margin"
    assert ns.table == 0
    assert ns.cell_range == "A1:D4"
    assert ns.left == 4.0
    assert ns.right == 3.5  # 기본값
    assert ns.top == 1.5
    assert ns.bottom == 2.0


def test_insert_chart_parse() -> None:
    ns = parse_args(["insert_chart", "--table", "0", "--type", "line"])
    assert ns.command == "insert_chart"
    assert ns.chart_type == "line"
    assert ns.chart_index == 0
    assert ns.no_dialog is True  # 대화상자 금지가 기본
    ns = parse_args(["insert_chart", "--table", "1", "--type", "pie", "--range", "A1:B5"])
    assert ns.cell_range == "A1:B5"
    with pytest.raises(SystemExit):
        parse_args(["insert_chart", "--type", "donut"])


def test_debug_and_lock_timeout_after_subcommand() -> None:
    # (#16) 서브커맨드 뒤에서도 동작해야 한다
    ns = parse_args(["status", "--debug"])
    assert ns.debug is True
    ns = parse_args(["status"])
    assert ns.debug is False
    ns = parse_args(["insert_paragraph", "본문", "--lock-timeout", "2"])
    assert ns.lock_timeout == 2.0
    ns = parse_args(["--debug", "status"])  # 앞에 둬도 여전히 동작
    assert ns.debug is True


def test_fill_cells_json_and_assignments() -> None:
    ns = parse_args(
        [
            "fill_cells",
            "--table",
            "0",
            "--cells",
            '[["항목","내용"]]',
            "--cell",
            "A2=목표",
        ]
    )
    assert parse_cells_json(ns.cells) == [["항목", "내용"]]
    assert parse_cell_assignments(ns.cell) == {"A2": "목표"}


def test_fill_cells_bad_json() -> None:
    ns = parse_args(["fill_cells", "--cells", "{not-json"])
    with pytest.raises(Exception):
        parse_cells_json(ns.cells)


def test_cell_assignment_requires_equals() -> None:
    with pytest.raises(Exception):
        parse_cell_assignments(["A1"])


def test_set_format_flags() -> None:
    ns = parse_args(
        [
            "set_format",
            "--bold",
            "--font",
            "함초롬돋움",
            "--size",
            "12",
            "--align",
            "center",
            "--table",
            "0",
            "--row",
            "1",
            "--fill",
            "gray",
        ]
    )
    assert ns.bold is True
    assert ns.font == "함초롬돋움"
    assert ns.row == 1


def test_save_requires_overwrite_flag_default_false() -> None:
    ns = parse_args(["save"])
    assert ns.overwrite is False
    ns = parse_args(["save", "--overwrite"])
    assert ns.overwrite is True


def test_close_requires_force_flag_default_false() -> None:
    ns = parse_args(["close"])
    assert ns.force is False
    ns = parse_args(["close", "--force"])
    assert ns.force is True


def test_save_as_and_page() -> None:
    ns = parse_args(["save_as", "out.hwpx", "--format", "HWPX"])
    assert ns.path == "out.hwpx"
    ns = parse_args(["page", "--goto", "3"])
    assert ns.goto == 3


def test_mcp_http_options() -> None:
    ns = parse_args(["mcp", "--http", "--port", "18765", "--list-tools"])
    assert ns.http is True
    assert ns.port == 18765
    assert ns.list_tools is True


def test_unknown_command_exits() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["not-a-command"])


def test_tool_catalog_marks_destructive() -> None:
    by_name = {t["name"]: t for t in tool_catalog()}
    assert by_name["save"]["destructive"] is True
    assert by_name["close"]["destructive"] is True
    assert by_name["save_as"]["destructive"] is False
    assert by_name["insert_title"]["write"] is True
    assert by_name["snapshot"]["write"] is False