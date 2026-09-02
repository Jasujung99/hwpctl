"""hwpctl 엔트리. 오류는 한국어 한 줄, 성공은 JSON."""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Sequence

from argparse import ArgumentTypeError

from hwpctl.errors import HwpctlError, UsageError
from hwpctl.parser import parse_args, parse_cell_assignments, parse_cells_json, parse_json_or_raw
from hwpctl.tools import tool_catalog

HWPX_COMMANDS = frozenset({"hwpx_status", "hwpx_inspect"})


def main(argv: Sequence[str] | None = None) -> int:
    # JSON CLI/MCP 스트림은 운영체제 콘솔 코드페이지가 아니라 UTF-8 계약이다.
    # 한/글 문서에는 CP949에 없는 U+25E6 같은 문자가 있으므로, locale 인코딩을
    # 보존하면 JSON 전송 자체가 실패하거나 호출자마다 깨진 텍스트가 된다.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="strict")
        except Exception:
            pass
    try:
        args = parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        code = exc.code
        return 0 if code in (0, None) else int(code)

    debug = bool(getattr(args, "debug", False))
    try:
        if args.command == "mcp":
            return _run_mcp(args)
        if args.command in HWPX_COMMANDS:
            payload = _run_hwpx(args)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        payload = _run_engine(args)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except HwpctlError as exc:
        print(exc.message, file=sys.stderr)
        if debug:
            traceback.print_exc()
        return exc.exit_code
    except Exception:
        print(
            "내부 오류가 발생했습니다. --debug 로 다시 실행하면 자세한 내용을 볼 수 있습니다.",
            file=sys.stderr,
        )
        if debug:
            traceback.print_exc()
        return 1


def _run_hwpx(args: Any) -> dict[str, Any]:
    """``.hwpx`` 읽기. Engine/COM/SingleWriterLock 을 거치지 않는다."""

    from hwpctl.hwpx.commands import dispatch_hwpx

    return dispatch_hwpx(args.command, path=getattr(args, "path", None))


def _run_engine(args: Any) -> dict[str, Any]:
    from hwpctl.engine import Engine

    engine = Engine(lock_timeout=float(args.lock_timeout))
    kwargs = _kwargs_for(args)
    return engine.dispatch(args.command, **kwargs)


def _kwargs_for(args: Any) -> dict[str, Any]:
    try:
        return _kwargs_for_inner(args)
    except ArgumentTypeError as exc:
        raise UsageError(str(exc)) from exc


def _kwargs_for_inner(args: Any) -> dict[str, Any]:
    cmd = args.command
    if cmd == "list_documents":
        return {}
    if cmd == "open":
        return {"path": args.path, "new": args.new, "discard": args.discard}
    if cmd == "format_paragraph_by_text":
        return {
            "text": args.text,
            "font": args.font,
            "size": args.size,
            "bold": args.bold,
            "italic": args.italic,
            "color": args.color,
            "letter_spacing_percent": args.letter_spacing_percent,
            "width_scale_percent": args.width_scale_percent,
            "paragraph": parse_json_or_raw(args.paragraph),
            "occurrence": args.occurrence,
            "dry_run": args.dry_run,
        }
    if cmd == "recreate_inline_table_before_paragraph":
        return {
            "old_table": args.old_table,
            "expected_table_text": args.expected_table_text,
            "before_text": args.before_text,
            "table_spec": parse_json_or_raw(args.table_spec),
            "blank_paragraph": parse_json_or_raw(args.blank_paragraph),
            "dry_run": args.dry_run,
        }
    if cmd == "trim_blank_paragraphs_before_body":
        return {"text": args.text, "keep": args.keep, "dry_run": args.dry_run}
    if cmd == "insert_title":
        return {"text": args.text, "size": args.size}
    if cmd == "insert_paragraph":
        return {
            "text": args.text,
            "runs": parse_json_or_raw(args.runs),
            "paragraph": parse_json_or_raw(args.paragraph),
            "page_break_before": args.page_break_before,
        }
    if cmd == "create_table":
        return {
            "rows": args.rows,
            "cols": args.cols,
            "header_fill": args.header_fill,
            "header": not args.no_header,
            "cell_margin": args.cell_padding,
        }
    if cmd == "set_table_properties":
        return {
            "table": args.table,
            "page_break": args.page_break,
            "repeat_header": args.repeat_header,
            "cell_spacing_mm": args.cell_spacing_mm,
        }
    if cmd == "set_table_position":
        return {
            "table": args.table,
            "position": parse_json_or_raw(args.position),
        }
    if cmd == "set_cell_margin":
        return {
            "table": args.table,
            "cell_range": args.cell_range,
            "left": args.left,
            "right": args.right,
            "top": args.top,
            "bottom": args.bottom,
        }
    if cmd == "set_col_width":
        return {
            "widths": args.widths,
            "table": args.table,
            "column": args.column,
            "unit": args.unit,
        }
    if cmd == "get_col_width":
        return {"table": args.table, "column": args.column}
    if cmd == "set_row_height":
        return {"height": args.height, "table": args.table, "row": args.row}
    if cmd == "get_row_height":
        return {"table": args.table, "row": args.row}
    if cmd == "merge_cells":
        return {"cell_range": args.cell_range, "table": args.table}
    if cmd == "set_valign":
        return {
            "align": args.align,
            "table": args.table,
            "cell_range": args.cell_range,
        }
    if cmd == "set_cell_border":
        return {
            "sides": args.sides,
            "line_type": args.line_type,
            "width": args.width,
            "color": args.color,
            "table": args.table,
            "cell_range": args.cell_range,
        }
    if cmd == "insert_image":
        return {
            "path": args.path,
            "table": args.table,
            "cell": args.cell,
            "size_option": args.size_option,
            "width_mm": args.width_mm,
            "height_mm": args.height_mm,
        }
    if cmd == "insert_text_box":
        return {
            "text": args.text,
            "width_mm": args.width_mm,
            "height_mm": args.height_mm,
            "fill": parse_json_or_raw(args.fill),
            "line": parse_json_or_raw(args.line),
            "shadow": parse_json_or_raw(args.shadow),
            "text_shadow": parse_json_or_raw(args.text_shadow),
            "margin": args.margin,
            "position": parse_json_or_raw(args.position),
            "bold": args.bold,
            "italic": args.italic,
            "font": args.font,
            "size": args.size,
            "align": args.align,
            "color": args.color,
        }
    if cmd == "insert_chart":
        return {
            "table": args.table,
            "cell_range": args.cell_range,
            "chart_type": args.chart_type,
            "chart_index": args.chart_index,
            "no_dialog": args.no_dialog,
        }
    if cmd == "fill_cells":
        return {
            "table": args.table,
            "cells": parse_cells_json(args.cells),
            "assignments": parse_cell_assignments(args.cell),
        }
    if cmd == "write_cell":
        return {
            "table": args.table,
            "cell": args.cell,
            "paragraphs": parse_json_or_raw(args.paragraphs),
        }
    if cmd == "exit_table":
        return {}
    if cmd == "set_cell_fill":
        return {
            "fill": parse_json_or_raw(args.fill),
            "table": args.table,
            "cell_range": args.cell_range,
        }
    if cmd == "layout_review":
        return {"table": args.table, "dry_run": args.dry_run}
    if cmd == "set_format":
        return {
            "bold": args.bold,
            "italic": args.italic,
            "font": args.font,
            "size": args.size,
            "align": args.align,
            "color": args.color,
            "fill": parse_json_or_raw(args.fill),
            "text_shadow": parse_json_or_raw(args.text_shadow),
            "table": args.table,
            "row": args.row,
            "cell_range": args.cell_range,
        }
    if cmd == "replace_selection":
        return {"text": args.text}
    if cmd == "set_style":
        return {"style": args.style}
    if cmd == "page":
        return {"goto": args.goto, "break_page": args.break_page}
    if cmd == "set_page_number":
        return {"position": args.position, "separator": args.separator}
    if cmd == "set_page_visibility":
        return {
            "hide_header": args.hide_header,
            "hide_footer": args.hide_footer,
            "hide_master_page": args.hide_master_page,
            "hide_border": args.hide_border,
            "hide_fill": args.hide_fill,
            "hide_page_num": args.hide_page_num,
        }
    if cmd == "restart_page_number":
        return {"number": args.number}
    if cmd == "set_pagedef":
        return {
            "paper_width": args.paper_width,
            "paper_height": args.paper_height,
            "left": args.left,
            "right": args.right,
            "top": args.top,
            "bottom": args.bottom,
            "header": args.header,
            "footer": args.footer,
            "gutter": args.gutter,
            "landscape": args.landscape,
            "apply": args.apply,
        }
    if cmd == "save_as":
        return {"path": args.path, "format": args.format, "overwrite": args.overwrite}
    if cmd == "save":
        return {"overwrite": args.overwrite}
    if cmd == "close":
        return {"force": args.force}
    if cmd == "close_all":
        return {"force": args.force}
    return {}


def _run_mcp(args: Any) -> int:
    if args.list_tools:
        print(json.dumps({"tools": tool_catalog()}, ensure_ascii=False, indent=2))
        return 0
    from hwpctl.mcp_server import run_mcp

    run_mcp(
        http=bool(args.http),
        host=str(args.host),
        port=int(args.port),
        token=str(args.token or ""),
        lock_timeout=float(args.lock_timeout),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
