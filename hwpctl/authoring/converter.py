"""Conservative, read-only HWPML/HWPX to ordered authoring specification.

The converter is deliberately evidence driven: a source construct is either
represented by a public v2 node or reported as a loss. A report with losses
never publishes an executable specification. No COM session is involved.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any
import xml.etree.ElementTree as ET
import zipfile

from hwpctl.authoring.geometry import CellMeasurement, recover_table_geometry
from hwpctl.authoring.model import SCHEMA, parse_spec
from hwpctl.errors import UsageError
from hwpctl.units import hwpunit_to_mm


_MAX_XML = 64 * 1024 * 1024
_MAX_ASSET = 128 * 1024 * 1024
_MAX_ZIP_TOTAL = 512 * 1024 * 1024
_HEX = re.compile(r"^[0-9a-fA-F]{64}$")
_LINE_WIDTHS = (0.1, 0.12, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5,
                0.6, 0.7, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0)


def _tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1].upper()


def _attrs(node: ET.Element) -> dict[str, str]:
    return {key.rsplit("}", 1)[-1].upper(): value for key, value in node.attrib.items()}


def _attr(node: ET.Element, name: str) -> str | None:
    return _attrs(node).get(name.upper())


def _children(node: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in node if _tag(child) == name.upper()]


def _child(node: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in node if _tag(child) == name.upper()), None)


def _descendant(node: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in node.iter() if _tag(child) == name.upper()), None)


def _xml(data: bytes, label: str) -> ET.Element:
    # UTF-16 declarations also need checking; ElementTree otherwise accepts
    # internal entities before the conversion inventory sees them.
    inspection = data.upper().replace(b"\x00", b"")
    if len(data) > _MAX_XML or b"<!DOCTYPE" in inspection or b"<!ENTITY" in inspection:
        raise UsageError(f"{label}: oversized XML or DTD/entity declaration")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise UsageError(f"{label}: malformed XML: {exc}") from exc


def _hu(raw: str | None, label: str, *, positive: bool = False) -> int:
    if raw is None or not re.fullmatch(r"-?\d+", raw):
        raise ValueError(f"{label}: expected raw HU integer")
    value = int(raw)
    if positive and value <= 0:
        raise ValueError(f"{label}: expected positive raw HU")
    return value


def _mm(value: int) -> float:
    # A binary float at this precision round-trips through mm_to_hwpunit.
    return hwpunit_to_mm(value)


def _boolean(raw: str, label: str) -> bool:
    if raw.lower() in {"1", "true"}:
        return True
    if raw.lower() in {"0", "false"}:
        return False
    raise ValueError(f"{label}: expected explicit 0/1 boolean")


def _color(raw: str | None, label: str) -> str:
    if raw is None:
        raise ValueError(f"{label}: missing color")
    if re.fullmatch(r"#[0-9a-fA-F]{6}", raw):
        return raw.upper()
    if re.fullmatch(r"\d+", raw) and 0 <= int(raw) <= 0xFFFFFF:
        value = int(raw)
        # HWPML numeric COLORREF is BGR, not RGB.
        return f"#{value & 255:02X}{(value >> 8) & 255:02X}{(value >> 16) & 255:02X}"
    raise ValueError(f"{label}: unsupported color encoding")


def _line_width(raw: str | None, label: str) -> float:
    """Map the source's discrete line-width choice, never silently round it."""
    if raw is None:
        raise ValueError(f"{label}: missing line width")
    stripped = raw.strip().lower()
    if stripped.endswith("mm"):
        try:
            width = float(stripped[:-2].strip())
        except ValueError as exc:
            raise ValueError(f"{label}: invalid line width") from exc
        exact = next((item for item in _LINE_WIDTHS if abs(width - item) < 1e-9), None)
    else:
        hu = _hu(stripped, label, positive=True)
        exact = next((item for item in _LINE_WIDTHS
                      if round(item * 7200 / 25.4) == hu), None)
    if exact is None:
        raise ValueError(f"{label}: no exact native line-width choice for {raw!r}")
    return exact


def _address(row: int, column: int) -> str:
    value = column + 1
    letters = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row + 1}"


def _safe_relative(value: str, label: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if not value or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts) or ":" in value:
        raise UsageError(f"{label}: unsafe relative path")
    return path.as_posix()


@dataclass(frozen=True)
class _Asset:
    name: str
    data: bytes
    sha256: str


class _Converter:
    def __init__(self, kind: str, source_sha256: str, roots: list[ET.Element],
                 head: ET.Element | None, available: dict[str, _Asset]) -> None:
        self.kind = kind
        self.source_sha256 = source_sha256
        self.roots = roots
        self.head = head
        self.available = available
        self.entries: list[dict[str, Any]] = []
        self.losses: list[dict[str, Any]] = []
        self.assets: dict[str, dict[str, str]] = {}
        self.used_assets: dict[str, _Asset] = {}
        self.char_styles: dict[str, ET.Element] = {}
        self.para_styles: dict[str, ET.Element] = {}
        self.fonts: dict[str, dict[str, tuple[str, str]]] = {}
        self._index_styles()

    def entry(self, source: str, target: str | None, status: str, detail: str = "") -> None:
        item = {"source": source, "target": target, "status": status}
        if detail:
            item["detail"] = detail
        self.entries.append(item)
        if status == "loss":
            self.losses.append(item)

    def _index_styles(self) -> None:
        if self.head is None:
            return
        for node in self.head.iter():
            name = _tag(node)
            identifier = _attr(node, "id")
            if identifier is not None and name in {"CHARSHAPE", "CHARPR"}:
                self.char_styles[identifier] = node
            if identifier is not None and name in {"PARASHAPE", "PARAPR"}:
                self.para_styles[identifier] = node
            if name == "FONTFACE":
                lang = (_attr(node, "Lang") or "HANGUL").upper()
                self.fonts.setdefault(lang, {}).update({
                    _attr(child, "Id") or "": (_attr(child, "Name") or _attr(child, "face") or "",
                                                     (_attr(child, "Type") or "TTF").lower())
                    for child in node if _tag(child) == "FONT"
                })

    def _style(self, index: str | None, shapes: dict[str, ET.Element], location: str, kind: str) -> ET.Element | None:
        if index is None:
            return None
        node = shapes.get(index)
        if node is None:
            self.entry(location, None, "loss", f"unresolved {kind} reference {index}")
        return node

    def _run_style(self, identifier: str | None, location: str) -> dict[str, Any]:
        style = self._style(identifier, self.char_styles, location, "character style")
        if style is None:
            return {}
        attrs = _attrs(style)
        allowed = {"ID", "HEIGHT", "TEXTCOLOR", "SHADECOLOR", "USEFONTSPACE", "USEKERNING", "SYMMARK", "BORDERFILLIDREF"}
        for key in sorted(set(attrs) - allowed):
            self.entry(location, None, "loss", f"unsupported character property {key}")
        for key, default in {"SHADECOLOR": "none", "USEFONTSPACE": "0", "SYMMARK": "NONE"}.items():
            if key in attrs and attrs[key].upper() != default.upper():
                self.entry(location, None, "loss", f"unsupported character property {key}={attrs[key]}")
        out: dict[str, Any] = {}
        if "HEIGHT" in attrs:
            try:
                out["size"] = _hu(attrs["HEIGHT"], location + ".Height", positive=True) / 100
            except ValueError as exc:
                self.entry(location, None, "loss", str(exc))
        if "TEXTCOLOR" in attrs:
            try:
                out["color"] = _color(attrs["TEXTCOLOR"], location + ".TextColor")
            except ValueError as exc:
                self.entry(location, None, "loss", str(exc))
        if "USEKERNING" in attrs:
            try:
                out["kerning"] = _boolean(attrs["USEKERNING"], location + ".UseKerning")
            except ValueError as exc:
                self.entry(location, None, "loss", str(exc))
        for child in style:
            tag = _tag(child)
            if tag in {"BOLD", "ITALIC", "SUPERSCRIPT", "SUBSCRIPT"}:
                out[tag.lower()] = True
            elif tag in {"FONTID", "FONTREF"}:
                names: dict[str, tuple[str, str]] = {}
                for lang, font_id in _attrs(child).items():
                    found = self.fonts.get(lang, {}).get(font_id)
                    if not found:
                        self.entry(location, None, "loss", f"unresolved font {lang}:{font_id}")
                    else:
                        names[lang.lower()] = found
                if names:
                    if len(set(names.values())) == 1 and next(iter(names.values()))[1] == "ttf":
                        out["font"] = next(iter(names.values()))[0]
                    else:
                        out["font_slots"] = {lang: {"name": name, "type": font_type}
                                             for lang, (name, font_type) in names.items()}
            elif tag in {"RATIO", "SPACING", "RELSZ", "OFFSET"}:
                expected = "100" if tag in {"RATIO", "RELSZ"} else "0"
                values = set(_attrs(child).values())
                if values != {expected}:
                    self.entry(location, None, "loss", f"non-default language-specific {tag}")
            elif tag == "UNDERLINE":
                if (_attr(child, "type") or "NONE").upper() != "NONE":
                    self.entry(location, None, "loss", "underline requires exact style mapping")
            elif tag == "STRIKEOUT":
                if (_attr(child, "shape") or "NONE").upper() != "NONE":
                    self.entry(location, None, "loss", "strikeout requires exact style mapping")
            elif tag in {"OUTLINE", "SHADOW"}:
                if (_attr(child, "type") or "NONE").upper() != "NONE":
                    self.entry(location, None, "loss", f"non-default character {tag}")
            else:
                self.entry(location, None, "loss", f"unsupported character style child {tag}")
        return out

    def _paragraph_style(self, identifier: str | None, location: str) -> dict[str, Any]:
        style = self._style(identifier, self.para_styles, location, "paragraph style")
        if style is None:
            return {}
        out: dict[str, Any] = {}
        attrs = _attrs(style)
        allowed = {"ID", "ALIGN", "TABPRIDREF", "CONDENSE", "FONTLINEHEIGHT", "SNAPTOGRID", "SUPPRESSLINENUMBERS", "CHECKED", "TEXTDIR"}
        for key in sorted(set(attrs) - allowed):
            self.entry(location, None, "loss", f"unsupported paragraph property {key}")
        defaults = {"CONDENSE": "0", "FONTLINEHEIGHT": "0", "SNAPTOGRID": "1", "SUPPRESSLINENUMBERS": "0", "CHECKED": "0", "TEXTDIR": "LTR"}
        for key, default in defaults.items():
            if key in attrs and attrs[key].upper() != default:
                self.entry(location, None, "loss", f"unsupported paragraph property {key}={attrs[key]}")
        align = attrs.get("ALIGN")
        for child in style:
            tag = _tag(child)
            if tag == "ALIGN":
                align = _attr(child, "horizontal")
            elif tag == "PARAMARGIN":
                for source, target in {"LEFT": "left_margin_mm", "RIGHT": "right_margin_mm", "INDENT": "first_line_indent_mm", "PREV": "before_spacing_mm", "NEXT": "after_spacing_mm"}.items():
                    raw = _attr(child, source)
                    if raw is not None:
                        try:
                            out[target] = _mm(_hu(raw, location + "." + source))
                        except ValueError as exc:
                            self.entry(location, None, "loss", str(exc))
                if _attr(child, "LineSpacing") is not None:
                    try:
                        out["line_spacing_percent"] = int(_attr(child, "LineSpacing"))
                    except (ValueError, TypeError):
                        self.entry(location, None, "loss", "invalid line spacing")
                for key in set(_attrs(child)) - {"LEFT", "RIGHT", "INDENT", "PREV", "NEXT", "LINESPACING"}:
                    self.entry(location, None, "loss", f"unsupported paragraph margin {key}")
            elif tag == "LINESPACING":
                if (_attr(child, "type") or "PERCENT").upper() != "PERCENT":
                    self.entry(location, None, "loss", "non-percent line spacing")
                else:
                    try:
                        out["line_spacing_percent"] = int(_attr(child, "value"))
                    except (ValueError, TypeError):
                        self.entry(location, None, "loss", "invalid line spacing")
            elif tag == "HEADING":
                if (_attr(child, "type") or "NONE").upper() != "NONE":
                    self.entry(location, None, "loss", "outline heading requires exact mapping")
            elif tag == "BREAKSETTING":
                setting = _attrs(child)
                word_break = {"BREAKLATINWORD": "break_latin_word", "BREAKNONLATINWORD": "break_non_latin_word"}
                for key, target in word_break.items():
                    if key in setting:
                        mapped = {"KEEP_WORD": "keep_word", "BREAK_WORD": "break_word"}.get(setting[key].upper())
                        if mapped is None:
                            self.entry(location, None, "loss", f"unsupported {key}")
                        else:
                            out[target] = mapped
                defaults = {"WIDOWORPHAN": "0", "KEEPWITHNEXT": "0", "KEEPLINES": "0", "PAGEBREAKBEFORE": "0", "LINEWRAP": "BREAK"}
                for key, default in defaults.items():
                    if key in setting and setting[key].upper() != default:
                        self.entry(location, None, "loss", f"unsupported paragraph {key}={setting[key]}")
                for key in set(setting) - set(word_break) - set(defaults):
                    self.entry(location, None, "loss", f"unsupported paragraph break {key}")
            elif tag == "AUTOSPACING":
                if any(value != "0" for value in _attrs(child).values()):
                    self.entry(location, None, "loss", "non-default automatic spacing")
            elif tag == "SWITCH":
                branches: list[dict[str, Any]] = []
                for branch in child:
                    if _tag(branch) not in {"CASE", "DEFAULT"}:
                        self.entry(location, None, "loss", "unknown conditional paragraph branch")
                        continue
                    layout: dict[str, Any] = {}
                    for item in branch:
                        if _tag(item) == "MARGIN":
                            fields = {"LEFT": "left_margin_mm", "RIGHT": "right_margin_mm",
                                      "INTENT": "first_line_indent_mm", "INDENT": "first_line_indent_mm",
                                      "PREV": "before_spacing_mm", "NEXT": "after_spacing_mm"}
                            for property_node in item:
                                key = _tag(property_node)
                                if key not in fields or (_attr(property_node, "unit") or "HWPUNIT").upper() != "HWPUNIT":
                                    self.entry(location, None, "loss", f"unsupported switched margin {key}")
                                    continue
                                try:
                                    layout[fields[key]] = _mm(_hu(_attr(property_node, "value"), location + "." + key))
                                except ValueError as exc:
                                    self.entry(location, None, "loss", str(exc))
                        elif _tag(item) == "LINESPACING":
                            if (_attr(item, "type") or "PERCENT").upper() != "PERCENT":
                                self.entry(location, None, "loss", "non-percent switched line spacing")
                            else:
                                try:
                                    layout["line_spacing_percent"] = int(_attr(item, "value"))
                                except (ValueError, TypeError):
                                    self.entry(location, None, "loss", "invalid switched line spacing")
                        else:
                            self.entry(location, None, "loss", f"unsupported switched paragraph item {_tag(item)}")
                    branches.append(layout)
                if not branches or any(layout != branches[0] for layout in branches[1:]):
                    self.entry(location, None, "loss", "conditional paragraph variants disagree")
                else:
                    out.update(branches[0])
            elif tag == "BORDER":
                properties = _attrs(child)
                reference = properties.get("BORDERFILLIDREF")
                if any(value != "0" for key, value in properties.items() if key != "BORDERFILLIDREF"):
                    self.entry(location, None, "loss", "paragraph border offsets or options")
                if reference is not None and not self._empty_border(reference):
                    self.entry(location, None, "loss", "non-empty paragraph border")
            else:
                self.entry(location, None, "loss", f"unsupported paragraph style child {tag}")
        if align:
            mapped = {"LEFT": "left", "CENTER": "center", "RIGHT": "right", "JUSTIFY": "justify"}.get(align.upper())
            if mapped is None:
                self.entry(location, None, "loss", f"unsupported paragraph alignment {align}")
            else:
                out["align"] = mapped
        return out

    def _empty_border(self, identifier: str) -> bool:
        if self.head is None:
            return False
        border = next((node for node in self.head.iter()
                       if _tag(node) == "BORDERFILL" and _attr(node, "id") == identifier), None)
        if border is None:
            return False
        for child in border.iter():
            tag = _tag(child)
            if tag in {"LEFTBORDER", "RIGHTBORDER", "TOPBORDER", "BOTTOMBORDER", "SLASH", "BACKSLASH"}:
                if (_attr(child, "type") or "NONE").upper() != "NONE":
                    return False
            if tag in {"WINDOWBRUSH", "WINBRUSH"}:
                if (_attr(child, "faceColor") or "none").lower() not in {"none", "#ffffffff", "4294967295"}:
                    return False
            if tag in {"GRADATION", "GRADIENT", "GRADIENTFILL", "IMAGEBRUSH"}:
                return False
        return True

    def _object_frame(self, node: ET.Element, source: str, result: dict[str, Any],
                      *, need_size: bool) -> None:
        """Read common SHAPEOBJECT/SIZE/POSITION facts without guessing anchors.

        HWPML stores these as children of the object. HWPX uses the same
        logical fields under ``shapeObject`` with ``sz``/``pos`` spellings.
        A missing position is inline only when no explicit floating flag is
        present. Floating coordinates must be stated in raw HU.
        """
        shape = _child(node, "SHAPEOBJECT")
        if shape is None:
            shape = node
        attrs = _attrs(shape)
        if shape is not node:
            for key in set(attrs) - {"INSTID", "ZORDER", "NUMBERINGTYPE", "TEXTWRAP", "TEXTFLOW", "LOCK", "ID"}:
                self.entry(source, None, "loss", f"unsupported shape-object property {key}")
            for key, allowed in {"ZORDER": {"0"}, "NUMBERINGTYPE": {"NONE"},
                                 "TEXTFLOW": {"BOTHSIDES"}, "LOCK": {"0", "FALSE"}}.items():
                if key in attrs and attrs[key].upper() not in allowed:
                    self.entry(source, None, "loss", f"unsupported shape-object property {key}={attrs[key]}")
        size = _child(shape, "SIZE")
        if size is None:
            size = _child(shape, "SZ")
        if need_size:
            source_size = size if size is not None else node
            dimensions = _attrs(source_size)
            for key, target in (("WIDTH", "width_mm"), ("HEIGHT", "height_mm")):
                try:
                    result[target] = _mm(_hu(dimensions.get(key), source + "." + key, positive=True))
                except ValueError as exc:
                    self.entry(source, None, "loss", str(exc))
            if size is not None:
                for key in set(dimensions) - {"WIDTH", "HEIGHT", "WIDTHRELTO", "HEIGHTRELTO", "PROTECT"}:
                    self.entry(source, None, "loss", f"unsupported object size {key}")
                for key in ("WIDTHRELTO", "HEIGHTRELTO"):
                    if dimensions.get(key, "ABSOLUTE").upper() != "ABSOLUTE":
                        self.entry(source, None, "loss", f"relative object dimension {key}")
                if dimensions.get("PROTECT", "0").upper() not in {"0", "FALSE"}:
                    self.entry(source, None, "loss", "protected object size")
        pos = _child(shape, "POSITION")
        if pos is None:
            pos = _child(shape, "POS")
        settings = _attrs(pos) if pos is not None else {}
        root_flag = _attr(node, "TreatAsChar")
        flag = settings.get("TREATASCHAR", root_flag)
        if flag is None and pos is None:
            result["position"] = {"mode": "inline"}
        elif flag is None:
            self.entry(source, None, "loss", "object position lacks TreatAsChar")
        else:
            try:
                inline = _boolean(flag, source + ".TreatAsChar")
            except ValueError as exc:
                self.entry(source, None, "loss", str(exc))
                inline = True
            if inline:
                result["position"] = {"mode": "inline"}
                if "AFFECTLSPACING" in settings:
                    try:
                        result["position"]["affect_line_spacing"] = _boolean(settings["AFFECTLSPACING"], source + ".AffectLSpacing")
                    except ValueError as exc:
                        self.entry(source, None, "loss", str(exc))
            else:
                required = {"HORZRELTO", "VERTRELTO", "HORZALIGN", "VERTALIGN", "HORZOFFSET", "VERTOFFSET"}
                absent = sorted(required - set(settings))
                if absent:
                    self.entry(source, None, "loss", "floating position lacks " + ", ".join(absent))
                wrap = attrs.get("TEXTWRAP", "SQUARE")
                wraps = {"SQUARE": "square", "TOPANDBOTTOM": "top_and_bottom",
                         "BEHINDTEXT": "behind_text", "INFRONTOFTEXT": "in_front_of_text"}
                if wrap.upper().replace("_", "") not in wraps:
                    self.entry(source, None, "loss", f"unrepresentable or absent floating text wrap {wrap!r}")
                hrel = settings.get("HORZRELTO", "").lower()
                vrel = settings.get("VERTRELTO", "").lower()
                halign = settings.get("HORZALIGN", "").lower()
                valign = settings.get("VERTALIGN", "").lower()
                if hrel not in {"paper", "page", "column", "para"} or vrel not in {"paper", "page", "para"}:
                    self.entry(source, None, "loss", "unsupported floating relative anchor")
                if halign not in {"left", "center", "right"} or valign not in {"top", "center", "bottom"}:
                    self.entry(source, None, "loss", "unsupported floating alignment")
                try:
                    result["position"] = {"mode": "floating", "horizontal_relative_to": hrel,
                                          "vertical_relative_to": vrel, "horizontal_align": halign,
                                          "vertical_align": valign,
                                          "x_mm": _mm(_hu(settings.get("HORZOFFSET"), source + ".HorzOffset")),
                                          "y_mm": _mm(_hu(settings.get("VERTOFFSET"), source + ".VertOffset")),
                                          "wrap": wraps.get((wrap or "").upper().replace("_", ""), "square"),
                                          # HWPML defaults are false; the authoring API defaults differ.
                                          "flow_with_text": _boolean(settings.get("FLOWWITHTEXT", "false"), source + ".FlowWithText"),
                                          "allow_overlap": _boolean(settings.get("ALLOWOVERLAP", "false"), source + ".AllowOverlap")}
                except ValueError as exc:
                    self.entry(source, None, "loss", str(exc))
        for key in set(settings) - {"TREATASCHAR", "AFFECTLSPACING", "HORZRELTO", "VERTRELTO",
                                    "HORZALIGN", "VERTALIGN", "HORZOFFSET", "VERTOFFSET",
                                    "FLOWWITHTEXT", "ALLOWOVERLAP", "HOLDANCHORANDSO"}:
            self.entry(source, None, "loss", f"unsupported object position {key}")
        if settings.get("HOLDANCHORANDSO", "false").lower() not in {"0", "false"}:
            self.entry(source, None, "loss", "hold-anchor-and-object behavior cannot be authored")
        outside = _child(shape, "OUTSIDEMARGIN")
        if outside is None:
            outside = _child(shape, "OUTMARGIN")
        if outside is not None:
            for key in set(_attrs(outside)) - {"LEFT", "RIGHT", "TOP", "BOTTOM"}:
                self.entry(source, None, "loss", f"unsupported outside margin {key}")
            try:
                margin = [_mm(_hu(_attr(outside, side), source + ".outside." + side))
                          for side in ("Left", "Right", "Top", "Bottom")]
                result.setdefault("position", {"mode": "inline"})["outside_margin_mm"] = margin
            except ValueError as exc:
                self.entry(source, None, "loss", str(exc))
        for child in shape if shape is not node else []:
            if _tag(child) not in {"SIZE", "SZ", "POSITION", "POS", "OUTSIDEMARGIN"}:
                self.entry(source + "/" + _tag(child), None, "loss", "unsupported shape-object child")

    def _page(self, section: ET.Element, location: str) -> dict[str, Any]:
        page = _child(section, "PAGEDEF")
        if page is None:
            page = _descendant(section, "PAGEPR")
        if page is None:
            self.entry(location, location + ".page", "inherited", "no explicit page definition")
            return {}
        attrs = _attrs(page)
        margin = _child(page, "PAGEMARGIN")
        if margin is None:
            margin = _child(page, "MARGIN")
        output: dict[str, Any] = {}
        for source, target in {"WIDTH": "paper_width", "HEIGHT": "paper_height"}.items():
            raw = attrs.get(source)
            if raw is not None:
                try:
                    output[target] = _mm(_hu(raw, location + "." + source, positive=True))
                except ValueError as exc:
                    self.entry(location, None, "loss", str(exc))
        if margin is not None:
            for source, target in {"LEFT": "left", "RIGHT": "right", "TOP": "top", "BOTTOM": "bottom", "HEADER": "header", "FOOTER": "footer", "GUTTER": "gutter"}.items():
                raw = _attr(margin, source)
                if raw is not None:
                    try:
                        output[target] = _mm(_hu(raw, location + ".margin." + source))
                    except ValueError as exc:
                        self.entry(location, None, "loss", str(exc))
            for key in set(_attrs(margin)) - {"LEFT", "RIGHT", "TOP", "BOTTOM", "HEADER", "FOOTER", "GUTTER"}:
                self.entry(location, None, "loss", f"unsupported page margin {key}")
        for key in set(attrs) - {"WIDTH", "HEIGHT", "LANDSCAPE", "GUTTERTYPE"}:
            self.entry(location, None, "loss", f"unsupported page property {key}")
        if "GUTTERTYPE" in attrs and attrs["GUTTERTYPE"] != "LEFT_ONLY":
            self.entry(location, None, "loss", "unsupported gutter type")
        # Width and height carry the physical page orientation. HWPX WIDELY
        # occurs in stock portrait documents; do not infer from that enum.
        self.entry(location, location + ".page", "converted", "raw HU page dimensions and margins")
        return output

    def _section_controls(self, section: ET.Element, source: str, target: str) -> list[dict[str, Any]]:
        declaration = _descendant(section, "SECPR") if self.kind == "hwpx" else _descendant(section, "SECDEF")
        if declaration is None:
            return []
        controls: list[dict[str, Any]] = []
        attrs = _attrs(declaration)
        if attrs.get("TEXTDIRECTION", "HORIZONTAL").upper() != "HORIZONTAL":
            self.entry(source, None, "loss", "non-horizontal section text direction")
        for key in set(attrs) - {"ID", "TEXTDIRECTION", "SPACECOLUMNS", "TABSTOP", "TABSTOPVAL", "TABSTOPUNIT",
                                 "OUTLINESHAPEIDREF", "MEMOSHAPEIDREF", "TEXTVERTICALWIDTHHEAD", "MASTERPAGECNT"}:
            self.entry(source, None, "loss", f"unsupported section property {key}")
        if attrs.get("MASTERPAGECNT") not in {None, "0"}:
            self.entry(source, None, "loss", "master pages are not authored")
        for child in declaration:
            tag = _tag(child)
            here = source + "/" + tag
            if tag == "PAGEPR" or tag == "PAGEDEF":
                continue
            if tag in {"FOOTNOTEPR", "ENDNOTEPR"}:
                # Settings without a note control do not add visible content.
                continue
            if tag == "GRID":
                if any(value != "0" for value in _attrs(child).values()):
                    self.entry(here, None, "loss", "non-default section text grid")
                continue
            if tag == "STARTNUM":
                properties = _attrs(child)
                if any(value != "0" for key, value in properties.items() if key in {"PIC", "TBL", "EQUATION"}):
                    self.entry(here, None, "loss", "non-page numbering restart")
                if properties.get("PAGESTARTSON", "BOTH").upper() != "BOTH":
                    self.entry(here, None, "loss", "page start parity is unsupported")
                page_number = properties.get("PAGE", "0")
                if page_number != "0":
                    try:
                        number = int(page_number)
                        controls.append({"kind": "new_number", "number": number, "source": here})
                        self.entry(here, target + f"[{len(controls)-1}]", "converted", "section page restart")
                    except ValueError:
                        self.entry(here, None, "loss", "invalid section page restart")
                continue
            if tag == "VISIBILITY":
                expected = {"HIDEFIRSTHEADER": "0", "HIDEFIRSTFOOTER": "0", "HIDEFIRSTMASTERPAGE": "0",
                            "BORDER": "SHOW_ALL", "FILL": "SHOW_ALL", "HIDEFIRSTPAGENUM": "0",
                            "HIDEFIRSTEMPTYLINE": "0", "SHOWLINENUMBER": "0"}
                properties = _attrs(child)
                for key, value in properties.items():
                    if key not in expected or value.upper() != expected[key]:
                        self.entry(here, None, "loss", f"unsupported section visibility {key}={value}")
                continue
            if tag == "LINENUMBERSHAPE":
                if any(value != "0" for value in _attrs(child).values()):
                    self.entry(here, None, "loss", "line numbering is unsupported")
                continue
            if tag == "PAGEBORDERFILL":
                border = _attr(child, "borderFillIDRef")
                if border is not None and not self._empty_border(border):
                    self.entry(here, None, "loss", "non-empty page border or fill")
                continue
            self.entry(here, None, "loss", f"unsupported section declaration {tag}")
        return controls

    def _inline_children(self, parent: ET.Element, source: str, target: str, style: dict[str, Any],
                         *, depth: int) -> list[dict[str, Any]]:
        if depth > 32:
            self.entry(source, None, "loss", "content nesting exceeds 32")
            return []
        result: list[dict[str, Any]] = []

        def append_text(value: str | None, location: str) -> None:
            if value:
                result.append({"kind": "run", "text": value, **style, "source": location})
                self.entry(location, target + f"[{len(result)-1}]", "preserved")

        append_text(parent.text, source + "/text()")
        for index, child in enumerate(parent):
            here = f"{source}/{_tag(child)}[{index}]"
            tag = _tag(child)
            if tag in {"CHAR", "T"}:
                if list(child):
                    self.entry(here, None, "loss", "nested markup inside text run")
                if _attrs(child):
                    self.entry(here, None, "loss", f"text child attributes require explicit mapping: {sorted(_attrs(child))}")
                append_text(child.text, here)
            elif tag in {"LINEBREAK", "TAB", "NBSPACE", "FWSPACE", "FIXEDWIDTHSPACE"}:
                append_text({"LINEBREAK": "\n", "TAB": "\t"}.get(tag, " "), here)
            elif tag in {"TABLE", "TBL"}:
                result.append(self._table(child, here, target + f"[{len(result)}]", depth + 1))
            elif tag in {"PICTURE", "PIC"}:
                result.append(self._picture(child, here, target + f"[{len(result)}]"))
            elif tag in {"SECDEF", "SECPR"}:
                # Section page properties are read once by _page.
                pass
            elif tag == "CTRL":
                col = _child(child, "COLPR")
                props = _attrs(col) if col is not None else {}
                if col is None or len(child) != 1 or props.get("COLCOUNT") != "1":
                    self.entry(here, None, "loss", "unsupported structural control")
                elif any(props.get(key) != value for key, value in
                         {"TYPE": "NEWSPAPER", "LAYOUT": "LEFT", "SAMESZ": "1", "SAMEGAP": "0"}.items()):
                    self.entry(here, None, "loss", "non-default column control")
                else:
                    self.entry(here, None, "converted", "single-column declaration")
            elif tag in {"PAGEHIDE", "HIDE"}:
                result.append(self._page_hide(child, here, target + f"[{len(result)}]"))
            elif tag in {"NEWNUM", "NEWNUMBER"}:
                result.append(self._new_number(child, here, target + f"[{len(result)}]"))
            elif tag in {"RECTANGLE", "RECT", "ELLIPSE", "LINE"}:
                result.append(self._drawing(child, here, target + f"[{len(result)}]"))
            elif tag == "CHART":
                self._chart(child, here)
            elif tag in {"DRAWINGOBJECT", "SHAPEOBJECT", "TEXTBOX"}:
                self.entry(here, None, "loss", f"drawing control lacks a verified native object mapping: {tag}")
            else:
                self.entry(here, None, "loss", f"unsupported inline control {tag}")
            append_text(child.tail, here + "/tail()")
        return result

    def _paragraph(self, node: ET.Element, source: str, target: str, *, depth: int) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": "paragraph", "source": source}
        attrs = _attrs(node)
        style_id = attrs.get("PARASHAPE") if self.kind == "hwpml" else attrs.get("PARAPRIDREF")
        if style_id is not None:
            style = self._paragraph_style(style_id, source + ".paragraph-style")
            if style:
                result["paragraph"] = style
        for key in set(attrs) - {"ID", "PARASHAPE", "PARAPRIDREF", "STYLE", "STYLEIDREF", "PAGEBREAK", "COLUMNBREAK", "MERGED"}:
            self.entry(source, None, "loss", f"unsupported paragraph property {key}")
        if attrs.get("STYLE", attrs.get("STYLEIDREF", "0")) not in {"0", ""}:
            self.entry(source, None, "loss", "named paragraph style is not preserved")
        for key in ("COLUMNBREAK", "MERGED"):
            if attrs.get(key) not in {None, "0"}:
                self.entry(source, None, "loss", f"unsupported paragraph property {key}={attrs[key]}")
        if attrs.get("PAGEBREAK") not in {None, "0"}:
            try:
                result["page_break_before"] = _boolean(attrs["PAGEBREAK"], source + ".PageBreak")
            except ValueError as exc:
                self.entry(source, None, "loss", str(exc))
        parts: list[dict[str, Any]] = []
        for index, child in enumerate(node):
            here = f"{source}/{_tag(child)}[{index}]"
            if _tag(child) not in {"TEXT", "RUN"}:
                if _tag(child) == "LINESEGARRAY":
                    self.entry(here, None, "converted", "computed line layout cache")
                else:
                    self.entry(here, None, "loss", f"unsupported paragraph child {_tag(child)}")
                continue
            run_attrs = _attrs(child)
            for key in set(run_attrs) - {"CHARSHAPE", "CHARPRIDREF"}:
                self.entry(here, None, "loss", f"unsupported text run property {key}")
            char_id = _attr(child, "CharShape") if self.kind == "hwpml" else _attr(child, "charPrIDRef")
            style = self._run_style(char_id, here + ".character-style") if char_id is not None else {}
            parts.extend(self._inline_children(child, here, target + ".content", style, depth=depth))
        if parts and all(part["kind"] == "run" for part in parts):
            result["runs"] = [{key: value for key, value in run.items() if key not in {"kind", "source"}} for run in parts]
        elif parts:
            result["content"] = parts
        else:
            result["text"] = ""
        self.entry(source, target, "preserved", "ordered paragraph content")
        return result

    def _content(self, parent: ET.Element, source: str, target: str, *, depth: int,
                 start_index: int = 0) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = []
        for index, child in enumerate(parent):
            here = f"{source}/{_tag(child)}[{index}]"
            tag = _tag(child)
            if tag == "P":
                content.append(self._paragraph(child, here, target + f"[{start_index + len(content)}]", depth=depth))
            elif tag in {"PAGEDEF", "SECPR"}:
                continue
            else:
                self.entry(here, None, "loss", f"unsupported block {tag}")
        return content

    def _table(self, table: ET.Element, source: str, target: str, depth: int) -> dict[str, Any]:
        attrs = _attrs(table)
        row_nodes = _children(table, "ROW") or _children(table, "TR")
        try:
            rows = int(attrs.get("ROWCOUNT", attrs.get("ROWCNT", str(len(row_nodes)))))
            cols = int(attrs.get("COLCOUNT", attrs.get("COLCNT", "0")))
            if rows < 1 or cols < 1 or rows > 256 or cols > 256:
                raise ValueError("table dimensions outside 1..256")
        except ValueError as exc:
            self.entry(source, None, "loss", f"invalid table dimensions: {exc}")
            return {"kind": "table", "rows": 1, "cols": 1, "column_widths_mm": [1], "row_heights_mm": [1], "cells": {}, "source": source}
        result: dict[str, Any] = {"kind": "table", "rows": rows, "cols": cols, "cells": {}, "source": source}
        measurements: list[CellMeasurement] = []
        merges: list[str] = []
        for row_index, row in enumerate(row_nodes):
            if _attrs(row):
                self.entry(f"{source}/ROW[{row_index}]", None, "loss", "row properties require explicit mapping")
            for cell_index, cell in enumerate(row):
                if _tag(cell) not in {"CELL", "TC"}:
                    self.entry(f"{source}/ROW[{row_index}]/{_tag(cell)}[{cell_index}]", None, "loss", "unsupported table row child")
                    continue
                here = f"{source}/ROW[{row_index}]/CELL[{cell_index}]"
                info = _attrs(cell)
                for child in cell:
                    if _tag(child) in {"CELLADDR", "CELLSPAN", "CELLSZ"}:
                        info.update(_attrs(child))
                    elif _tag(child) not in {"PARALIST", "SUBLIST", "CELLMARGIN", "MARGIN"}:
                        self.entry(here + "/" + _tag(child), None, "loss", "unsupported cell child")
                for key in set(info) - {"ROWADDR", "COLADDR", "ROWSPAN", "COLSPAN", "WIDTH", "HEIGHT",
                                        "HASMARGIN", "BORDERFILL", "BORDERFILLIDREF", "ID", "NAME",
                                        "HEADER", "PROTECT", "EDITABLE", "DIRTY"}:
                    self.entry(here, None, "loss", f"unsupported cell property {key}")
                for key, expected in {"NAME": "", "HEADER": "0", "PROTECT": "0", "EDITABLE": "0", "DIRTY": "0"}.items():
                    if key in info and info[key] != expected:
                        self.entry(here, None, "loss", f"unsupported cell property {key}={info[key]}")
                try:
                    row_addr = int(info.get("ROWADDR", row_index))
                    col_addr = int(info["COLADDR"])
                    row_span = int(info.get("ROWSPAN", "1"))
                    col_span = int(info.get("COLSPAN", "1"))
                    width = _hu(info.get("WIDTH"), here + ".Width", positive=True) if "WIDTH" in info else None
                    height = _hu(info.get("HEIGHT"), here + ".Height", positive=True) if "HEIGHT" in info else None
                    measurement = CellMeasurement(row_addr, col_addr, row_span, col_span, width, height, here)
                    measurements.append(measurement)
                except (ValueError, KeyError) as exc:
                    self.entry(here, None, "loss", f"invalid cell geometry: {exc}")
                    continue
                addr = _address(row_addr, col_addr)
                if addr in result["cells"]:
                    self.entry(here, None, "loss", f"duplicate cell address {addr}")
                cell_target = target + ".cells." + addr
                sub = _child(cell, "PARALIST")
                if sub is None:
                    sub = _child(cell, "SUBLIST")
                content = self._content(sub, here + "/content", cell_target + ".content", depth=depth) if sub is not None else []
                spec_cell: dict[str, Any] = {"content": content}
                if sub is None:
                    self.entry(here, None, "loss", "cell content list absent")
                valign = _attr(sub, "VertAlign") if sub is not None else None
                if sub is not None:
                    sub_defaults = {"ID": "", "TEXTDIRECTION": "HORIZONTAL", "LINEWRAP": "BREAK",
                                    "LINKLISTIDREF": "0", "LINKLISTNEXTIDREF": "0", "TEXTWIDTH": "0",
                                    "TEXTHEIGHT": "0", "HASTEXTREF": "0", "HASNUMREF": "0"}
                    for key in set(_attrs(sub)) - {"VERTALIGN"} - set(sub_defaults):
                        self.entry(here, None, "loss", f"unsupported cell content property {key}")
                    for key, expected in sub_defaults.items():
                        if _attr(sub, key) not in {None, expected}:
                            self.entry(here, None, "loss", f"unsupported cell content property {key}={_attr(sub, key)}")
                if valign is not None:
                    mapped = {"TOP": "top", "CENTER": "center", "BOTTOM": "bottom"}.get(valign.upper())
                    if mapped is None:
                        self.entry(here, None, "loss", f"unsupported vertical alignment {valign}")
                    else:
                        spec_cell["valign"] = mapped
                has_margin = info.get("HASMARGIN")
                if has_margin is not None:
                    try:
                        spec_cell["has_margin"] = _boolean(has_margin, here + ".hasMargin")
                    except ValueError as exc:
                        self.entry(here, None, "loss", str(exc))
                margin = _child(cell, "CELLMARGIN")
                if margin is None:
                    margin = _child(cell, "MARGIN")
                if margin is not None:
                    try:
                        spec_cell["margin_mm"] = [_mm(_hu(_attr(margin, side), here + ".margin." + side)) for side in ("Left", "Right", "Top", "Bottom")]
                    except ValueError as exc:
                        self.entry(here, None, "loss", str(exc))
                if spec_cell.get("has_margin") is True and "margin_mm" not in spec_cell:
                    self.entry(here, None, "loss", "explicit hasMargin=1 without raw cell margin")
                if "BORDERFILL" in info or "BORDERFILLIDREF" in info:
                    border_id = info.get("BORDERFILL", info.get("BORDERFILLIDREF"))
                    self._border(border_id, spec_cell, here)
                result["cells"][addr] = spec_cell
                self.entry(here, cell_target, "preserved", "raw HU cell dimensions and ordered content")
                if row_span > 1 or col_span > 1:
                    merges.append(f"{addr}:{_address(row_addr + row_span - 1, col_addr + col_span - 1)}")
        try:
            geometry = recover_table_geometry(rows, cols, measurements)
            result["raw_hu"] = {"columns": [int(value) if value is not None and value.denominator == 1 else None for value in geometry.columns.tracks_hwp],
                                "rows": [int(value) if value is not None and value.denominator == 1 else None for value in geometry.rows.tracks_hwp],
                                "column_status": geometry.columns.status, "row_status": geometry.rows.status}
            if not geometry.exact or any(value is None or value.denominator != 1 for value in (*geometry.columns.tracks_hwp, *geometry.rows.tracks_hwp)):
                self.entry(source, None, "loss", f"table grid unresolved: columns={geometry.columns.status}, rows={geometry.rows.status}; {'; '.join(geometry.issues)}")
            else:
                result["column_widths_mm"] = [_mm(int(value)) for value in geometry.columns.tracks_hwp]
                result["row_heights_mm"] = [_mm(int(value)) for value in geometry.rows.tracks_hwp]
        except ValueError as exc:
            self.entry(source, None, "loss", f"table grid invalid: {exc}")
        if merges:
            result["merges"] = merges
        result["exit_cell"] = self._last_anchor(rows, cols, measurements)
        for child in table:
            if _tag(child) in {"ROW", "TR"}:
                continue
            if _tag(child) == "SHAPEOBJECT":
                continue
            if _tag(child) in {"INSIDEMARGIN", "INMARGIN"}:
                try:
                    result["default_margin_mm"] = [
                        _mm(_hu(_attr(child, side), source + ".insideMargin." + side))
                        for side in ("Left", "Right", "Top", "Bottom")]
                except ValueError as exc:
                    self.entry(source, None, "loss", str(exc))
            elif _tag(child) in {"SZ", "POS", "OUTMARGIN", "SHAPECOMMENT"}:
                if _tag(child) == "SHAPECOMMENT" and ((_attrs(child)) or (child.text or "").strip() or list(child)):
                    self.entry(source, None, "loss", "nonempty table shape comment")
            elif _tag(child) == "CELLZONELIST":
                if list(child) or any(value != "0" for value in _attrs(child).values()):
                    self.entry(source, None, "loss", "nonempty table cell zones are not authored")
            else:
                self.entry(source + "/" + _tag(child), None, "loss", "unsupported table child")
        properties: dict[str, Any] = {}
        if "REPEATHEADER" in attrs:
            try:
                properties["repeat_header"] = _boolean(attrs["REPEATHEADER"], source + ".repeatHeader")
            except ValueError as exc:
                self.entry(source, None, "loss", str(exc))
        if "CELLSPACING" in attrs:
            try:
                properties["cell_spacing_mm"] = _mm(_hu(attrs["CELLSPACING"], source + ".cellSpacing"))
            except ValueError as exc:
                self.entry(source, None, "loss", str(exc))
        if "PAGEBREAK" in attrs:
            page_break = {"TABLE": "table", "CELL": "cell", "NONE": "none"}.get(attrs["PAGEBREAK"].upper())
            if page_break is None:
                self.entry(source, None, "loss", f"unsupported table page break {attrs['PAGEBREAK']}")
            else:
                properties["page_break"] = page_break
        if properties:
            result["properties"] = properties
        for key in set(attrs) - {"ROWCOUNT", "ROWCNT", "COLCOUNT", "COLCNT", "REPEATHEADER", "CELLSPACING", "PAGEBREAK", "TREATASCHAR", "ID",
                                 "ZORDER", "NUMBERINGTYPE", "TEXTWRAP", "TEXTFLOW", "LOCK", "DROPCAPSTYLE", "BORDERFILLIDREF", "NOADJUST"}:
            self.entry(source, None, "loss", f"unsupported table property {key}")
        for key, expected in {"ZORDER": "0", "NUMBERINGTYPE": "TABLE", "TEXTWRAP": "TOP_AND_BOTTOM",
                              "TEXTFLOW": "BOTH_SIDES", "LOCK": "0", "DROPCAPSTYLE": "NONE", "NOADJUST": "0"}.items():
            if key in attrs and attrs[key].upper() != expected:
                self.entry(source, None, "loss", f"unsupported table property {key}={attrs[key]}")
        if "BORDERFILLIDREF" in attrs and any(
            _attr(cell, "borderFillIDRef") not in {None, attrs["BORDERFILLIDREF"]}
            for row in row_nodes for cell in row if _tag(cell) in {"CELL", "TC"}
        ):
            self.entry(source, None, "loss", "table outer border-fill differs from one or more cells")
        size = _child(table, "SZ")
        if size is not None and "column_widths_mm" in result and "row_heights_mm" in result:
            try:
                width_hu = _hu(_attr(size, "width"), source + ".sz.width", positive=True)
                height_hu = _hu(_attr(size, "height"), source + ".sz.height", positive=True)
                if abs(_mm(width_hu) - sum(result["column_widths_mm"])) > 1e-9 or abs(_mm(height_hu) - sum(result["row_heights_mm"])) > 1e-9:
                    self.entry(source, None, "loss", "table outer size conflicts with exact cell grid")
            except ValueError as exc:
                self.entry(source, None, "loss", str(exc))
        self._object_frame(table, source, result, need_size=False)
        # The public compiler does not accept raw_hu in the spec. Keep the
        # exact measurements in the report entry and emit only physical mm.
        raw = result.pop("raw_hu", None)
        self.entry(source, target, "converted", json.dumps(raw, sort_keys=True) if raw else "table geometry")
        return result

    @staticmethod
    def _last_anchor(rows: int, cols: int, measurements: list[CellMeasurement]) -> str:
        for cell in reversed(sorted(measurements, key=lambda item: (item.row, item.column))):
            if cell.row <= rows - 1 < cell.row + cell.row_span and cell.column <= cols - 1 < cell.column + cell.column_span:
                return _address(cell.row, cell.column)
        return _address(rows - 1, cols - 1)

    def _border(self, identifier: str | None, output: dict[str, Any], source: str) -> None:
        if self.head is None or identifier is None:
            self.entry(source, None, "loss", "unresolved cell border reference")
            return
        border = next((node for node in self.head.iter() if _tag(node) == "BORDERFILL" and _attr(node, "id") == identifier), None)
        if border is None:
            self.entry(source, None, "loss", f"unresolved cell border {identifier}")
            return
        attrs = _attrs(border)
        for key in set(attrs) - {"ID", "THREED", "SHADOW", "SLASH", "BACKSLASH", "CROOKEDSLASH",
                                 "COUNTERSLASH", "COUNTERBACKSLASH", "BREAKCELLSEPARATELINE", "CENTERLINE"}:
            self.entry(source, None, "loss", f"unsupported border-fill property {key}")
        for key in set(attrs) - {"ID"}:
            if attrs[key].lower() not in {"0", "false", "none"}:
                self.entry(source, None, "loss", f"unsupported border-fill property {key}={attrs[key]}")
        borders: list[dict[str, Any]] = []
        fills: list[ET.Element] = []
        for child in border.iter():
            tag = _tag(child)
            if tag in {"LEFTBORDER", "RIGHTBORDER", "TOPBORDER", "BOTTOMBORDER"}:
                side = tag[:-6].lower()
                line = (_attr(child, "type") or "None").upper()
                extra = set(_attrs(child)) - {"TYPE", "WIDTH", "COLOR"}
                if extra:
                    self.entry(source, None, "loss", f"unsupported {side} border properties {sorted(extra)}")
                if line == "NONE":
                    borders.append({"sides": side, "line_type": "None", "width": "0.12mm", "color": "#000000"})
                elif line == "SOLID":
                    try:
                        width = _line_width(_attr(child, "width"), source + "." + side + ".width")
                        borders.append({"sides": side, "line_type": "Solid", "width": f"{width:g}mm",
                                        "color": _color(_attr(child, "color"), source + "." + side + ".color")})
                    except ValueError as exc:
                        self.entry(source, None, "loss", str(exc))
                else:
                    self.entry(source, None, "loss", f"unsupported {side} border line type {line}")
            elif tag in {"WINDOWBRUSH", "WINBRUSH", "GRADATION", "GRADIENT", "GRADIENTFILL", "IMAGEBRUSH", "IMGBRUSH"}:
                fills.append(child)
            elif tag == "DIAGONAL":
                # HWPX emits a dormant diagonal pen even when both diagonal
                # selectors are NONE. It has no visible effect in that case.
                if any((_attr(item, "type") or "NONE").upper() != "NONE"
                       for item in border.iter() if _tag(item) in {"SLASH", "BACKSLASH"}):
                    self.entry(source, None, "loss", "active cell diagonal is not authored")
            elif tag in {"SLASH", "BACKSLASH"}:
                if (_attr(child, "type") or "NONE").upper() != "NONE":
                    self.entry(source, None, "loss", f"unsupported cell diagonal {tag}")
                for key in set(_attrs(child)) - {"TYPE", "CROOKED", "ISCOUNTER"}:
                    self.entry(source, None, "loss", f"unsupported cell diagonal property {key}")
                if _attr(child, "Crooked") not in {None, "0"} or _attr(child, "isCounter") not in {None, "0"}:
                    self.entry(source, None, "loss", f"non-default cell diagonal {tag}")
        if borders:
            output["borders"] = borders
        if len(fills) > 1:
            self.entry(source, None, "loss", "combined cell fill brushes cannot be represented")
        elif fills:
            fill = self._fill_brush(fills[0], source)
            if fill is not None:
                output["fill"] = fill

    def _fill_brush(self, brush: ET.Element, source: str) -> dict[str, Any] | None:
        tag = _tag(brush)
        if tag in {"WINDOWBRUSH", "WINBRUSH"}:
            attrs = _attrs(brush)
            for key in set(attrs) - {"FACECOLOR", "HATCHCOLOR", "HATCHSTYLE", "ALPHA"}:
                self.entry(source, None, "loss", f"unsupported solid-fill property {key}")
            if attrs.get("HATCHSTYLE", "NONE").upper() != "NONE" or attrs.get("ALPHA", "0") != "0":
                self.entry(source, None, "loss", "hatch or transparent cell fill")
            face = attrs.get("FACECOLOR")
            if face in {None, "4294967295", "#FFFFFFFF", "none"}:
                return None
            try:
                return {"type": "solid", "color": _color(face, source + ".fill")}
            except ValueError as exc:
                self.entry(source, None, "loss", str(exc))
                return None
        if tag not in {"GRADATION", "GRADIENT", "GRADIENTFILL"}:
            self.entry(source, None, "loss", f"unsupported cell fill {tag}")
            return None
        attrs = _attrs(brush)
        for key in set(attrs) - {"TYPE", "ANGLE", "CENTERX", "CENTERY", "STEP", "STEPCENTER", "COLORNUM", "ALPHA"}:
            self.entry(source, None, "loss", f"unsupported gradient property {key}")
        if attrs.get("ALPHA", "0") != "0":
            self.entry(source, None, "loss", "gradient alpha cannot be authored")
        kind = attrs.get("TYPE", "").upper()
        if kind not in {"LINEAR", "RADIAL"}:
            self.entry(source, None, "loss", f"unsupported gradient type {kind or '<absent>'}")
            return None
        colors: list[str] = []
        for index, color in enumerate(brush):
            if _tag(color) != "COLOR" or set(_attrs(color)) - {"VALUE"} or list(color):
                self.entry(source, None, "loss", "gradient color has unsupported stop properties")
                continue
            try:
                colors.append(_color(_attr(color, "value") or color.text, source + f".color[{index}]"))
            except ValueError as exc:
                self.entry(source, None, "loss", str(exc))
        if len(colors) < 2 or len(colors) > 10 or attrs.get("COLORNUM") != str(len(colors)):
            self.entry(source, None, "loss", "gradient color count absent, inconsistent, or outside 2..10")
        try:
            angle = int(attrs["ANGLE"])
            center_x = int(attrs.get("CENTERX", "0"))
            center_y = int(attrs.get("CENTERY", "0"))
            step = int(attrs.get("STEP", "50"))
            step_center = int(attrs.get("STEPCENTER", "50"))
            if not 0 <= angle <= 359 or any(not 0 <= value <= 100 for value in (center_x, center_y, step, step_center)):
                raise ValueError("gradient geometry outside supported range")
        except (KeyError, ValueError) as exc:
            self.entry(source, None, "loss", f"invalid gradient geometry: {exc}")
            return None
        result: dict[str, Any] = {"type": "linear_gradient" if kind == "LINEAR" else "radial_gradient",
                                  "angle": angle, "stops": colors}
        if kind == "LINEAR":
            if (center_x, center_y, step, step_center) != (0, 0, 100, 50):
                self.entry(source, None, "loss", "linear gradient center/step differs from native writer")
        else:
            result.update(center_x=center_x, center_y=center_y, step=step, step_center=step_center)
        return result

    def _drawing(self, node: ET.Element, source: str, target: str) -> dict[str, Any]:
        tag = _tag(node)
        kind = {"RECTANGLE": "rectangle", "RECT": "rectangle", "ELLIPSE": "ellipse", "LINE": "line"}[tag]
        result: dict[str, Any] = {"kind": "shape", "shape_kind": kind, "source": source}
        self._object_frame(node, source, result, need_size=True)
        attrs = _attrs(node)
        frame = _child(node, "SHAPEOBJECT")
        native_size = _child(frame, "SIZE") if frame is not None else _child(node, "SZ")
        raw_size = _attrs(native_size) if native_size is not None else attrs
        width_hu = raw_size.get("WIDTH")
        height_hu = raw_size.get("HEIGHT")
        if self.kind == "hwpml" and width_hu is not None and height_hu is not None:
            try:
                width_int = _hu(width_hu, source + ".width", positive=True)
                height_int = _hu(height_hu, source + ".height", positive=True)
                center = (width_int // 2, height_int // 2)
                if kind == "rectangle":
                    expected_points = {"X0": 0, "Y0": 0, "X1": width_int, "Y1": 0,
                                       "X2": width_int, "Y2": height_int, "X3": 0, "Y3": height_int}
                elif kind == "ellipse":
                    expected_points = {"CENTERX": center[0], "CENTERY": center[1],
                                       "AXIS1X": width_int, "AXIS1Y": center[1],
                                       "AXIS2X": center[0], "AXIS2Y": height_int}
                else:
                    expected_points = {}
                if any(attrs.get(key) != str(value) for key, value in expected_points.items()):
                    self.entry(source, None, "loss", f"{kind} vertices are absent or transformed")
            except ValueError as exc:
                self.entry(source, None, "loss", str(exc))
        if kind == "rectangle" and attrs.get("RATIO", "0") != "0":
            self.entry(source, None, "loss", "rounded rectangle corners are not authored")
        if kind == "ellipse" and (attrs.get("HASARCPROPERTY", attrs.get("HASARCPR", "false")).lower() not in {"0", "false"}
                                  or attrs.get("ARCTYPE", "NORMAL").upper() != "NORMAL"):
            self.entry(source, None, "loss", "ellipse arc or pie geometry is not authored")
        if kind == "line" and self.kind == "hwpml":
            try:
                start = (_hu(attrs.get("STARTX"), source + ".StartX"),
                         _hu(attrs.get("STARTY"), source + ".StartY"))
                end = (_hu(attrs.get("ENDX"), source + ".EndX"),
                       _hu(attrs.get("ENDY"), source + ".EndY"))
                expected = (_hu(str(round(result["width_mm"] * 7200 / 25.4)), source + ".Width"),
                            _hu(str(round(result["height_mm"] * 7200 / 25.4)), source + ".Height"))
                if start != (0, 0) or end != expected or attrs.get("ISREVERSEHV", "false").lower() not in {"0", "false"}:
                    self.entry(source, None, "loss", "line endpoints cannot be represented by native diagonal primitive")
            except (KeyError, ValueError) as exc:
                self.entry(source, None, "loss", f"invalid line geometry: {exc}")
        allowed = {"ID", "TREATASCHAR", "WIDTH", "HEIGHT", "RATIO"} if kind == "rectangle" else {"ID", "TREATASCHAR", "WIDTH", "HEIGHT"}
        if kind == "line":
            allowed |= {"STARTX", "STARTY", "ENDX", "ENDY", "ISREVERSEHV"}
        if kind == "ellipse":
            allowed |= {"HASARCPROPERTY", "HASARCPR", "ARCTYPE", "INTERVALDIRTY"}
            if attrs.get("HASARCPR", "0").lower() not in {"0", "false"} or attrs.get("INTERVALDIRTY", "0").lower() not in {"0", "false"}:
                self.entry(source, None, "loss", "ellipse arc or dirty interval not authored")
        if self.kind == "hwpx":
            allowed |= {"ZORDER", "NUMBERINGTYPE", "LOCK", "DROPCAPSTYLE", "HREF", "GROUPLEVEL", "INSTID", "TEXTWRAP", "TEXTFLOW"}
            for key, valid in {"ZORDER": {"0"}, "NUMBERINGTYPE": {"NONE"}, "LOCK": {"0", "FALSE"},
                               "DROPCAPSTYLE": {"NONE"}, "HREF": {""}, "GROUPLEVEL": {"0"},
                               "TEXTFLOW": {"BOTHSIDES"}}.items():
                if key in attrs and attrs[key].upper() not in valid:
                    self.entry(source, None, "loss", f"unsupported drawing property {key}={attrs[key]}")
            required = {"OFFSET", "ORGSZ", "CURSZ", "FLIP", "ROTATIONINFO", "RENDERINGINFO",
                        "LINESHAPE", "SZ", "POS"}
            required |= ({"PT0", "PT1", "PT2", "PT3"} if kind == "rectangle" else
                         {"STARTPT", "ENDPT"} if kind == "line" else
                         {"CENTER", "AX1", "AX2", "START1", "END1", "START2", "END2"})
            absent = required - {_tag(item) for item in node}
            if absent:
                self.entry(source, None, "loss", f"HWPX drawing has missing structural facts: {sorted(absent)}")
        if kind == "rectangle" and self.kind == "hwpml":
            allowed |= {f"{axis}{index}" for axis in ("X", "Y") for index in range(4)}
        if kind == "ellipse" and self.kind == "hwpml":
            allowed |= {"CENTERX", "CENTERY", "AXIS1X", "AXIS1Y", "AXIS2X", "AXIS2Y"}
        for key in set(attrs) - allowed:
            self.entry(source, None, "loss", f"unsupported drawing geometry {key}")
        drawing = _child(node, "DRAWINGOBJECT")
        if drawing is None:
            if self.kind == "hwpx":
                drawing = node
            else:
                self.entry(source, None, "loss", "drawing properties absent")
                self.entry(source, target, "converted", "native editable drawing primitive")
                return result
        if drawing is not node and _attrs(drawing):
            self.entry(source, None, "loss", "unsupported drawing-object attributes")
        line = _child(drawing, "LINESHAPE")
        if line is None:
            self.entry(source, None, "loss", "drawing line style absent")
        else:
            lattrs = _attrs(line)
            for key in set(lattrs) - {"STYLE", "WIDTH", "COLOR", "ENDCAP", "HEADSTYLE", "TAILSTYLE",
                                      "HEADSIZE", "TAILSIZE", "HEADSZ", "TAILSZ", "HEADFILL", "TAILFILL",
                                      "OUTLINESTYLE", "ALPHA"}:
                self.entry(source, None, "loss", f"unsupported drawing line property {key}")
            for key, default in {"ENDCAP": "FLAT", "HEADSTYLE": "NORMAL", "TAILSTYLE": "NORMAL",
                                 "HEADSIZE": "SMALLSMALL", "TAILSIZE": "SMALLSMALL", "HEADSZ": "SMALL_SMALL",
                                 "TAILSZ": "SMALL_SMALL", "HEADFILL": "1", "TAILFILL": "1",
                                 "OUTLINESTYLE": "NORMAL", "ALPHA": "0"}.items():
                if key in lattrs and lattrs[key].upper() != default:
                    self.entry(source, None, "loss", f"unsupported drawing line {key}={lattrs[key]}")
            style = lattrs.get("STYLE", "").upper()
            if style == "NONE":
                result["line"] = {"type": "none"}
            elif style == "SOLID":
                try:
                    result["line"] = {"type": "solid", "color": _color(lattrs.get("COLOR"), source + ".line.color"),
                                      "width_mm": _line_width(lattrs.get("WIDTH"), source + ".line.width")}
                except ValueError as exc:
                    self.entry(source, None, "loss", str(exc))
            else:
                self.entry(source, None, "loss", f"unsupported drawing line style {style or '<absent>'}")
        fill = _child(drawing, "FILLBRUSH")
        if fill is not None:
            if _attrs(fill) or len(fill) != 1:
                self.entry(source, None, "loss", "drawing fill brush is not a single simple fill")
            elif parsed := self._fill_brush(fill[0], source):
                result["fill"] = parsed
        draw_text = _child(drawing, "DRAWTEXT")
        if draw_text is not None:
            result["kind"] = "text_box"
            result.pop("shape_kind", None)
            tattrs = _attrs(draw_text)
            for key in set(tattrs) - {"LASTWIDTH", "NAME", "EDITABLE"}:
                self.entry(source, None, "loss", f"unsupported draw-text property {key}")
            if tattrs.get("EDITABLE", "true").lower() not in {"1", "true"}:
                self.entry(source, None, "loss", "non-editable draw text cannot become editable text box")
            if "NAME" in tattrs:
                if tattrs["NAME"]:
                    self.entry(source, None, "loss", "named drawing object cannot retain name")
            if "LASTWIDTH" in tattrs:
                raw_width = _attr(_child(node, "SHAPEOBJECT"), "width") if _child(node, "SHAPEOBJECT") is not None else None
                size_node = _child(_child(node, "SHAPEOBJECT"), "SIZE") if _child(node, "SHAPEOBJECT") is not None else _child(node, "SZ")
                if size_node is not None:
                    raw_width = _attr(size_node, "width")
                if tattrs["LASTWIDTH"] not in {raw_width, "4294967295"}:
                    self.entry(source, None, "loss", "draw-text lastWidth differs from object width")
            margin = _child(draw_text, "TEXTMARGIN")
            if margin is not None:
                try:
                    result["margin"] = [_mm(_hu(_attr(margin, side), source + ".textMargin." + side))
                                        for side in ("Left", "Right", "Top", "Bottom")]
                except ValueError as exc:
                    self.entry(source, None, "loss", str(exc))
            paras = _child(draw_text, "PARALIST")
            if paras is None:
                paras = _child(draw_text, "SUBLIST")
            if paras is None:
                self.entry(source, None, "loss", "draw text paragraph list absent")
            else:
                sub_defaults = {"ID": "", "TEXTDIRECTION": "HORIZONTAL", "LINEWRAP": "BREAK",
                                "LINKLISTIDREF": "0", "LINKLISTNEXTIDREF": "0", "TEXTWIDTH": "0",
                                "TEXTHEIGHT": "0", "HASTEXTREF": "0", "HASNUMREF": "0"}
                for key in set(_attrs(paras)) - {"VERTALIGN"} - set(sub_defaults):
                    self.entry(source, None, "loss", f"unsupported draw-text list property {key}")
                if _attr(paras, "vertAlign") is not None:
                    self.entry(source, None, "loss", "draw-text vertical alignment is not authored")
                for key, default in sub_defaults.items():
                    if _attr(paras, key) not in {None, default}:
                        self.entry(source, None, "loss", f"unsupported draw-text list property {key}={_attr(paras, key)}")
                content = self._content(paras, source + "/DRAWTEXT/PARALIST", target + ".paragraphs", depth=1)
                if any(item.get("kind") != "paragraph" or "content" in item for item in content):
                    self.entry(source, None, "loss", "nested objects inside draw text are not authored")
                else:
                    result["paragraphs"] = [{key: value for key, value in item.items() if key not in {"kind", "source"}}
                                            for item in content]
            for child in draw_text:
                if _tag(child) not in {"TEXTMARGIN", "PARALIST"}:
                    self.entry(source, None, "loss", f"unsupported draw text child {_tag(child)}")
        for child in drawing:
            tag_child = _tag(child)
            if tag_child == "SHAPECOMPONENT":
                component = _attrs(child)
                default = {"XPOS": "0", "YPOS": "0", "GROUPLEVEL": "0", "HORZFLIP": "false", "VERTFLIP": "false"}
                for key in set(component) - {"HREF", "XPOS", "YPOS", "GROUPLEVEL", "ORIWIDTH", "ORIHEIGHT",
                                             "CURWIDTH", "CURHEIGHT", "HORZFLIP", "VERTFLIP", "INSTID"}:
                    self.entry(source, None, "loss", f"unsupported shape component {key}")
                for key, value in default.items():
                    if key in component and component[key].lower() != value:
                        self.entry(source, None, "loss", f"transformed shape component {key}={component[key]}")
                if list(child):
                    self.entry(source, None, "loss", "shape rotation/rendering transform not authored")
            elif drawing is node and tag_child in {"OFFSET", "ORGSZ", "CURSZ", "FLIP", "ROTATIONINFO",
                                                   "RENDERINGINFO", "SZ", "POS", "OUTMARGIN", "SHAPECOMMENT",
                                                   "PT0", "PT1", "PT2", "PT3", "CENTER", "AX1", "AX2",
                                                   "START1", "END1", "START2", "END2", "STARTPT", "ENDPT", "SHADOW"}:
                self._hwpx_drawing_fact(child, node, source, result)
            elif tag_child not in {"LINESHAPE", "FILLBRUSH", "DRAWTEXT"}:
                self.entry(source, None, "loss", f"unsupported drawing property {tag_child}")
        if drawing is not node:
            for child in node:
                if _tag(child) not in {"SHAPEOBJECT", "DRAWINGOBJECT"}:
                    self.entry(source, None, "loss", f"unsupported drawing child {_tag(child)}")
        self.entry(source, target, "converted", "native editable drawing primitive")
        return result

    def _hwpx_drawing_fact(self, child: ET.Element, node: ET.Element,
                           source: str, result: dict[str, Any]) -> None:
        tag = _tag(child)
        attrs = _attrs(child)
        native_size = _attrs(_child(node, "SZ")) if _child(node, "SZ") is not None else {}
        width, height = native_size.get("WIDTH"), native_size.get("HEIGHT")
        expected: dict[str, str] | None = None
        if tag == "OFFSET":
            expected = {"X": "0", "Y": "0"}
        elif tag in {"ORGSZ", "CURSZ"}:
            expected = {"WIDTH": width or "", "HEIGHT": height or ""}
        elif tag == "FLIP":
            expected = {"HORIZONTAL": "0", "VERTICAL": "0"}
        elif tag == "ROTATIONINFO":
            expected = {"ANGLE": "0", "CENTERX": str(int(width) // 2) if width else "",
                        "CENTERY": str(int(height) // 2) if height else "", "ROTATEIMAGE": "1"}
        elif tag == "RENDERINGINFO":
            identity = {"E1": "1", "E2": "0", "E3": "0", "E4": "0", "E5": "1", "E6": "0"}
            if attrs or len(child) != 3 or {_tag(item) for item in child} != {"TRANSMATRIX", "SCAMATRIX", "ROTMATRIX"}:
                self.entry(source, None, "loss", "non-identity or incomplete drawing rendering transform")
            for item in child:
                if _attrs(item) != identity or list(item):
                    self.entry(source, None, "loss", "non-identity drawing matrix")
            return
        elif tag == "SHAPECOMMENT":
            if attrs or (child.text or "").strip() or list(child):
                self.entry(source, None, "loss", "drawing comment is not authored")
            return
        elif tag == "SHADOW":
            for key in set(attrs) - {"TYPE", "COLOR", "OFFSETX", "OFFSETY", "ALPHA"}:
                self.entry(source, None, "loss", f"unsupported drawing shadow {key}")
            if attrs.get("TYPE", "NONE").upper() != "NONE" or any(attrs.get(key, "0") != "0" for key in ("OFFSETX", "OFFSETY", "ALPHA")):
                self.entry(source, None, "loss", "drawing shadow differs from no-shadow primitive")
            return
        elif tag in {"SZ", "POS", "OUTMARGIN"}:
            return
        elif tag in {"PT0", "PT1", "PT2", "PT3", "STARTPT", "ENDPT"}:
            points = {"PT0": ("0", "0"), "PT1": (width, "0"), "PT2": (width, height),
                      "PT3": ("0", height), "STARTPT": ("0", "0"), "ENDPT": (width, height)}
            x, y = points[tag]
            expected = {"X": x or "", "Y": y or ""}
        elif tag in {"CENTER", "AX1", "AX2", "START1", "END1", "START2", "END2"}:
            if width is None or height is None:
                self.entry(source, None, "loss", "ellipse geometry lacks absolute size")
                return
            center = (str(int(width) // 2), str(int(height) // 2))
            first = (width, center[1])
            second = (center[0], height)
            coords = {"CENTER": center, "AX1": first, "AX2": second,
                      "START1": first, "END1": first, "START2": first, "END2": first}[tag]
            expected = {"X": coords[0], "Y": coords[1]}
        if expected is not None and attrs != expected:
            self.entry(source, None, "loss", f"{tag} geometry differs from native primitive: {attrs}")

    def _picture(self, node: ET.Element, source: str, target: str) -> dict[str, Any]:
        image = _descendant(node, "IMAGE")
        if image is None:
            image = _descendant(node, "IMG")
        ref = _attr(image, "BinItem") if image is not None else None
        if ref is None and image is not None:
            ref = _attr(image, "binaryItemIDRef")
        if ref is None:
            self.entry(source, None, "loss", "picture asset reference absent")
            return {"kind": "picture", "asset": "unresolved", "source": source}
        if image is not None:
            image_defaults = {"BRIGHT": "0", "CONTRAST": "0", "EFFECT": "REAL_PIC", "ALPHA": "0"}
            for key in set(_attrs(image)) - {"BINITEM", "BINARYITEMIDREF"} - set(image_defaults):
                self.entry(source, None, "loss", f"unsupported image property {key}")
            for key, default in image_defaults.items():
                if _attr(image, key) not in {None, default}:
                    self.entry(source, None, "loss", f"unsupported image effect {key}={_attr(image, key)}")
            if list(image):
                self.entry(source, None, "loss", "image effects or crop require explicit mapping")
        asset = self.available.get(ref)
        if asset is None:
            self.entry(source, None, "loss", f"picture asset {ref} missing or not embedded")
            return {"kind": "picture", "asset": "unresolved", "source": source}
        if Path(asset.name).suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".wmf", ".emf"}:
            self.entry(source, None, "loss", f"picture asset {ref} is not a supported image part")
        key = f"bin-{ref}" if ref.isdigit() else "asset-" + hashlib.sha256(ref.encode()).hexdigest()[:12]
        if key not in self.assets:
            relative = f"assets/{key}{Path(asset.name).suffix.lower()}"
            self.assets[key] = {"path": relative, "sha256": asset.sha256}
            self.used_assets[key] = asset
        result = {"kind": "picture", "asset": key, "size_option": 1, "source": source}
        self._object_frame(node, source, result, need_size=True)
        if self.kind == "hwpx":
            required = {"OFFSET", "ORGSZ", "CURSZ", "FLIP", "ROTATIONINFO", "RENDERINGINFO",
                        "IMGRECT", "IMGCLIP", "INMARGIN", "IMGDIM", "IMG", "EFFECTS", "SZ", "POS", "OUTMARGIN"}
            absent = required - {_tag(child) for child in node}
            if absent:
                self.entry(source, None, "loss", f"HWPX picture has missing structural facts: {sorted(absent)}")
        allowed_root = {"WIDTH", "HEIGHT", "TREATASCHAR", "ID"}
        if self.kind == "hwpx":
            allowed_root |= {"ZORDER", "NUMBERINGTYPE", "TEXTWRAP", "TEXTFLOW", "LOCK",
                             "DROPCAPSTYLE", "HREF", "GROUPLEVEL", "INSTID", "REVERSE"}
            for key, default in {"ZORDER": "0", "NUMBERINGTYPE": "PICTURE", "TEXTFLOW": "BOTH_SIDES",
                                 "LOCK": "0", "DROPCAPSTYLE": "NONE", "HREF": "", "GROUPLEVEL": "0",
                                 "REVERSE": "0"}.items():
                if _attr(node, key) is not None and _attr(node, key).upper() != default:
                    self.entry(source, None, "loss", f"unsupported picture property {key}={_attr(node, key)}")
        for key_attr in set(_attrs(node)) - allowed_root:
            self.entry(source, None, "loss", f"unsupported picture property {key_attr}")
        for child in node:
            tag = _tag(child)
            if self.kind == "hwpx" and tag in {"OFFSET", "ORGSZ", "CURSZ", "FLIP", "ROTATIONINFO",
                                               "RENDERINGINFO", "SZ", "POS", "OUTMARGIN", "SHAPECOMMENT"}:
                self._hwpx_drawing_fact(child, node, source, result)
            elif self.kind == "hwpx" and tag in {"IMGRECT", "IMGCLIP", "INMARGIN", "IMGDIM", "EFFECTS"}:
                self._hwpx_picture_fact(child, node, source)
            elif tag not in {"SHAPEOBJECT", "IMAGE", "IMG"}:
                self.entry(source + "/" + _tag(child), None, "loss", "picture effect or crop is not authored")
        self.entry(source, target, "converted", "embedded asset with native dimensions")
        return result

    def _hwpx_picture_fact(self, child: ET.Element, node: ET.Element, source: str) -> None:
        tag = _tag(child)
        size = _child(node, "SZ")
        width = _attr(size, "width") if size is not None else None
        height = _attr(size, "height") if size is not None else None
        if tag == "IMGRECT":
            names = [_tag(item) for item in child]
            if _attrs(child) or names != ["PT0", "PT1", "PT2", "PT3"]:
                self.entry(source, None, "loss", "picture frame geometry is incomplete")
            for item in child:
                self._hwpx_drawing_fact(item, node, source, {})
        elif tag == "IMGCLIP":
            if _attrs(child) != {"LEFT": "0", "RIGHT": width, "TOP": "0", "BOTTOM": height}:
                self.entry(source, None, "loss", "cropped picture cannot be reproduced by image insertion")
        elif tag == "INMARGIN":
            if _attrs(child) != {"LEFT": "0", "RIGHT": "0", "TOP": "0", "BOTTOM": "0"}:
                self.entry(source, None, "loss", "picture inner margin is not authored")
        elif tag == "IMGDIM":
            if _attrs(child) != {"DIMWIDTH": width, "DIMHEIGHT": height}:
                self.entry(source, None, "loss", "picture original dimensions differ from frame")
        elif tag == "EFFECTS":
            if _attrs(child) or list(child):
                self.entry(source, None, "loss", "picture visual effects are not authored")

    def _chart(self, node: ET.Element, source: str) -> None:
        if self.kind == "hwpml":
            self.entry(source, None, "loss", "HWPML 3.0 has no CHART element; chart relationship cannot be inferred")
            return
        reference = _attr(node, "chartIDRef")
        if not reference:
            self.entry(source, None, "loss", "HWPX chartIDRef is absent")
            return
        part = self.available.get(reference)
        if part is None:
            self.entry(source, None, "loss", f"HWPX chart part {reference!r} is missing")
            return
        try:
            root = _xml(part.data, part.name)
        except UsageError as exc:
            self.entry(source, None, "loss", f"HWPX chart part invalid: {exc}")
            return
        if _tag(root) != "CHARTSPACE":
            self.entry(source, None, "loss", f"HWPX chart part {reference!r} is not ChartML chartSpace")
            return
        chart_types = sorted({_tag(item) for item in root.iter() if _tag(item) in
                              {"BARCHART", "LINECHART", "PIECHART", "AREACHART", "SCATTERCHART"}})
        series = sum(1 for item in root.iter() if _tag(item) == "SER")
        self.entry(source, None, "loss", f"HWPX ChartML {reference!r} has type={chart_types}, series={series}; "
                   "chartIDRef does not encode a source table/range, and table-driven insert_chart "
                   "cannot preserve the ChartML series, axes, styling, and placement")

    def _page_hide(self, node: ET.Element, source: str, target: str) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": "page_hiding", "source": source}
        mapping = {"PAGENUM": "hide_page_num", "HEADER": "hide_header", "FOOTER": "hide_footer", "BORDER": "hide_border", "FILL": "hide_fill"}
        for key, raw in _attrs(node).items():
            if key not in mapping:
                self.entry(source, None, "loss", f"unsupported page hide property {key}")
                continue
            try:
                result[mapping[key]] = _boolean(raw, source + "." + key)
            except ValueError as exc:
                self.entry(source, None, "loss", str(exc))
        self.entry(source, target, "converted")
        return result

    def _new_number(self, node: ET.Element, source: str, target: str) -> dict[str, Any]:
        attrs = _attrs(node)
        if attrs.get("TYPE", "PAGE").upper() != "PAGE":
            self.entry(source, None, "loss", "non-page numbering restart")
        try:
            number = int(attrs.get("NUMBER", attrs.get("NUM", "1")))
        except ValueError:
            number = 1
            self.entry(source, None, "loss", "invalid page restart number")
        for key in set(attrs) - {"TYPE", "NUMBER", "NUM"}:
            self.entry(source, None, "loss", f"unsupported numbering property {key}")
        self.entry(source, target, "converted")
        return {"kind": "new_number", "number": number, "source": source}

    def convert(self) -> dict[str, Any]:
        sections: list[dict[str, Any]] = []
        for index, section in enumerate(self.roots):
            source = f"{self.kind}:section[{index}]"
            target = f"sections[{index}]"
            controls = self._section_controls(section, source, target + ".content")
            sections.append({"page": self._page(section, source),
                             "content": controls + self._content(section, source, target + ".content",
                                                                 depth=0, start_index=len(controls))})
            self.entry(source, target, "preserved", "section order")
        return {"schema": SCHEMA, "reference": {"source_sha256": self.source_sha256},
                "assets": self.assets, "sections": sections}


def _bundle(path: Path) -> tuple[str, list[ET.Element], ET.Element | None, dict[str, _Asset], str]:
    manifest_file = path / "manifest.json"
    if not manifest_file.is_file():
        raise UsageError("capture bundle requires manifest.json")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UsageError(f"Invalid capture manifest: {exc}") from exc
    if not isinstance(manifest, dict) or not manifest.get("source_unchanged"):
        raise UsageError("capture bundle does not prove source integrity")
    xml_name = _safe_relative(str(manifest.get("hwpml", "")), "manifest.hwpml")
    xml_file = (path / xml_name).resolve()
    if not xml_file.is_relative_to(path.resolve()) or not xml_file.is_file():
        raise UsageError("manifest HWPML is missing or outside bundle")
    data = xml_file.read_bytes()
    root = _xml(data, xml_name)
    available: dict[str, _Asset] = {}
    for item in manifest.get("assets", []):
        if not isinstance(item, dict):
            raise UsageError("manifest asset must be an object")
        number = item.get("bin_item")
        if type(number) is not int or number < 1:
            raise UsageError("manifest asset bin_item is invalid")
        if not item.get("extracted"):
            continue
        relative = _safe_relative(str(item.get("path", "")), "manifest asset")
        asset_file = (path / relative).resolve()
        if not asset_file.is_relative_to(path.resolve()) or not asset_file.is_file() or asset_file.stat().st_size > _MAX_ASSET:
            raise UsageError("bundle asset missing, oversized, or outside bundle")
        payload = asset_file.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if not isinstance(item.get("sha256"), str) or digest != item["sha256"].lower():
            raise UsageError("bundle asset SHA-256 mismatch")
        available[str(number)] = _Asset(asset_file.name, payload, digest)
    sections = [section for body in root.iter() if _tag(body) == "BODY" for section in body if _tag(section) == "SECTION"]
    return "hwpml", sections, _descendant(root, "HEAD"), available, hashlib.sha256(data).hexdigest()


def _hwpml(path: Path) -> tuple[str, list[ET.Element], ET.Element | None, dict[str, _Asset], str]:
    data = path.read_bytes()
    root = _xml(data, path.name)
    if _tag(root) != "HWPML":
        raise UsageError("Expected HWPML root")
    sections = [section for body in root.iter() if _tag(body) == "BODY" for section in body if _tag(section) == "SECTION"]
    return "hwpml", sections, _descendant(root, "HEAD"), {}, hashlib.sha256(data).hexdigest()


def _hwpx(path: Path) -> tuple[str, list[ET.Element], ET.Element | None, dict[str, _Asset], str]:
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.infolist()
            if sum(item.file_size for item in info) > _MAX_ZIP_TOTAL or any(item.file_size > _MAX_ASSET for item in info):
                raise UsageError("HWPX package exceeds safety limits")
            names = {item.filename for item in info}
            if "Contents/content.hpf" not in names or "Contents/header.xml" not in names:
                raise UsageError("HWPX package lacks manifest or header")
            manifest = _xml(archive.read("Contents/content.hpf"), "Contents/content.hpf")
            items = {_attr(item, "id"): _safe_relative(_attr(item, "href") or "", "manifest href")
                     for item in manifest.iter() if _tag(item) == "ITEM"}
            section_names: list[str] = []
            for ref in manifest.iter():
                if _tag(ref) == "ITEMREF":
                    item_id = _attr(ref, "idref")
                    if item_id and item_id.lower().startswith("section"):
                        part = items.get(item_id)
                        if part is None or part not in names:
                            raise UsageError(f"Missing HWPX section {item_id}")
                        section_names.append(part)
            if not section_names:
                raise UsageError("HWPX package has no ordered sections")
            sections = [_xml(archive.read(name), name) for name in section_names]
            head = _xml(archive.read("Contents/header.xml"), "Contents/header.xml")
            available: dict[str, _Asset] = {}
            for item_id, name in items.items():
                if not item_id or name not in names or not name.lower().startswith(("bindata/", "chart/")):
                    continue
                payload = archive.read(name)
                asset = _Asset(PurePosixPath(name).name, payload, hashlib.sha256(payload).hexdigest())
                available[item_id] = asset
                if name.lower().startswith("chart/"):
                    available[name] = asset
            return "hwpx", sections, head, available, hashlib.sha256(path.read_bytes()).hexdigest()
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise UsageError(f"Invalid HWPX package: {exc}") from exc


def reference_to_spec(input: str | Path, output_dir: str | Path, dry_run: bool = False) -> dict[str, Any]:
    """Convert supported source facts; publish only a fully validated v2 spec.

    ``dry_run`` reads and reports but creates no files or directories. A loss
    returns ``ok=False`` and ``spec=None``. Actual success creates a fresh
    directory with ``spec.json``, ``report.json`` and referenced assets.
    """
    source = Path(input).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    if not source.exists():
        raise UsageError("Reference input does not exist")
    if output.exists():
        raise UsageError("Reference conversion output must be a new directory")
    if source == output or (source.is_dir() and output.is_relative_to(source)):
        raise UsageError("Conversion output cannot be inside the reference bundle")
    if source.is_dir():
        kind, sections, head, available, digest = _bundle(source)
    elif source.suffix.lower() == ".hwpml":
        kind, sections, head, available, digest = _hwpml(source)
    elif source.suffix.lower() == ".hwpx":
        kind, sections, head, available, digest = _hwpx(source)
    else:
        raise UsageError("Reference input must be HWPML, HWPX, or a capture bundle")
    if not sections:
        raise UsageError("Reference contains no sections")
    converter = _Converter(kind, digest, sections, head, available)
    candidate = converter.convert()
    if not converter.losses:
        try:
            # This also checks recursive nodes and public command coverage.
            parse_spec(candidate, base_dir=source.parent)
        except (UsageError, ValueError) as exc:
            converter.entry("spec", None, "loss", f"authoring preflight failed: {exc}")
    report = {"schema": "hwpctl.reference-conversion/1", "format": kind,
              "source_sha256": digest, "status": "blocked" if converter.losses else "ready",
              "executable": not converter.losses, "entries": converter.entries,
              "losses": converter.losses,
              "asset_count": len(converter.used_assets), "section_count": len(sections)}
    if converter.losses:
        return {"ok": False, "dry_run": bool(dry_run), "format": kind,
                "executable": False, "spec": None, "report": report, "output_dir": None}
    if dry_run:
        return {"ok": True, "dry_run": True, "format": kind,
                "executable": True, "spec": candidate, "report": report, "output_dir": None}
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        output.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise UsageError("Conversion destination appeared during publication") from exc
    marker = output / ".incomplete"
    try:
        marker.write_text("Conversion is incomplete; no executable spec is published.\n", encoding="utf-8")
        if converter.used_assets:
            (output / "assets").mkdir()
        for key, asset in converter.used_assets.items():
            relative = candidate["assets"][key]["path"]
            with (output / relative).open("xb") as stream:
                stream.write(asset.data)
        with (output / "spec.json").open("x", encoding="utf-8") as stream:
            json.dump(candidate, stream, ensure_ascii=False, indent=2)
        with (output / "report.json").open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
        marker.unlink()
    except Exception:
        # Keep the owned directory and marker as evidence of partial output.
        raise
    return {"ok": True, "dry_run": False, "format": kind, "executable": True,
            "spec": str(output / "spec.json"), "report": report,
            "report_path": str(output / "report.json"), "output_dir": str(output)}


__all__ = ["reference_to_spec"]
