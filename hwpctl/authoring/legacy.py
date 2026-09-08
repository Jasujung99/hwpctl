"""Version-one authoring compatibility: model, validation and public command compiler."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


from hwpctl.engine import Engine
from hwpctl.tools import tool_names


SCHEMA_ID = "hwpctl.blank-rebuild/1"
SUPPORTED_OPERATION_KINDS = frozenset({"paragraph", "table", "text_box"})


class SpecError(ValueError):
    """The normalized manifest is incomplete or asks for a non-public feature."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def a1_to_index(address: str) -> tuple[int, int]:
    """Return zero-based (row, column) for a single A1 address."""
    raw = address.strip().upper()
    if not raw or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" for char in raw):
        raise SpecError(f"잘못된 셀 주소입니다: {address!r}")
    letters = ""
    digits = ""
    for char in raw:
        if char.isalpha() and not digits:
            letters += char
        elif char.isdigit():
            digits += char
        else:
            raise SpecError(f"잘못된 셀 주소입니다: {address!r}")
    if not letters or not digits or digits.startswith("0"):
        raise SpecError(f"잘못된 셀 주소입니다: {address!r}")
    column = 0
    for char in letters:
        column = column * 26 + (ord(char) - ord("A") + 1)
    return int(digits) - 1, column - 1


def index_to_a1(row: int, column: int) -> str:
    if row < 0 or column < 0:
        raise ValueError("A1 index must be non-negative")
    name = ""
    number = column + 1
    while number:
        number, remainder = divmod(number - 1, 26)
        name = chr(ord("A") + remainder) + name
    return f"{name}{row + 1}"


def parse_range(value: str) -> tuple[tuple[int, int], tuple[int, int]]:
    raw = value.strip().upper()
    pieces = raw.split(":")
    if len(pieces) != 2:
        raise SpecError(f"병합 범위는 A1:B2 형식이어야 합니다: {value!r}")
    start, end = (a1_to_index(piece) for piece in pieces)
    if end[0] < start[0] or end[1] < start[1] or start == end:
        raise SpecError(f"잘못된 병합 범위입니다: {value!r}")
    return start, end


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SpecError(f"{label}은(는) JSON 객체여야 합니다.")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise SpecError(f"{label}은(는) JSON 배열이어야 합니다.")
    return value


def _number_list(value: Any, label: str, expected: int) -> list[float]:
    raw = _list(value, label)
    if len(raw) != expected:
        raise SpecError(f"{label}은(는) 정확히 {expected}개 값이 필요합니다.")
    result: list[float] = []
    for item in raw:
        if isinstance(item, bool):
            raise SpecError(f"{label} 값은 숫자여야 합니다.")
        try:
            number = float(item)
        except (TypeError, ValueError) as exc:
            raise SpecError(f"{label} 값은 숫자여야 합니다.") from exc
        if not math.isfinite(number) or number <= 0:
            raise SpecError(f"{label} 값은 0보다 커야 합니다.")
        result.append(number)
    return result


def _margin(value: Any, label: str) -> tuple[float, float, float, float]:
    values = _list(value, label)
    if len(values) != 4:
        raise SpecError(f"{label}은(는) 정확히 4개 값이 필요합니다.")
    raw: list[float] = []
    for item in values:
        if isinstance(item, bool):
            raise SpecError(f"{label} 값은 숫자여야 합니다.")
        try:
            number = float(item)
        except (TypeError, ValueError) as exc:
            raise SpecError(f"{label} 값은 숫자여야 합니다.") from exc
        if not math.isfinite(number) or number < 0:
            raise SpecError(f"{label} 값은 0 이상이어야 합니다.")
        raw.append(number)
    if any(number > 50 for number in raw):
        raise SpecError(f"{label} 값은 0~50mm 범위여야 합니다.")
    return raw[0], raw[1], raw[2], raw[3]


def _runs(value: Any, label: str) -> list[dict[str, Any]] | None:
    """Validate the public ``insert_paragraph`` run schema without COM knowledge."""
    if value is None:
        return None
    raw_runs = _list(value, label)
    if not raw_runs:
        return None
    permitted = {
        "text", "bold", "italic", "font", "size", "color", "text_shadow",
        "letter_spacing_percent", "width_scale_percent", "underline", "strikeout",
        "superscript", "subscript", "kerning",
    }
    result: list[dict[str, Any]] = []
    for index, item in enumerate(raw_runs):
        run = dict(_mapping(item, f"{label}[{index}]"))
        unknown = sorted(set(run) - permitted)
        if unknown:
            raise SpecError(f"{label}[{index}]의 알 수 없는 run 필드: {', '.join(unknown)}")
        if not isinstance(run.get("text"), str):
            raise SpecError(f"{label}[{index}].text는 문자열이어야 합니다.")
        result.append(run)
    return result


def _paragraph_layout(value: Any, label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    raw = dict(_mapping(value, label))
    permitted = {
        "align", "left_margin_mm", "right_margin_mm", "first_line_indent_mm",
        "before_spacing_mm", "after_spacing_mm", "line_spacing_percent",
        "break_latin_word", "break_non_latin_word",
    }
    unknown = sorted(set(raw) - permitted)
    if unknown:
        raise SpecError(f"{label}의 알 수 없는 문단 필드: {', '.join(unknown)}")
    return raw


def _paragraph_payload(value: Any, label: str, *, allow_page_break_before: bool) -> dict[str, Any]:
    raw = dict(_mapping(value, label))
    permitted = {"text", "runs", "paragraph", "page_break_before"}
    unknown = sorted(set(raw) - permitted)
    if unknown:
        raise SpecError(f"{label}의 알 수 없는 문단 필드: {', '.join(unknown)}")
    text = raw.get("text", "")
    if not isinstance(text, str):
        raise SpecError(f"{label}.text는 문자열이어야 합니다.")
    runs = _runs(raw.get("runs"), f"{label}.runs")
    if text and runs:
        raise SpecError(f"{label}에서 text와 비어 있지 않은 runs는 함께 쓸 수 없습니다.")
    page_break_before = bool(raw.get("page_break_before", False))
    if page_break_before and not allow_page_break_before:
        raise SpecError(f"{label}.page_break_before는 표 셀 안에서 지원되지 않습니다.")
    return {
        "text": text,
        "runs": runs,
        "paragraph": _paragraph_layout(raw.get("paragraph"), f"{label}.paragraph"),
        "page_break_before": page_break_before,
    }


def _fill(value: Any, label: str) -> Any:
    """Keep source paint verbatim; preflight gates unpublished fill variants."""
    if value is None or isinstance(value, str):
        return value
    raw = _mapping(value, label)
    return dict(raw)


def _cell_sort_key(address: str) -> tuple[int, int]:
    return a1_to_index(address)


@dataclass(frozen=True)
class Asset:
    key: str
    path: Path
    sha256: str | None


@dataclass(frozen=True)
class Cell:
    address: str
    paragraphs: tuple[dict[str, Any], ...]
    fill: Any = None
    margin_mm: tuple[float, float, float, float] | None = None
    valign: str | None = None
    borders: tuple[dict[str, Any], ...] = ()
    images: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class Paragraph:
    payload: dict[str, Any]
    page_break_after: bool = False
    page_controls_after: tuple[PageControl, ...] = ()


@dataclass(frozen=True)
class TextBox:
    args: dict[str, Any]
    page_break_before: bool = False
    page_break_after: bool = False
    page_controls_after: tuple[PageControl, ...] = ()


@dataclass(frozen=True)
class PageControl:
    visibility: dict[str, bool] | None = None
    restart_page_number: int | None = None


@dataclass(frozen=True)
class Table:
    rows: int
    cols: int
    column_widths_mm: tuple[float, ...]
    row_heights_mm: tuple[float, ...]
    default_margin_mm: tuple[float, float, float, float]
    merges: tuple[str, ...]
    cells: tuple[Cell, ...]
    exit_cell: str
    properties: dict[str, Any]
    position: dict[str, Any] | None = None
    page_break_before: bool = False
    page_break_after: bool = False
    review: bool = True
    page_controls_after: tuple[PageControl, ...] = ()


Operation = Paragraph | TextBox | Table


@dataclass(frozen=True)
class BuildSpec:
    source_sha256: str
    source_label: str
    page: dict[str, Any]
    page_number: dict[str, Any] | None
    assets: dict[str, Asset]
    operations: tuple[Operation, ...]
    raw_hash: str


def _assert_no_capability_gap(raw: Mapping[str, Any], where: str) -> None:
    """Reject source-only constructs that still have no public command.

    The original table/page controls now have public Engine/CLI/MCP
    commands.  Keep this guard only for genuinely unsupported legacy fields so
    a manifest can never make the driver reach for a private COM fallback.
    """
    known_gaps = {
        "shape_kind": "generic_shapes",
        "floating_position": "floating_images",
    }
    found = [known_gaps[key] for key in known_gaps if key in raw]
    if found:
        names = ", ".join(sorted(set(found)))
        raise SpecError(f"{where}에는 아직 공개 MCP 명령이 없는 기능이 있습니다: {names}")


def _parse_cell(address: str, value: Any, *, rows: int, cols: int) -> Cell:
    row, column = a1_to_index(address)
    if row >= rows or column >= cols:
        raise SpecError(f"표 범위를 벗어난 셀입니다: {address}")
    raw = _mapping(value, f"cells.{address}")
    _assert_no_capability_gap(raw, f"cells.{address}")
    permitted = {"paragraphs", "fill", "margin_mm", "valign", "borders", "images"}
    unknown = sorted(set(raw) - permitted)
    if unknown:
        raise SpecError(f"cells.{address}의 알 수 없는 필드: {', '.join(unknown)}")
    paragraphs_raw = _list(raw.get("paragraphs"), f"cells.{address}.paragraphs")
    if not paragraphs_raw:
        raise SpecError(f"cells.{address}.paragraphs에는 빈 문단이라도 하나 필요합니다.")
    paragraphs = tuple(
        _paragraph_payload(item, f"cells.{address}.paragraphs[{index}]", allow_page_break_before=False)
        for index, item in enumerate(paragraphs_raw)
    )
    margin_value = raw.get("margin_mm")
    margin = _margin(margin_value, f"cells.{address}.margin_mm") if margin_value is not None else None
    valign = raw.get("valign")
    if valign is not None and valign not in {"top", "center", "bottom"}:
        raise SpecError(f"cells.{address}.valign은 top/center/bottom이어야 합니다.")
    borders: list[dict[str, Any]] = []
    for index, border_value in enumerate(_list(raw.get("borders", []), f"cells.{address}.borders")):
        border = dict(_mapping(border_value, f"cells.{address}.borders[{index}]"))
        unknown_border = sorted(set(border) - {"sides", "line_type", "width", "color"})
        if unknown_border:
            raise SpecError(
                f"cells.{address}.borders[{index}]의 알 수 없는 테두리 필드: "
                + ", ".join(unknown_border)
            )
        borders.append(border)
    images: list[dict[str, Any]] = []
    for index, image_value in enumerate(_list(raw.get("images", []), f"cells.{address}.images")):
        image = dict(_mapping(image_value, f"cells.{address}.images[{index}]"))
        if "position" in image:
            raise SpecError(
                f"cells.{address}.images[{index}]에는 아직 공개 MCP 명령이 없는 기능이 있습니다: floating_images"
            )
        unknown_image = sorted(set(image) - {"asset", "size_option", "width_mm", "height_mm"})
        if unknown_image:
            raise SpecError(
                f"cells.{address}.images[{index}]의 알 수 없는 그림 필드: "
                + ", ".join(unknown_image)
            )
        if not isinstance(image.get("asset"), str) or not image["asset"]:
            raise SpecError(f"cells.{address}.images[{index}].asset은 assets 키여야 합니다.")
        images.append(image)
    return Cell(
        address=address.strip().upper(),
        paragraphs=paragraphs,
        fill=_fill(raw.get("fill"), f"cells.{address}.fill"),
        margin_mm=margin,
        valign=valign,
        borders=tuple(borders),
        images=tuple(images),
    )


def _last_anchor(rows: int, cols: int, merges: Iterable[str]) -> str:
    final = (rows - 1, cols - 1)
    for merge in merges:
        start, end = parse_range(merge)
        if start[0] <= final[0] <= end[0] and start[1] <= final[1] <= end[1]:
            return index_to_a1(*start)
    return index_to_a1(*final)


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise SpecError(f"{label}는 숫자여야 합니다.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SpecError(f"{label}는 숫자여야 합니다.") from exc
    if not math.isfinite(number):
        raise SpecError(f"{label}는 유한한 숫자여야 합니다.")
    return number


def _position_enum(value: Any, label: str, *, allowed: set[str], aliases: Mapping[str, str] | None = None) -> str:
    if not isinstance(value, str):
        raise SpecError(f"{label} 값은 문자열이어야 합니다.")
    normalized = value.strip().lower().replace("-", "_")
    if aliases is not None:
        normalized = aliases.get(normalized, normalized)
    if normalized not in allowed:
        raise SpecError(f"{label} 값이 지원 범위에 없습니다: {value!r}")
    return normalized


def _table_position(value: Any, label: str) -> dict[str, Any] | None:
    """Translate the flat read-only position record to the public command shape.

    The analyser keeps source facts for every table, including fields that Han/글
    ignores when a table is inline.  ``set_table_position`` deliberately has a
    smaller inline schema, so retain only its meaningful fields there while
    validating that no unsupported source layout is silently discarded.
    """
    if value is None:
        return None
    raw = dict(_mapping(value, label))
    permitted = {
        "mode", "horizontal_relative_to", "vertical_relative_to", "horizontal_align",
        "vertical_align", "x_mm", "y_mm", "wrap", "flow_with_text", "allow_overlap",
        "affect_line_spacing", "outside_margin_mm",
    }
    unknown = sorted(set(raw) - permitted)
    if unknown:
        raise SpecError(f"{label}의 알 수 없는 표 위치 필드: {', '.join(unknown)}")
    mode = _position_enum(raw.get("mode", "inline"), f"{label}.mode", allowed={"inline", "floating"})
    margins = list(_margin(raw.get("outside_margin_mm", [0, 0, 0, 0]), f"{label}.outside_margin_mm"))
    affect_line_spacing = raw.get("affect_line_spacing", False)
    if not isinstance(affect_line_spacing, bool):
        raise SpecError(f"{label}.affect_line_spacing는 true 또는 false여야 합니다.")

    # Validate source-faithful fields even when they do not affect inline
    # rendering.  This prevents a malformed specification from being quietly
    # normalized to an unrelated public layout.
    for key, allowed, aliases in (
        ("horizontal_relative_to", {"para", "column", "paper", "page"}, {"paragraph": "para"}),
        ("vertical_relative_to", {"para", "paper", "page"}, {"paragraph": "para"}),
        ("horizontal_align", {"left", "center", "right"}, None),
        ("vertical_align", {"top", "center", "bottom"}, None),
    ):
        if key in raw:
            _position_enum(raw[key], f"{label}.{key}", allowed=allowed, aliases=aliases)
    if "x_mm" in raw:
        _finite_number(raw["x_mm"], f"{label}.x_mm")
    if "y_mm" in raw:
        _finite_number(raw["y_mm"], f"{label}.y_mm")
    for key in ("flow_with_text", "allow_overlap"):
        if key in raw and not isinstance(raw[key], bool):
            raise SpecError(f"{label}.{key}는 true 또는 false여야 합니다.")

    if mode == "inline":
        if "wrap" in raw:
            _position_enum(raw["wrap"], f"{label}.wrap", allowed={"inline"})
        return {
            "mode": "inline",
            "affect_line_spacing": affect_line_spacing,
            "outside_margin_mm": margins,
        }

    required = ("x_mm", "y_mm", "wrap")
    missing = [key for key in required if key not in raw]
    if missing:
        raise SpecError(f"{label} floating 위치 필수값 누락: {', '.join(missing)}")
    horizontal_relative_to = _position_enum(
        raw.get("horizontal_relative_to", "para"),
        f"{label}.horizontal_relative_to",
        allowed={"para", "column", "paper", "page"},
        aliases={"paragraph": "para"},
    )
    vertical_relative_to = _position_enum(
        raw.get("vertical_relative_to", "para"),
        f"{label}.vertical_relative_to",
        allowed={"para", "paper", "page"},
        aliases={"paragraph": "para"},
    )
    wrap = _position_enum(
        raw["wrap"],
        f"{label}.wrap",
        allowed={"top_and_bottom", "square", "behind_text", "in_front_of_text"},
    )
    return {
        "mode": "floating",
        "horizontal_relative_to": horizontal_relative_to,
        "vertical_relative_to": vertical_relative_to,
        "horizontal_align": _position_enum(
            raw.get("horizontal_align", "left"),
            f"{label}.horizontal_align",
            allowed={"left", "center", "right"},
        ),
        "vertical_align": _position_enum(
            raw.get("vertical_align", "top"),
            f"{label}.vertical_align",
            allowed={"top", "center", "bottom"},
        ),
        "x_mm": _finite_number(raw["x_mm"], f"{label}.x_mm"),
        "y_mm": _finite_number(raw["y_mm"], f"{label}.y_mm"),
        "wrap": wrap,
        "flow_with_text": raw.get("flow_with_text", True),
        "allow_overlap": raw.get("allow_overlap", False),
        "affect_line_spacing": affect_line_spacing,
        "outside_margin_mm": margins,
    }


def _table_properties(value: Any, label: str) -> dict[str, Any]:
    """Validate the exact public ``set_table_properties`` payload."""
    raw = dict(_mapping(value, label))
    permitted = {"page_break", "repeat_header", "cell_spacing_mm"}
    unknown = sorted(set(raw) - permitted)
    if unknown:
        raise SpecError(f"{label}의 알 수 없는 표 속성 필드: {', '.join(unknown)}")
    missing = sorted(permitted - set(raw))
    if missing:
        raise SpecError(f"{label} 필수값 누락: {', '.join(missing)}")
    page_break = _position_enum(raw["page_break"], f"{label}.page_break", allowed={"none", "table", "cell"})
    repeat_header = raw["repeat_header"]
    if not isinstance(repeat_header, bool):
        raise SpecError(f"{label}.repeat_header는 true 또는 false여야 합니다.")
    cell_spacing_mm = _finite_number(raw["cell_spacing_mm"], f"{label}.cell_spacing_mm")
    if not 0 <= cell_spacing_mm <= 50:
        raise SpecError(f"{label}.cell_spacing_mm는 0~50mm 범위여야 합니다.")
    return {
        "page_break": page_break,
        "repeat_header": repeat_header,
        "cell_spacing_mm": cell_spacing_mm,
    }


def _page_controls(value: Any, label: str) -> tuple[PageControl, ...]:
    """Keep source PAGEHIDING/NEWNUM control order for future public commands."""
    if value is None:
        return ()
    controls: list[PageControl] = []
    visibility_keys = {
        "hide_page_num", "hide_header", "hide_footer", "hide_border", "hide_fill", "hide_master_page",
    }
    for index, item in enumerate(_list(value, label)):
        raw = dict(_mapping(item, f"{label}[{index}]"))
        kind = raw.get("kind")
        if kind == "page_hiding":
            unknown = sorted(set(raw) - ({"kind"} | visibility_keys))
            if unknown:
                raise SpecError(f"{label}[{index}]의 알 수 없는 page_hiding 필드: {', '.join(unknown)}")
            visibility = {key: bool(raw.get(key, False)) for key in sorted(visibility_keys)}
            for key in visibility_keys:
                if key in raw and not isinstance(raw[key], bool):
                    raise SpecError(f"{label}[{index}].{key}는 true 또는 false여야 합니다.")
            controls.append(PageControl(visibility=visibility))
        elif kind == "new_number":
            unknown = sorted(set(raw) - {"kind", "number", "number_type"})
            if unknown:
                raise SpecError(f"{label}[{index}]의 알 수 없는 new_number 필드: {', '.join(unknown)}")
            if raw.get("number_type", "page") != "page":
                raise SpecError(f"{label}[{index}].number_type은 현재 page만 지원합니다.")
            number = raw.get("number")
            if isinstance(number, bool) or not isinstance(number, int) or number < 1:
                raise SpecError(f"{label}[{index}].number는 1 이상의 정수여야 합니다.")
            controls.append(PageControl(restart_page_number=number))
        else:
            raise SpecError(f"{label}[{index}].kind는 page_hiding 또는 new_number여야 합니다.")
    return tuple(controls)


def _parse_table(raw_value: Any, *, index: int) -> Table:
    raw = _mapping(raw_value, f"operations[{index}]")
    _assert_no_capability_gap(raw, f"operations[{index}]")
    permitted = {
        "kind", "rows", "cols", "column_widths_mm", "row_heights_mm", "default_margin_mm",
        "merges", "cells", "exit_cell", "position", "properties", "page_break_before", "page_break_after", "review", "page_controls_after",
    }
    unknown = sorted(set(raw) - permitted)
    if unknown:
        raise SpecError(f"operations[{index}] table의 알 수 없는 필드: {', '.join(unknown)}")
    rows, cols = raw.get("rows"), raw.get("cols")
    if isinstance(rows, bool) or isinstance(cols, bool) or not isinstance(rows, int) or not isinstance(cols, int):
        raise SpecError(f"operations[{index}] table의 rows/cols는 정수여야 합니다.")
    if rows < 1 or cols < 1:
        raise SpecError(f"operations[{index}] table의 rows/cols는 1 이상이어야 합니다.")
    widths = tuple(_number_list(raw.get("column_widths_mm"), f"operations[{index}].column_widths_mm", cols))
    heights = tuple(_number_list(raw.get("row_heights_mm"), f"operations[{index}].row_heights_mm", rows))
    default_margin = _margin(raw.get("default_margin_mm"), f"operations[{index}].default_margin_mm")
    merges_raw = _list(raw.get("merges", []), f"operations[{index}].merges")
    merges: list[str] = []
    covered_by_merge: dict[tuple[int, int], tuple[int, int]] = {}
    for merge in merges_raw:
        if not isinstance(merge, str):
            raise SpecError(f"operations[{index}].merges의 값은 문자열이어야 합니다.")
        start, end = parse_range(merge)
        if end[0] >= rows or end[1] >= cols:
            raise SpecError(f"operations[{index}].merges 범위가 표를 벗어납니다: {merge}")
        for row in range(start[0], end[0] + 1):
            for column in range(start[1], end[1] + 1):
                position = (row, column)
                if position in covered_by_merge:
                    raise SpecError(f"operations[{index}].merges 범위가 겹칩니다: {merge}")
                covered_by_merge[position] = start
        merges.append(merge.strip().upper())
    cell_map = _mapping(raw.get("cells"), f"operations[{index}].cells")
    cells = [_parse_cell(address, value, rows=rows, cols=cols) for address, value in cell_map.items()]
    if len({cell.address for cell in cells}) != len(cells):
        raise SpecError(f"operations[{index}].cells에 중복 셀이 있습니다.")
    for cell in cells:
        position = a1_to_index(cell.address)
        anchor = covered_by_merge.get(position)
        if anchor is not None and anchor != position:
            raise SpecError(
                f"operations[{index}].cells.{cell.address}은 병합 셀의 시작 주소 "
                f"{index_to_a1(*anchor)}로 적어야 합니다."
            )
    expected_exit = _last_anchor(rows, cols, merges)
    exit_cell = str(raw.get("exit_cell", expected_exit)).strip().upper()
    if exit_cell != expected_exit:
        raise SpecError(
            f"operations[{index}] exit_cell은 마지막 논리 셀 {expected_exit}이어야 합니다 (현재 {exit_cell})."
        )
    cell_addresses = {cell.address for cell in cells}
    if exit_cell not in cell_addresses:
        raise SpecError(
            f"operations[{index}] exit_table 전 캐럿을 고정하려면 exit_cell {exit_cell}을 cells에 명시하세요."
        )
    return Table(
        rows=rows,
        cols=cols,
        column_widths_mm=widths,
        row_heights_mm=heights,
        default_margin_mm=default_margin,
        merges=tuple(merges),
        cells=tuple(cells),
        exit_cell=exit_cell,
        properties=_table_properties(raw.get("properties"), f"operations[{index}].properties"),
        position=_table_position(raw.get("position"), f"operations[{index}].position"),
        page_break_before=bool(raw.get("page_break_before", False)),
        page_break_after=bool(raw.get("page_break_after", False)),
        review=bool(raw.get("review", True)),
        page_controls_after=_page_controls(raw.get("page_controls_after"), f"operations[{index}].page_controls_after"),
    )


def _parse_paragraph(raw_value: Any, *, index: int) -> Paragraph:
    raw = _mapping(raw_value, f"operations[{index}]")
    _assert_no_capability_gap(raw, f"operations[{index}]")
    permitted = {"kind", "text", "runs", "paragraph", "page_break_before", "page_break_after", "page_controls_after"}
    unknown = sorted(set(raw) - permitted)
    if unknown:
        raise SpecError(f"operations[{index}] paragraph의 알 수 없는 필드: {', '.join(unknown)}")
    payload = _paragraph_payload(
        {key: raw[key] for key in ("text", "runs", "paragraph", "page_break_before") if key in raw},
        f"operations[{index}]",
        allow_page_break_before=True,
    )
    return Paragraph(
        payload=payload,
        page_break_after=bool(raw.get("page_break_after", False)),
        page_controls_after=_page_controls(raw.get("page_controls_after"), f"operations[{index}].page_controls_after"),
    )


def _parse_text_box(raw_value: Any, *, index: int) -> TextBox:
    raw = _mapping(raw_value, f"operations[{index}]")
    _assert_no_capability_gap(raw, f"operations[{index}]")
    permitted = {
        "kind", "text", "width_mm", "height_mm", "fill", "line", "shadow", "text_shadow",
        "align", "position", "margin", "bold", "italic", "font", "size", "color", "page_break_before", "page_break_after", "page_controls_after",
    }
    unknown = sorted(set(raw) - permitted)
    if unknown:
        raise SpecError(f"operations[{index}] text_box의 알 수 없는 필드: {', '.join(unknown)}")
    required = ("text", "width_mm", "height_mm")
    missing = [name for name in required if name not in raw]
    if missing:
        raise SpecError(f"operations[{index}] text_box 필수값 누락: {', '.join(missing)}")
    args = {name: raw[name] for name in permitted - {"kind", "page_break_before", "page_break_after", "page_controls_after"} if name in raw}
    if "fill" in args:
        args["fill"] = _fill(args["fill"], f"operations[{index}].fill")
    if "margin" in args:
        from hwpctl.engine import _normalize_margin
        from hwpctl.errors import UsageError
        try:
            _normalize_margin(args["margin"])
        except UsageError as exc:
            raise SpecError(f"operations[{index}].margin: {exc}") from exc
    return TextBox(
        args=args,
        page_break_before=bool(raw.get("page_break_before", False)),
        page_break_after=bool(raw.get("page_break_after", False)),
        page_controls_after=_page_controls(raw.get("page_controls_after"), f"operations[{index}].page_controls_after"),
    )


def load_spec(path: Path) -> BuildSpec:
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise SpecError(f"사양 파일을 읽지 못했습니다: {path}") from exc
    try:
        raw_value = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpecError(f"사양 JSON이 올바르지 않습니다: {path}") from exc
    raw = _mapping(raw_value, "최상위 사양")
    permitted = {"schema", "reference", "page", "page_number", "assets", "operations"}
    unknown = sorted(set(raw) - permitted)
    if unknown:
        raise SpecError(f"최상위 사양의 알 수 없는 필드: {', '.join(unknown)}")
    if raw.get("schema") != SCHEMA_ID:
        raise SpecError(f"schema는 {SCHEMA_ID!r}이어야 합니다.")
    reference = _mapping(raw.get("reference"), "reference")
    if set(reference) - {"label", "source_sha256"}:
        raise SpecError("reference에는 label과 source_sha256만 허용됩니다 (원본 경로 금지).")
    source_sha256 = reference.get("source_sha256")
    if (
        not isinstance(source_sha256, str)
        or len(source_sha256.strip()) != 64
        or any(char not in "0123456789abcdefABCDEF" for char in source_sha256.strip())
    ):
        raise SpecError("reference.source_sha256에는 원본의 64자리 SHA-256이 필요합니다.")
    source_label = reference.get("label", "Synthetic document")
    if not isinstance(source_label, str) or not source_label.strip():
        raise SpecError("reference.label은 비어 있지 않은 문자열이어야 합니다.")
    page = dict(_mapping(raw.get("page"), "page"))
    permitted_page = {
        "paper_width", "paper_height", "left", "right", "top", "bottom", "header", "footer", "gutter", "landscape", "apply",
    }
    bad_page = sorted(set(page) - permitted_page)
    if bad_page:
        raise SpecError(f"page에 아직 공개 API가 없는 필드가 있습니다: {', '.join(bad_page)}")
    page_number_raw = raw.get("page_number")
    page_number: dict[str, Any] | None = None
    if page_number_raw is not None:
        page_number = dict(_mapping(page_number_raw, "page_number"))
        unknown_page_number = sorted(set(page_number) - {"position", "separator"})
        if unknown_page_number:
            raise SpecError(
                "page_number에 알 수 없는 필드가 있습니다: "
                + ", ".join(unknown_page_number)
            )
        position = page_number.get("position", "bottom_center")
        if position not in {
            "top_left", "top_center", "top_right", "bottom_left", "bottom_center", "bottom_right",
        }:
            raise SpecError("page_number.position은 top/bottom_left/center/right 중 하나여야 합니다.")
        separator = page_number.get("separator", "-")
        if not isinstance(separator, str) or len(separator) > 1:
            raise SpecError("page_number.separator는 한 글자 또는 빈 문자열이어야 합니다.")
    assets_raw = _mapping(raw.get("assets", {}), "assets")
    assets: dict[str, Asset] = {}
    for key, asset_value in assets_raw.items():
        if not isinstance(key, str) or not key:
            raise SpecError("assets 키는 비어 있지 않은 문자열이어야 합니다.")
        asset = _mapping(asset_value, f"assets.{key}")
        path_value = asset.get("path")
        if not isinstance(path_value, str) or not path_value:
            raise SpecError(f"assets.{key}.path가 필요합니다.")
        hash_value = asset.get("sha256")
        if hash_value is not None and (
            not isinstance(hash_value, str)
            or len(hash_value.strip()) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in hash_value.strip())
        ):
            raise SpecError(f"assets.{key}.sha256은 64자리 SHA-256이어야 합니다.")
        asset_path = Path(path_value)
        if not asset_path.is_absolute():
            asset_path = path.parent / asset_path
        assets[key] = Asset(
            key=key,
            path=asset_path.resolve(),
            sha256=hash_value.upper() if hash_value else None,
        )
    operations_raw = _list(raw.get("operations"), "operations")
    if not operations_raw:
        raise SpecError("operations가 비어 있습니다.")
    operations: list[Operation] = []
    for index, operation_value in enumerate(operations_raw):
        operation = _mapping(operation_value, f"operations[{index}]")
        kind = operation.get("kind")
        if kind not in SUPPORTED_OPERATION_KINDS:
            raise SpecError(f"operations[{index}].kind는 {sorted(SUPPORTED_OPERATION_KINDS)} 중 하나여야 합니다.")
        if kind == "paragraph":
            operations.append(_parse_paragraph(operation, index=index))
        elif kind == "table":
            operations.append(_parse_table(operation, index=index))
        else:
            operations.append(_parse_text_box(operation, index=index))
    return BuildSpec(
        source_sha256=source_sha256.strip().upper(),
        source_label=source_label.strip(),
        page=page,
        page_number=page_number,
        assets=assets,
        operations=tuple(operations),
        raw_hash=hashlib.sha256(raw_bytes).hexdigest().upper(),
    )


def _fill_requires_radial(fill: Any) -> bool:
    if not isinstance(fill, Mapping):
        return False
    kind = str(fill.get("type", fill.get("kind", "solid"))).strip().lower()
    return kind in {"radial", "radial_gradient", "radial-gradient"}


def _paragraph_capabilities(payload: Mapping[str, Any]) -> set[str]:
    # Rich public runs already carry decorations, script, and kerning.  Keep this
    # helper as the single scanning point for future source-only paragraph effects.
    del payload
    return set()


def required_capabilities(spec: BuildSpec) -> set[str]:
    """Return every fidelity feature the normalized source asks this build to retain."""
    required: set[str] = set()
    for operation in spec.operations:
        if isinstance(operation, Paragraph):
            required.update(_paragraph_capabilities(operation.payload))
            controls = operation.page_controls_after
        elif isinstance(operation, TextBox):
            if _fill_requires_radial(operation.args.get("fill")):
                required.add("radial_gradient")
            controls = operation.page_controls_after
        else:
            # Every source table carries an explicit position.  Inline tables
            # still need the command so their outside margins and line-spacing
            # behavior are not replaced by invisible defaults.
            if operation.position is not None:
                required.add("table_position")
            required.add("table_properties")
            for cell in operation.cells:
                if _fill_requires_radial(cell.fill):
                    required.add("radial_gradient")
                for paragraph in cell.paragraphs:
                    required.update(_paragraph_capabilities(paragraph))
            controls = operation.page_controls_after
        for control in controls:
            if control.visibility is not None:
                required.add("page_visibility")
            if control.restart_page_number is not None:
                required.add("page_number_restart")
    return required


def _unavailable_capabilities(spec: BuildSpec) -> dict[str, str]:
    available_commands = set(tool_names())
    required = required_capabilities(spec)
    unavailable: dict[str, str] = {}
    command_backed = {
        "table_position": "set_table_position",
        "table_properties": "set_table_properties",
        "page_visibility": "set_page_visibility",
        "page_number_restart": "restart_page_number",
        "radial_gradient": "set_cell_fill",
    }
    for capability, command in command_backed.items():
        if capability in required and command not in available_commands:
            unavailable[capability] = f"공개 명령 {command}"
    return unavailable


def preflight(spec: BuildSpec, output: Path, log_path: Path) -> None:
    unavailable = _unavailable_capabilities(spec)
    if unavailable:
        detail = "; ".join(f"{name} → {surface}" for name, surface in sorted(unavailable.items()))
        raise SpecError(
            "정규화 사양의 원본 효과를 표현할 공개 MCP 기능이 아직 없습니다: " + detail
        )
    if output.exists():
        raise SpecError(f"기존 산출물을 덮어쓰지 않습니다: {output}")
    if log_path.exists():
        raise SpecError(f"기존 빌드 기록을 덮어쓰지 않습니다: {log_path}")
    if output.resolve() == log_path.resolve():
        raise SpecError("산출물과 빌드 기록은 서로 다른 경로여야 합니다.")
    for asset in spec.assets.values():
        if not asset.path.is_file():
            raise SpecError(f"자산 파일을 찾지 못했습니다: {asset.key} → {asset.path}")
        if asset.sha256 and sha256_file(asset.path) != asset.sha256:
            raise SpecError(f"자산 해시가 사양과 다릅니다: {asset.key}")
        if asset.path.resolve() in {output.resolve(), log_path.resolve()}:
            raise SpecError("자산은 산출물/기록 경로로 사용할 수 없습니다.")
    # Compile the complete call sequence without constructing an Engine or COM.
    # This catches missing asset references and absent public commands before open.
    class CommandCheck:
        def dispatch(self, command: str, **kwargs: Any) -> dict[str, Any]:
            if command not in tool_names():
                raise SpecError(f"공개 명령이 없습니다: {command}")
            return {"ok": True, "warnings": []}

    PublicBuild(engine=CommandCheck(), spec=spec).build(output)


@dataclass
class PublicBuild:
    engine: Engine
    spec: BuildSpec
    progress_path: Path | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=lambda: {"paragraphs": 0, "tables": 0, "cells": 0, "text_boxes": 0, "images": 0})
    resumed_from_operation: int | None = None

    def call(self, command: str, **kwargs: Any) -> dict[str, Any]:
        """The only authoring gateway: public Engine.dispatch / CLI / MCP contract."""
        try:
            result = self.engine.dispatch(command, **kwargs)
        except Exception as exc:
            # COM can fail after it has already changed a blank document. Keep a
            # durable last-command record (may contain document text) to diagnose
            # the public bridge gap without inspecting or modifying the source.
            self.calls.append(
                {
                    "command": command,
                    "arguments": kwargs,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            self._checkpoint(status="failed")
            raise
        self.calls.append({"command": command, "arguments": kwargs, "result": result})
        self._checkpoint(status="running")
        return result

    def _checkpoint(self, *, status: str) -> None:
        """Persist a local build ledger; arguments may contain private content."""
        if self.progress_path is None:
            return
        payload = {
            "status": status,
            "schema": SCHEMA_ID,
            "reference": {"label": self.spec.source_label, "source_sha256": self.spec.source_sha256},
            "spec_sha256": self.spec.raw_hash,
            "object_counts": self.counts,
            "resumed_from_operation": self.resumed_from_operation,
            "command_count": len(self.calls),
            "last_call": self.calls[-1] if self.calls else None,
        }
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        self.progress_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def page_break_if(self, enabled: bool) -> None:
        if enabled:
            self.call("page", break_page=True)

    def apply_page_controls(self, controls: Iterable[PageControl]) -> None:
        for control in controls:
            if control.visibility is not None:
                self.call("set_page_visibility", **control.visibility)
            if control.restart_page_number is not None:
                self.call("restart_page_number", number=control.restart_page_number)

    def build_paragraph(self, operation: Paragraph) -> None:
        self.call("insert_paragraph", **operation.payload)
        self.counts["paragraphs"] += 1
        self.apply_page_controls(operation.page_controls_after)
        self.page_break_if(operation.page_break_after)

    def build_text_box(self, operation: TextBox) -> None:
        self.page_break_if(operation.page_break_before)
        self.call("insert_text_box", **operation.args)
        self.counts["text_boxes"] += 1
        self.apply_page_controls(operation.page_controls_after)
        self.page_break_if(operation.page_break_after)

    @staticmethod
    def _ordered_cells(table: Table) -> list[Cell]:
        normal = sorted((cell for cell in table.cells if cell.address != table.exit_cell), key=lambda cell: _cell_sort_key(cell.address))
        last = next(cell for cell in table.cells if cell.address == table.exit_cell)
        return [*normal, last]

    def _insert_images(self, table_index: int, cell: Cell) -> None:
        for image in cell.images:
            asset_key = image.get("asset")
            if not isinstance(asset_key, str) or asset_key not in self.spec.assets:
                raise SpecError(f"cells.{cell.address}.images.asset이 assets에 없습니다: {asset_key!r}")
            args = dict(image)
            args.pop("asset")
            args["path"] = str(self.spec.assets[asset_key].path)
            args["table"] = table_index
            args["cell"] = cell.address
            self.call("insert_image", **args)
            self.counts["images"] += 1

    def build_table(self, table: Table, table_index: int) -> None:
        self.page_break_if(table.page_break_before)
        # No hidden defaults: the normalized spec supplies source-measured margins.
        self.call("create_table", rows=table.rows, cols=table.cols, header=False, cell_margin=None)
        self.call("set_table_properties", table=table_index, **table.properties)
        self.call("set_table_grid", table=table_index,
                  column_widths_mm=list(table.column_widths_mm),
                  row_heights_mm=list(table.row_heights_mm))
        for cell_range in table.merges:
            self.call("merge_cells", table=table_index, cell_range=cell_range)
        self.call(
            "set_cell_margin",
            table=table_index,
            left=table.default_margin_mm[0],
            right=table.default_margin_mm[1],
            top=table.default_margin_mm[2],
            bottom=table.default_margin_mm[3],
        )
        ordered_cells = self._ordered_cells(table)
        for cell in ordered_cells:
            if cell.margin_mm is not None:
                self.call(
                    "set_cell_margin",
                    table=table_index,
                    cell_range=cell.address,
                    left=cell.margin_mm[0],
                    right=cell.margin_mm[1],
                    top=cell.margin_mm[2],
                    bottom=cell.margin_mm[3],
                )
            if cell.fill is not None:
                self.call("set_cell_fill", table=table_index, cell_range=cell.address, fill=cell.fill)
            if cell.valign is not None:
                self.call("set_valign", table=table_index, cell_range=cell.address, align=cell.valign)
            for border in cell.borders:
                self.call("set_cell_border", table=table_index, cell_range=cell.address, **border)
            self.call("write_cell", table=table_index, cell=cell.address, paragraphs=list(cell.paragraphs))
            self._insert_images(table_index, cell)
        if table.review:
            review = self.call("layout_review", table=table_index, dry_run=True)
            self.warnings.extend(str(item) for item in review.get("warnings", []))
        # Dedicated non-mutating navigation replaces the prototype margin trick.
        self.call("move_to_cell", table=table_index, cell=table.exit_cell)
        self.call("exit_table")
        # Native TablePropertyDialog selects the table object rather than a cell;
        # call it only after the public exit_table boundary.  The command itself
        # preserves the body cursor, so the next operation stays in document flow.
        if table.position is not None:
            self.call("set_table_position", table=table_index, position=table.position)
        self.counts["tables"] += 1
        self.counts["cells"] += len(table.cells)
        self.apply_page_controls(table.page_controls_after)
        self.page_break_if(table.page_break_after)

    @staticmethod
    def _counts_before(operations: Iterable[Operation]) -> dict[str, int]:
        counts = {"paragraphs": 0, "tables": 0, "cells": 0, "text_boxes": 0, "images": 0}
        for operation in operations:
            if isinstance(operation, Paragraph):
                counts["paragraphs"] += 1
            elif isinstance(operation, TextBox):
                counts["text_boxes"] += 1
            else:
                counts["tables"] += 1
                counts["cells"] += len(operation.cells)
                counts["images"] += sum(len(cell.images) for cell in operation.cells)
        return counts

    def _build_operations(self, *, start_operation: int, table_index: int) -> None:
        for operation in self.spec.operations[start_operation:]:
            if isinstance(operation, Paragraph):
                self.build_paragraph(operation)
            elif isinstance(operation, TextBox):
                self.build_text_box(operation)
            else:
                self.build_table(operation, table_index)
                table_index += 1

    def build(self, output: Path) -> None:
        self.call("open", new=True)
        self.call("set_pagedef", **self.spec.page)
        if self.spec.page_number is not None:
            self.call("set_page_number", **self.spec.page_number)
        self._build_operations(start_operation=0, table_index=0)
        self.call("save_as", path=str(output), format="")

    def resume(self, output: Path, *, from_operation: int) -> None:
        """Continue an already-open blank build without replaying prior pages."""
        if isinstance(from_operation, bool) or not isinstance(from_operation, int):
            raise SpecError("resume_from_operation은 0 이상의 정수여야 합니다.")
        if not 0 < from_operation <= len(self.spec.operations):
            raise SpecError(
                f"resume_from_operation은 1에서 {len(self.spec.operations)} 사이여야 합니다."
            )
        self.resumed_from_operation = from_operation
        completed = self.spec.operations[:from_operation]
        self.counts = self._counts_before(completed)
        table_index = sum(isinstance(operation, Table) for operation in completed)
        self._build_operations(start_operation=from_operation, table_index=table_index)
        self.call("save_as", path=str(output), format="")


def plan(spec: BuildSpec) -> dict[str, Any]:
    """A no-Han/글 summary useful for review before taking the global writer lock."""
    table_count = sum(isinstance(item, Table) for item in spec.operations)
    return {
        "ok": True,
        "schema": SCHEMA_ID,
        "reference": {"label": spec.source_label, "source_sha256": spec.source_sha256},
        "spec_sha256": spec.raw_hash,
        "page_number": spec.page_number,
        "operations": len(spec.operations),
        "tables": table_count,
        "paragraphs": sum(isinstance(item, Paragraph) for item in spec.operations),
        "text_boxes": sum(isinstance(item, TextBox) for item in spec.operations),
        "assets": sorted(spec.assets),
        "required_capabilities": sorted(required_capabilities(spec)),
        "authoring_contract": "Engine.dispatch only (CLI/MCP-equivalent)",
    }


def write_record(path: Path, *, spec: BuildSpec, build: PublicBuild, output: Path) -> None:
    record = {
        "ok": True,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "schema": SCHEMA_ID,
        "reference": {"label": spec.source_label, "source_sha256": spec.source_sha256},
        "spec_sha256": spec.raw_hash,
        "output": str(output),
        "authoring_contract": "Engine.dispatch only (same public API as CLI and MCP)",
        "resumed_from_operation": build.resumed_from_operation,
        "required_capabilities": sorted(required_capabilities(spec)),
        "object_counts": build.counts,
        "commands": [item["command"] for item in build.calls],
        "calls": build.calls,
        "warnings": list(dict.fromkeys(build.warnings)),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True, help="read-only analysis로 만든 normalized JSON 사양")
    parser.add_argument("--output", type=Path, required=True, help="새 HWP 산출물 경로(기존 파일이면 거부)")
    parser.add_argument("--log", type=Path, default=None, help="빌드 기록 JSON 경로(기본: output.hwp.build.json)")
    parser.add_argument("--dry-run", action="store_true", help="사양 검증과 공개 명령 계획만 출력; 한/글을 열지 않음")
    parser.add_argument(
        "--resume-from-operation",
        type=int,
        default=None,
        help="이미 열린 동일한 빈 문서에서 이 0-based 작업 번호부터 이어서 조립",
    )
    args = parser.parse_args()
    try:
        spec = load_spec(args.spec)
        output = args.output.expanduser().resolve()
        log_path = (args.log.expanduser().resolve() if args.log else output.with_suffix(output.suffix + ".build.json"))
        preflight(spec, output, log_path)
        if args.dry_run and args.resume_from_operation is not None:
            raise SpecError("--dry-run과 --resume-from-operation은 함께 쓸 수 없습니다.")
        if args.dry_run:
            print(json.dumps(plan(spec), ensure_ascii=False, indent=2))
            return 0
        progress_path = log_path.with_name(log_path.name + ".progress.json")
        build = PublicBuild(engine=Engine(), spec=spec, progress_path=progress_path)
        if args.resume_from_operation is None:
            build._checkpoint(status="starting")
            build.build(output)
        else:
            build.resumed_from_operation = args.resume_from_operation
            build._checkpoint(status="resuming")
            build.resume(output, from_operation=args.resume_from_operation)
        write_record(log_path, spec=spec, build=build, output=output)
        print(json.dumps({**plan(spec), "output": str(output), "build_record": str(log_path), "warnings": build.warnings}, ensure_ascii=False, indent=2))
        return 0
    except (SpecError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
