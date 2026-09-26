"""Compile ordered v2 content to public Engine commands without touching COM."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import inspect
from pathlib import Path
from typing import Any

from hwpctl import engine as api
from hwpctl.errors import UsageError
from hwpctl.authoring.model import DocumentSpec, mapping, sequence
from hwpctl.authoring import legacy


@dataclass(frozen=True)
class Command:
    location: str
    name: str
    arguments: dict[str, Any]
    source: str | None = None

    def to_dict(self):
        return {"location": self.location, "command": self.name,
                "arguments": deepcopy(self.arguments), "source": self.source}


def _bool(value, location):
    if type(value) is not bool:
        raise UsageError(f"{location}: expected boolean")
    return value


def _number(value, location, minimum=0, maximum=1000):
    if type(value) not in (int, float) or not minimum <= value <= maximum:
        raise UsageError(f"{location}: expected number in {minimum}..{maximum}")
    return value


def _integer(value, location, minimum=1, maximum=256):
    if type(value) is not int or not minimum <= value <= maximum:
        raise UsageError(f"{location}: expected integer in {minimum}..{maximum}")
    return value


class Compiler:
    def __init__(self, spec: DocumentSpec, *, check_assets=True):
        self.spec = spec
        self.commands: list[Command] = []
        self.tables: dict[str, int] = {}
        self.table_shapes: dict[str, tuple[int, int]] = {}
        self.table_count = 0
        self.assets: dict[str, Path] = {}
        self.check_assets = check_assets

    def emit(self, location, name, source=None, **arguments):
        handler = getattr(api.Engine, name, None)
        if handler is None:
            raise UsageError(f"{location}: public command is unavailable: {name}")
        try:
            inspect.signature(handler).bind(None, **arguments)
        except TypeError as exc:
            raise UsageError(f"{location}: {name}: {exc}") from exc
        self.commands.append(Command(location, name, deepcopy(arguments), source))

    def compile(self):
        for key, asset in self.spec.assets.items():
            path = (self.spec.base_dir / asset["path"]).resolve()
            if self.check_assets and not path.is_file():
                raise UsageError(f"assets.{key}: missing file")
            if self.check_assets and asset.get("sha256") and hashlib.sha256(path.read_bytes()).hexdigest().lower() != asset["sha256"].lower():
                raise UsageError(f"assets.{key}: SHA-256 mismatch")
            self.assets[key] = path
        for index, section in enumerate(self.spec.sections):
            location = f"sections[{index}]"
            if index:
                self.emit(location, "insert_section")
            page = mapping(section.get("page", {}), location + ".page", {
                "paper_width", "paper_height", "left", "right", "top", "bottom",
                "header", "footer", "gutter", "landscape", "apply"})
            for key, value in page.items():
                if key == "landscape":
                    _bool(value, location + ".page.landscape")
                elif key == "apply":
                    if value not in {"current", "all"} or (len(self.spec.sections) > 1 and value != "current"):
                        raise UsageError(f"{location}: multiple sections require current-only page setup")
                else:
                    _number(value, location + ".page." + key, 0.01 if key.startswith("paper_") else 0)
            if page:
                self.emit(location, "set_pagedef", **page)
            if section.get("page_number") is not None:
                number = mapping(section["page_number"], location + ".page_number", {"position", "separator"})
                api._normalize_page_number_position(number.get("position", "bottom_center"))
                api._normalize_page_number_separator(number.get("separator", "-"))
                self.emit(location, "set_page_number", **number)
            self.content(section["content"], location + ".content", in_cell=False)
        return tuple(self.commands)

    def content(self, content, location, *, in_cell, inline=False, depth=0):
        if depth > 32:
            raise UsageError(f"{location}: nesting exceeds 32")
        nodes = sequence(content, location)
        for index, node in enumerate(nodes):
            self.node(node, f"{location}[{index}]", in_cell=in_cell, inline=inline,
                      terminate=not (in_cell and index == len(nodes) - 1), depth=depth)

    def node(self, value, location, *, in_cell=False, inline=False, terminate=True, depth=0):
        node = mapping(value, location)
        kind = node.get("kind")
        source = node.get("source")
        if source is not None and not isinstance(source, str):
            raise UsageError(f"{location}.source: expected source location string")
        shared = {"kind", "source", "page_break_before", "page_break_after", "page_controls_after"}
        fields = {
            "paragraph": {"text", "runs", "paragraph", "content", "terminate"},
            "run": {"text", "bold", "italic", "font", "font_slots", "size", "color", "text_shadow",
                    "letter_spacing_percent", "width_scale_percent", "underline", "strikeout", "superscript", "subscript", "kerning"},
            "table": {"id", "rows", "cols", "column_widths_mm", "row_heights_mm", "default_margin_mm",
                      "merges", "cells", "exit_cell", "position", "properties", "review"},
            "picture": {"asset", "size_option", "width_mm", "height_mm", "position"},
            "text_box": {"text", "paragraphs", "width_mm", "height_mm", "fill", "line", "shadow", "text_shadow",
                         "margin", "align", "position", "bold", "italic", "font", "font_slots", "size", "color"},
            "shape": {"shape_kind", "width_mm", "height_mm", "fill", "line", "shadow", "position"},
            "chart": {"table_id", "cell_range", "chart_type", "chart_index"},
            "page_break": set(), "page_hiding": {"hide_page_num", "hide_header", "hide_footer", "hide_border", "hide_fill", "hide_master_page"},
            "new_number": {"number", "number_type"},
        }
        if kind not in fields:
            raise UsageError(f"{location}: unknown node kind {kind!r}")
        mapping(node, location, shared | fields[kind])
        for key in ("page_break_before", "page_break_after"):
            if key in node:
                _bool(node[key], location + "." + key)
            if node.get(key) and (in_cell or inline):
                raise UsageError(f"{location}: page break is not allowed in cell/inline content")
        if node.get("page_break_before"):
            self.emit(location, "page", source, break_page=True)
        args = {k: deepcopy(v) for k, v in node.items() if k not in shared}
        if kind == "paragraph":
            if inline:
                raise UsageError(f"{location}: a paragraph cannot be nested in inline content")
            do_terminate = _bool(args.pop("terminate", terminate), location + ".terminate")
            content = args.pop("content", None)
            if content is not None:
                if "text" in args or "runs" in args:
                    raise UsageError(f"{location}: content and text/runs are mutually exclusive")
                api._normalize_paragraph_spec(**args)
                self.emit(location, "insert_paragraph", source, **args, terminate=False)
                self.content(content, location + ".content", in_cell=in_cell, inline=True, depth=depth + 1)
                if do_terminate:
                    self.emit(location, "insert_paragraph", source, text="", terminate=True)
            else:
                api._normalize_paragraph_spec(**args)
                self.emit(location, "insert_paragraph", source, **args, terminate=do_terminate)
        elif kind == "run":
            if not inline:
                raise UsageError(f"{location}: run requires paragraph.content")
            api._normalize_text_run(args, 0)
            self.emit(location, "insert_paragraph", source, runs=[args], terminate=False)
        elif kind == "table":
            self.table(args, location, source, in_cell=in_cell, depth=depth)
        elif kind == "picture":
            asset = args.pop("asset", None)
            if asset not in self.assets:
                raise UsageError(f"{location}: missing asset reference {asset!r}")
            option = _integer(args.get("size_option", 1), location + ".size_option", 0, 3)
            if option in (2, 3) and not in_cell:
                raise UsageError(f"{location}: cell-fit image requires cell content")
            for key in ("width_mm", "height_mm"):
                _number(args.get(key, 0), location + "." + key, 0.01 if option == 1 else 0)
            if "position" in args:
                api._normalize_table_position(args["position"])
            args.setdefault("position", {"mode": "inline"})
            self.emit(location, "insert_image", source, path=str(self.assets[asset]), **{**args, "size_option": option})
        elif kind in {"text_box", "shape"}:
            for key in ("width_mm", "height_mm"):
                _number(args.get(key), location + "." + key, 0.01)
            api._normalize_fill(args.get("fill"), allow_empty=True)
            api._normalize_line(args.get("line"))
            api._normalize_shadow(args.get("shadow"), label="shape")
            if kind == "shape":
                if args.get("shape_kind") not in {"rectangle", "ellipse", "line"}:
                    raise UsageError(f"{location}: shape_kind must be rectangle, ellipse or line")
                if "position" in args:
                    api._normalize_table_position(args["position"])
            else:
                api._normalize_margin(args.get("margin"))
                api._normalize_text_box_position(args.get("position"))
                api._normalize_align(args.get("align", "center"))
                api._normalize_text_run({k: args[k] for k in ("text", "bold", "italic", "font", "font_slots", "size", "color", "text_shadow") if k in args} | {"text": args.get("text", "")}, 0)
                if "paragraphs" in args:
                    if args.get("text"):
                        raise UsageError(f"{location}: text and paragraphs are mutually exclusive")
                    api._normalize_cell_paragraphs(args["paragraphs"])
                args.setdefault("text", "")
                args["cursor_after"] = True
            self.emit(location, "insert_" + kind, source, **args)
        elif kind == "chart":
            table_id = args.pop("table_id", None)
            if table_id not in self.tables:
                raise UsageError(f"{location}: chart requires a previously authored table_id")
            if args.get("chart_type", "line") not in api.CHART_GROUPS:
                raise UsageError(f"{location}: invalid chart type")
            _integer(args.get("chart_index", 0), location + ".chart_index", 0, 100)
            if args.get("cell_range"):
                start, end = api._range_bounds(args["cell_range"])
                rows, cols = self.table_shapes[table_id]
                for address in (start, end):
                    row, col = api.parse_a1(address)
                    if row >= rows or col >= cols:
                        raise UsageError(f"{location}: chart cell_range exceeds table {table_id}")
            self.emit(location, "insert_chart", source, table=self.tables[table_id], **args)
        elif kind == "page_break":
            if in_cell or inline:
                raise UsageError(f"{location}: page break requires body content")
            self.emit(location, "page", source, break_page=True)
        elif kind == "page_hiding":
            for key, value in args.items():
                _bool(value, location + "." + key)
            self.emit(location, "set_page_visibility", source, **args)
        elif kind == "new_number":
            if args.pop("number_type", "page") != "page":
                raise UsageError(f"{location}: only page numbering is supported")
            api._normalize_page_number_restart(args.get("number"))
            self.emit(location, "restart_page_number", source, **args)
        self.content(node.get("page_controls_after", []), location + ".page_controls_after", in_cell=in_cell, depth=depth + 1)
        if node.get("page_break_after"):
            self.emit(location, "page", source, break_page=True)

    def table(self, args, location, source, *, in_cell, depth):
        rows = _integer(args.get("rows"), location + ".rows")
        cols = _integer(args.get("cols"), location + ".cols")
        cells = mapping(args.get("cells"), location + ".cells")
        # Reuse the proven merge/address partition validator, not its legacy
        # paragraphs-only data model. The last anchor may legitimately be empty.
        shell = {k: v for k, v in args.items() if k not in {"id", "cells", "default_margin_mm"}}
        shell["default_margin_mm"] = args.get("default_margin_mm", [0, 0, 0, 0])
        shell["properties"] = {"page_break": "cell", "repeat_header": False, "cell_spacing_mm": 0}
        shell["cells"] = {key: {"paragraphs": [{"text": ""}]} for key in cells}
        last = legacy._last_anchor(rows, cols, args.get("merges", []))
        shell["cells"].setdefault(last, {"paragraphs": [{"text": ""}]})
        try:
            checked = legacy._parse_table(shell, index=0)
        except (ValueError, TypeError) as exc:
            raise UsageError(f"{location}: {exc}") from exc
        number = self.table_count
        self.table_count += 1
        identifier = args.get("id")
        if identifier is not None:
            if not isinstance(identifier, str) or not identifier or identifier in self.tables:
                raise UsageError(f"{location}: table id must be unique non-empty text")
            self.tables[identifier] = number
            self.table_shapes[identifier] = (rows, cols)
        self.emit(location, "create_table", source, rows=rows, cols=cols, header=False, cell_margin=None)
        self.emit(location, "set_table_grid", source, table=number,
                  column_widths_mm=list(checked.column_widths_mm), row_heights_mm=list(checked.row_heights_mm))
        if "properties" in args:
            properties = mapping(args["properties"], location + ".properties", {"repeat_header", "page_break", "cell_spacing_mm"})
            api._normalize_table_properties(page_break=properties.get("page_break", "cell"),
                repeat_header=properties.get("repeat_header", True), cell_spacing_mm=properties.get("cell_spacing_mm", 0))
            self.emit(location, "set_table_properties", source, table=number,
                **{key: properties.get(key) for key in ("page_break", "repeat_header", "cell_spacing_mm")})
        if "default_margin_mm" in args:
            margin = api._normalize_margin(args["default_margin_mm"])
            if margin is None:
                raise UsageError(f"{location}: explicit table margin must have four values")
            self.emit(location, "set_table_inside_margin", source, table=number, **dict(zip(("left", "right", "top", "bottom"), margin)))
        for merged in checked.merges:
            self.emit(location, "merge_cells", source, table=number, cell_range=merged)
        for address in sorted(cells, key=legacy.a1_to_index):
            cell = mapping(cells[address], location + ".cells." + address,
                           {"content", "paragraphs", "images", "fill", "margin_mm", "has_margin", "valign", "borders"})
            cell_location = location + ".cells." + address
            if "content" in cell and ("paragraphs" in cell or "images" in cell):
                raise UsageError(f"{cell_location}: use ordered content or legacy paragraphs/images, not both")
            if "margin_mm" in cell or "has_margin" in cell:
                has_margin = _bool(cell.get("has_margin", True), cell_location + ".has_margin")
                margin = api._normalize_margin(cell.get("margin_mm"))
                if has_margin and margin is None:
                    raise UsageError(f"{cell_location}: explicit margin requires margin_mm")
                self.emit(cell_location, "set_cell_margin", source, table=number, cell_range=address,
                          **({} if margin is None else dict(zip(("left", "right", "top", "bottom"), margin))), has_margin=has_margin)
            if "fill" in cell:
                api._normalize_fill(cell["fill"], allow_empty=False)
                self.emit(cell_location, "set_cell_fill", source, table=number, cell_range=address, fill=cell["fill"])
            if "valign" in cell:
                if cell["valign"] not in {"top", "center", "bottom"}:
                    raise UsageError(f"{cell_location}: invalid valign")
                self.emit(cell_location, "set_valign", source, table=number, cell_range=address, align=cell["valign"])
            for border in sequence(cell.get("borders", []), cell_location + ".borders"):
                mapping(border, cell_location + ".border", {"sides", "line_type", "width", "color"})
                api._normalize_border_sides(border.get("sides", "all"))
                self.emit(cell_location, "set_cell_border", source, table=number, cell_range=address, **border)
            content = cell.get("content")
            if content is None:
                content = [{"kind": "paragraph", **p} for p in sequence(cell.get("paragraphs", []), cell_location + ".paragraphs")]
                content += [{"kind": "picture", **p} for p in sequence(cell.get("images", []), cell_location + ".images")]
            self.emit(cell_location, "move_to_cell", source, table=number, cell=address)
            self.content(content, cell_location + ".content", in_cell=True, depth=depth + 1)
        self.emit(location, "move_to_cell", source, table=number, cell=last)
        self.emit(location, "exit_table", source, destination="parent" if in_cell else "body")
        if "position" in args:
            self.emit(location, "set_table_position", source, table=number, position=checked.position)
        if "review" in args:
            review = _bool(args["review"], location + ".review")
            if review:
                self.emit(location, "layout_review", source, table=number, dry_run=True)


def compile_spec(spec: DocumentSpec, *, check_assets=True) -> tuple[Command, ...]:
    """Validate the entire input, including assets, before any native session."""
    try:
        return Compiler(spec, check_assets=check_assets).compile()
    except (ValueError, TypeError, KeyError) as exc:
        raise UsageError(f"Invalid authoring specification: {exc}") from exc
