"""hwpctl 엔트리. 오류는 한국어 한 줄, 성공은 JSON."""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Sequence

from argparse import ArgumentTypeError

from hwpctl.errors import HwpctlError, UsageError
from hwpctl.parser import parse_args, parse_cell_assignments, parse_cells_json
from hwpctl.tools import tool_catalog

HWPX_COMMANDS = frozenset({"hwpx_status", "hwpx_inspect"})


def main(argv: Sequence[str] | None = None) -> int:
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
    if cmd == "open":
        return {"path": args.path, "new": args.new, "discard": args.discard}
    if cmd == "insert_title":
        return {"text": args.text, "size": args.size}
    if cmd == "insert_paragraph":
        return {"text": args.text}
    if cmd == "create_table":
        return {
            "rows": args.rows,
            "cols": args.cols,
            "header_fill": args.header_fill,
            "header": not args.no_header,
            "cell_margin": args.cell_padding,
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
            "fill": args.fill,
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
        return {"path": args.path, "format": args.format}
    if cmd == "save":
        return {"overwrite": args.overwrite}
    if cmd == "close":
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