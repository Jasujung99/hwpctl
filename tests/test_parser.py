from __future__ import annotations

import pytest

from hwpctl.cli import _kwargs_for
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
        "list_documents",
        "open",
        "snapshot",
        "format_paragraph_by_text",
        "recreate_inline_table_before_paragraph",
        "trim_blank_paragraphs_before_body",
        "insert_title",
        "insert_paragraph",
        "create_table",
        "set_table_properties",
        "set_table_position",
        "fill_cells",
        "write_cell",
        "exit_table",
        "layout_review",
        "set_cell_margin",
        "set_col_width",
        "get_col_width",
        "set_row_height",
        "get_row_height",
        "merge_cells",
        "set_valign",
        "set_cell_border",
        "insert_image",
        "insert_text_box",
        "set_cell_fill",
        "insert_chart",
        "set_format",
        "set_style",
        "replace_selection",
        "undo",
        "page",
        "set_page_number",
        "set_page_visibility",
        "restart_page_number",
        "set_pagedef",
        "save_as",
        "close_all",
        "hwpx_status",
        "hwpx_inspect",
    ):
        assert required in names
    assert "mcp" in known_commands()


def test_status_parse() -> None:
    ns = parse_args(["status"])
    assert ns.command == "status"


def test_list_documents_parse_and_cli_kwargs() -> None:
    ns = parse_args(["list_documents"])
    assert ns.command == "list_documents"
    assert _kwargs_for(ns) == {}


def test_open_new_and_path() -> None:
    ns = parse_args(["open", "--new"])
    assert ns.new is True
    assert ns.path is None
    ns = parse_args(["open", "C:/docs/a.hwp", "--discard"])
    assert ns.path.endswith("a.hwp")
    assert ns.discard is True


def test_close_all_parse_and_cli_kwargs() -> None:
    ns = parse_args(["close_all", "--force"])
    assert _kwargs_for(ns) == {"force": True}


def test_insert_title_and_paragraph() -> None:
    ns = parse_args(["insert_title", "사업계획서", "--size", "22"])
    assert ns.text == "사업계획서"
    assert ns.size == 22
    ns = parse_args(["insert_paragraph", "본문입니다."])
    assert ns.text == "본문입니다."


def test_format_paragraph_by_text_cli_kwargs() -> None:
    ns = parse_args(
        [
            "format_paragraph_by_text",
            "--text",
            " ◦ 본문입니다. ",
            "--font",
            "휴먼명조",
            "--size",
            "15",
            "--no-bold",
            "--paragraph",
            '{"align":"justify","line_spacing_percent":155}',
            "--dry-run",
        ]
    )
    assert _kwargs_for(ns) == {
        "text": " ◦ 본문입니다. ",
        "font": "휴먼명조",
        "size": 15.0,
        "bold": False,
        "italic": None,
        "color": "",
        "letter_spacing_percent": None,
        "width_scale_percent": None,
        "paragraph": {"align": "justify", "line_spacing_percent": 155},
        "occurrence": 1,
        "dry_run": True,
    }


def test_recreate_inline_table_before_paragraph_cli_kwargs() -> None:
    ns = parse_args(
        [
            "recreate_inline_table_before_paragraph",
            "--old-table",
            "11",
            "--expected-table-text",
            "Q. 질문",
            "--before-text",
            " ◦ 답변",
            "--table-spec",
            '{"kind":"table","rows":1}',
            "--blank-paragraph",
            '{"kind":"paragraph","runs":[{"text":""}]}',
            "--dry-run",
        ]
    )
    assert _kwargs_for(ns) == {
        "old_table": 11,
        "expected_table_text": "Q. 질문",
        "before_text": " ◦ 답변",
        "table_spec": {"kind": "table", "rows": 1},
        "blank_paragraph": {"kind": "paragraph", "runs": [{"text": ""}]},
        "dry_run": True,
    }


def test_trim_blank_paragraphs_before_body_cli_kwargs() -> None:
    ns = parse_args(
        [
            "trim_blank_paragraphs_before_body",
            "--text",
            " ◦ 답변",
            "--keep",
            "1",
            "--dry-run",
        ]
    )
    assert _kwargs_for(ns) == {"text": " ◦ 답변", "keep": 1, "dry_run": True}


def test_structured_paragraph_and_write_cell_cli_kwargs() -> None:
    paragraph = parse_args(
        [
            "insert_paragraph",
            "--runs",
            '[{"text":"Q. ","bold":true,"superscript":true,"underline":{"enabled":true,"type":"bottom","shape":"solid","color":"#112233"},"strikeout":{"enabled":true,"type":"continuous","shape":"solid","color":"#445566"},"kerning":true,"letter_spacing_percent":-3},{"text":"답변"}]',
            "--paragraph",
            '{"align":"justify","first_line_indent_mm":-8,"line_spacing_percent":150,"break_latin_word":"keep_word","break_non_latin_word":"break_word"}',
            "--page-break-before",
        ]
    )
    assert paragraph.text == ""
    assert _kwargs_for(paragraph) == {
        "text": "",
        "runs": [
            {
                "text": "Q. ",
                "bold": True,
                "superscript": True,
                "underline": {
                    "enabled": True,
                    "type": "bottom",
                    "shape": "solid",
                    "color": "#112233",
                },
                "strikeout": {
                    "enabled": True,
                    "type": "continuous",
                    "shape": "solid",
                    "color": "#445566",
                },
                "kerning": True,
                "letter_spacing_percent": -3,
            },
            {"text": "답변"},
        ],
        "paragraph": {
            "align": "justify",
            "first_line_indent_mm": -8,
            "line_spacing_percent": 150,
            "break_latin_word": "keep_word",
            "break_non_latin_word": "break_word",
        },
        "page_break_before": True,
    }

    cell = parse_args(
        [
            "write_cell",
            "--table",
            "2",
            "--cell",
            "B3",
            "--paragraphs",
            '[{"runs":[{"text":"항목","bold":true}],"paragraph":{"align":"center"}}]',
        ]
    )
    assert _kwargs_for(cell) == {
        "table": 2,
        "cell": "B3",
        "paragraphs": [
            {
                "runs": [{"text": "항목", "bold": True}],
                "paragraph": {"align": "center"},
            }
        ],
    }


def test_set_page_number_cli_kwargs() -> None:
    ns = parse_args(["set_page_number", "--position", "bottom_center", "--separator", "-"])
    assert _kwargs_for(ns) == {"position": "bottom_center", "separator": "-"}


def test_page_visibility_and_restart_cli_kwargs() -> None:
    visibility = parse_args(
        [
            "set_page_visibility",
            "--hide-header",
            "--hide-master-page",
            "--hide-page-num",
            "--no-hide-fill",
        ]
    )
    assert _kwargs_for(visibility) == {
        "hide_header": True,
        "hide_footer": False,
        "hide_master_page": True,
        "hide_border": False,
        "hide_fill": False,
        "hide_page_num": True,
    }

    restart = parse_args(["restart_page_number", "--number", "7"])
    assert _kwargs_for(restart) == {"number": 7}


def test_create_table_header_fill() -> None:
    ns = parse_args(["create_table", "--rows", "8", "--cols", "4", "--header-fill", "gray"])
    assert ns.rows == 8
    assert ns.cols == 4
    assert ns.header_fill == "gray"
    assert ns.no_header is False
    assert ns.cell_padding == "3.5,2.0"  # 새 표 기본 칸 안여백(mm)


def test_table_properties_and_position_cli_kwargs() -> None:
    properties = parse_args(
        [
            "set_table_properties",
            "--table",
            "2",
            "--page-break",
            "table",
            "--no-repeat-header",
            "--cell-spacing-mm",
            "0.7",
        ]
    )
    assert _kwargs_for(properties) == {
        "table": 2,
        "page_break": "table",
        "repeat_header": False,
        "cell_spacing_mm": 0.7,
    }

    position = parse_args(
        [
            "set_table_position",
            "--table",
            "2",
            "--position",
            '{"mode":"floating","horizontal_relative_to":"para","vertical_relative_to":"para","horizontal_align":"left","vertical_align":"top","x_mm":0.025,"y_mm":1.609,"wrap":"top_and_bottom","flow_with_text":true,"allow_overlap":false,"outside_margin_mm":[0.5,0.5,0.5,0.5]}',
        ]
    )
    assert _kwargs_for(position) == {
        "table": 2,
        "position": {
            "mode": "floating",
            "horizontal_relative_to": "para",
            "vertical_relative_to": "para",
            "horizontal_align": "left",
            "vertical_align": "top",
            "x_mm": 0.025,
            "y_mm": 1.609,
            "wrap": "top_and_bottom",
            "flow_with_text": True,
            "allow_overlap": False,
            "outside_margin_mm": [0.5, 0.5, 0.5, 0.5],
        },
    }


def test_exit_table_parse_and_cli_kwargs() -> None:
    ns = parse_args(["exit_table"])
    assert ns.command == "exit_table"
    assert _kwargs_for(ns) == {}


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


def test_visual_format_cli_parses_structured_specs_and_preserves_default_margin() -> None:
    text_box = parse_args(
        [
            "insert_text_box",
            "문의 안내",
            "--width",
            "118",
            "--height",
            "23.5",
            "--fill",
            '{"type":"linear_gradient","angle":90,"stops":[{"offset":0,"color":"#004A99"},{"offset":1,"color":"#00A7C6"}]}',
            "--line",
            '{"type":"solid","color":"#113355","width_mm":0.3}',
            "--shadow",
            '{"type":"offset","color":"#000000","alpha":96,"offset_x_mm":1,"offset_y_mm":1}',
            "--text-shadow",
            '{"type":"offset","color":"#101010","alpha":0,"offset_x_mm":0.5,"offset_y_mm":0}',
            "--position",
            '{"mode":"floating","x_mm":10,"y_mm":20}',
            "--bold",
            "--font",
            "함초롬돋움",
            "--size",
            "16",
            "--color",
            "#FFFFFF",
        ]
    )
    assert text_box.command == "insert_text_box"
    assert text_box.margin == "none"
    text_box_kwargs = _kwargs_for(text_box)
    assert text_box_kwargs["fill"] == {
        "type": "linear_gradient",
        "angle": 90,
        "stops": [
            {"offset": 0, "color": "#004A99"},
            {"offset": 1, "color": "#00A7C6"},
        ],
    }
    assert text_box_kwargs["line"]["width_mm"] == 0.3
    assert text_box_kwargs["text_shadow"]["alpha"] == 0
    assert text_box_kwargs["margin"] == "none"
    assert text_box_kwargs["position"] == {"mode": "floating", "x_mm": 10, "y_mm": 20}

    cell_fill = parse_args(
        [
            "set_cell_fill",
            "--table",
            "2",
            "--range",
            "A1:B3",
            "--fill",
            '#123456',
        ]
    )
    assert _kwargs_for(cell_fill) == {
        "fill": "#123456",
        "table": 2,
        "cell_range": "A1:B3",
    }

    text_format = parse_args(
        [
            "set_format",
            "--text-shadow",
            '{"type":"offset","color":"#000000","alpha":1}',
        ]
    )
    # CLI는 구조를 충실히 전달하고, 한/글 2022 제한(alpha=0)은 Engine이
    # CLI/MCP 공통으로 검증한다.
    assert _kwargs_for(text_format)["text_shadow"] == {
        "type": "offset",
        "color": "#000000",
        "alpha": 1,
    }


def test_table_size_merge_valign_and_border_parse() -> None:
    col = parse_args(
        ["set_col_width", "--table", "0", "--widths", "1,2,1", "--unit", "ratio"]
    )
    assert col.widths == "1,2,1"
    assert col.unit == "ratio"
    assert parse_args(["get_col_width", "--table", "0", "--column", "2"]).column == 2

    row = parse_args(["set_row_height", "--height", "12.5", "--table", "0", "--row", "2"])
    assert row.height == 12.5
    assert parse_args(["get_row_height", "--row", "3"]).row == 3

    merge = parse_args(["merge_cells", "--table", "0", "--range", "A1:B2"])
    assert merge.cell_range == "A1:B2"
    valign = parse_args(["set_valign", "bottom", "--table", "0", "--range", "A1:A2"])
    assert valign.align == "bottom"
    border = parse_args(
        [
            "set_cell_border",
            "--sides",
            "left,bottom",
            "--line-type",
            "Solid",
            "--width",
            "0.12mm",
            "--color",
            "#112233",
        ]
    )
    assert border.sides == "left,bottom"
    assert border.line_type == "Solid"


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


def test_layout_review_parse_defaults_and_dry_run() -> None:
    ns = parse_args(["layout_review"])
    assert ns.table is None
    assert ns.dry_run is False
    ns = parse_args(["layout_review", "--table", "2", "--dry-run"])
    assert ns.table == 2
    assert ns.dry_run is True


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
    assert ns.overwrite is False
    assert _kwargs_for(ns) == {"path": "out.hwpx", "format": "HWPX", "overwrite": False}
    overwrite = parse_args(["save_as", "out.hwpx", "--overwrite"])
    assert overwrite.overwrite is True
    assert _kwargs_for(overwrite)["overwrite"] is True
    ns = parse_args(["page", "--goto", "3"])
    assert ns.goto == 3
    assert ns.break_page is False
    assert parse_args(["page", "--break"]).break_page is True


def test_style_and_pagedef_parse() -> None:
    style = parse_args(["set_style", "개요 1"])
    assert style.style == "개요 1"
    page = parse_args(
        [
            "set_pagedef",
            "--paper-width",
            "210",
            "--paper-height",
            "297",
            "--left",
            "20",
            "--landscape",
            "--apply",
            "all",
        ]
    )
    assert page.paper_width == 210
    assert page.landscape is True
    assert page.apply == "all"


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
    assert by_name["save_as"]["destructive"] is True
    assert by_name["insert_title"]["write"] is True
    assert by_name["snapshot"]["write"] is False
    assert by_name["list_documents"]["write"] is False
    assert by_name["list_documents"]["destructive"] is False
    assert by_name["set_table_properties"]["write"] is True
    assert by_name["set_table_position"]["write"] is True
    assert by_name["set_page_visibility"]["write"] is True
    assert by_name["restart_page_number"]["write"] is True
    assert by_name["exit_table"]["write"] is False
    assert by_name["exit_table"]["destructive"] is False
    assert by_name["hwpx_status"]["write"] is False
    assert by_name["hwpx_inspect"]["write"] is False
    assert by_name["hwpx_inspect"]["destructive"] is False
