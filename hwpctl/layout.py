"""표 레이아웃 검토 정책.

줄 수는 HangulCanvas가 KeyIndicator로 실측한다. 다만 한/글 2022 Automation에는
문자열의 조판 폭을 직접 반환하는 API가 없어, 줄바꿈을 없앨 목표 너비는 글자 크기와
유니코드 문자 폭으로 추정한다. 이 추정치는 한 번에 현재 열의 1.6배, 본문 폭의 45%를
넘지 않게 제한한다.
"""

from __future__ import annotations

import math
import unicodedata
from typing import Any

MM_PER_POINT = 25.4 / 72.0
MIN_WIDTH_CHANGE_MM = 0.5


def plan_table_layout(layout: dict[str, Any]) -> dict[str, Any]:
    """HangulCanvas 측정값에서 안전한 열/행 변경 계획을 만든다."""
    widths = [float(v) for v in layout.get("column_widths_mm", [])]
    cells = list(layout.get("cells", []))
    max_width = float(layout.get("max_table_width_mm", sum(widths)))
    table_width = float(layout.get("table_width_mm", sum(widths)))
    warnings = list(layout.get("warnings", []))

    requested = [0.0] * len(widths)
    wrapped_cells: list[list[dict[str, Any]]] = [[] for _ in widths]
    for cell in cells:
        col = int(cell.get("col", -1))
        if col < 0 or col >= len(widths) or not cell.get("soft_wrapped", False):
            continue
        wrapped_cells[col].append(cell)
        estimated = _estimated_unwrapped_width(cell)
        # 한 셀 때문에 열 하나가 표 대부분을 차지하지 않게 제한한다.
        cap = min(widths[col] * 1.6, max_width * 0.45)
        target = min(cap, max(widths[col] * 1.15, estimated))
        requested[col] = max(requested[col], max(0.0, target - widths[col]))

    available = max(0.0, max_width - table_width)
    total_requested = sum(requested)
    increments = list(requested)
    if total_requested > available and total_requested:
        scale = available / total_requested
        increments = [value * scale for value in requested]

    column_changes: list[dict[str, Any]] = []
    target_widths = list(widths)
    for col, increment in enumerate(increments):
        if increment < MIN_WIDTH_CHANGE_MM:
            if wrapped_cells[col]:
                warnings.append(
                    f"{layout['index']}번 표 {col + 1}열은 줄바꿈이 있지만 "
                    "본문 폭 상한 때문에 더 넓히지 못했습니다."
                )
            continue
        target_widths[col] = widths[col] + increment
        addresses = [str(cell.get("address", "")) for cell in wrapped_cells[col]]
        column_changes.append(
            {
                "column": col + 1,
                "column_index": col,
                "from_mm": _round(widths[col]),
                "to_mm": _round(target_widths[col]),
                "delta_mm": _round(increment),
                "reason": "열 너비 때문에 생긴 셀 줄바꿈",
                "cells": addresses,
                "measurement": "KeyIndicator 실측",
                "target_width_basis": "글자 크기·문자 폭 추정",
            }
        )

    row_changes = _plan_rows(layout, cells)
    return {
        "table": int(layout["index"]),
        "rows": int(layout.get("rows", 0)),
        "columns": int(layout.get("cols", len(widths))),
        "width_before_mm": _round(table_width),
        "width_planned_mm": _round(table_width + sum(increments)),
        "max_width_mm": _round(max_width),
        "target_column_widths_mm": [_round(v) for v in target_widths],
        "column_changes": column_changes,
        "row_changes": row_changes,
        "warnings": warnings,
    }


def _plan_rows(layout: dict[str, Any], cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_row: dict[int, list[dict[str, Any]]] = {}
    for cell in cells:
        by_row.setdefault(int(cell.get("row", 0)), []).append(cell)

    changes: list[dict[str, Any]] = []
    row_heights = [float(v) for v in layout.get("row_heights_mm", [])]
    for row, row_cells in sorted(by_row.items()):
        if row >= len(row_heights) or not row_cells:
            continue
        current = row_heights[row]
        required = max(_required_cell_height(cell) for cell in row_cells)
        all_one_line = all(int(cell.get("line_count", 1)) <= 1 for cell in row_cells)
        reason = ""
        target = current
        if current + 0.5 < required:
            target = required
            reason = "글자 크기·줄 수·상하 여백에 비해 행 높이가 부족함"
        elif all_one_line and current > required + 2.0 and current > required * 1.25:
            target = required
            reason = "모든 셀이 한 줄인데 행 높이가 불필요하게 큼"
        if reason and abs(target - current) >= 0.5:
            changes.append(
                {
                    "row": row + 1,
                    "row_index": row,
                    "from_mm": _round(current),
                    "to_mm": _round(target),
                    "delta_mm": _round(target - current),
                    "reason": reason,
                    "height_basis": "실측 줄 수 + 글자 크기·줄간격·셀 여백",
                }
            )
    return changes


def _estimated_unwrapped_width(cell: dict[str, Any]) -> float:
    text = str(cell.get("text", ""))
    longest = max((_visual_units(line) for line in _logical_lines(text)), default=0.0)
    font_mm = max(1.0, float(cell.get("font_size_pt", 10.0)) * MM_PER_POINT)
    margins = cell.get("margins_mm") or {}
    horizontal = float(margins.get("left", 3.5)) + float(margins.get("right", 3.5))
    return longest * font_mm + horizontal + 1.0


def _required_cell_height(cell: dict[str, Any]) -> float:
    lines = max(1, int(cell.get("line_count", 1)))
    font_mm = max(1.0, float(cell.get("font_size_pt", 10.0)) * MM_PER_POINT)
    spacing = float(cell.get("line_spacing_percent", 160.0))
    line_height = font_mm * max(1.0, min(spacing, 250.0) / 100.0)
    margins = cell.get("margins_mm") or {}
    vertical = float(margins.get("top", 2.0)) + float(margins.get("bottom", 2.0))
    return max(2.0, lines * line_height + vertical)


def _logical_lines(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.split("\n") or [""]


def _visual_units(text: str) -> float:
    units = 0.0
    for char in text:
        if char == "\t":
            units += 4.0
        elif unicodedata.east_asian_width(char) in {"W", "F"}:
            units += 1.0
        elif char.isspace():
            units += 0.5
        else:
            units += 0.58
    return units


def hard_line_count(text: str) -> int:
    """명시적 문단/강제 줄바꿈 수. 조판 줄 수와 비교해 소프트 랩을 구분한다."""
    return max(1, len(_logical_lines(text)))


def _round(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return round(value, 2)
