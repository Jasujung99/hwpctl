"""``.hwpx`` 문단·런·셀 서식 그룹. 쓰기 전에 상속할 ID 를 모은다.

ZIP + OWPML 을 표준 라이브러리로 읽는다. 한/글과 ``python-hwpx`` 가
없어도 동작한다. 라이브러리가 있으면 버전만 함께 표시한다.
"""

from __future__ import annotations

import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import BadZipFile

from hwpctl.errors import HwpxError, UsageError
from hwpctl.hwpx.document import hwpx_version

# HWPUNIT 100 = 1pt (한컴 문서 관행, python-hwpx charPr height 와 동일).
HWPUNIT_PER_PT = 100
SAMPLE_LIMIT = 40


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    if ":" in tag:
        return tag.split(":", 1)[-1]
    return tag


def _attr(elem: ET.Element, *names: str) -> str:
    attrib = elem.attrib
    for name in names:
        if name in attrib:
            return attrib[name]
        for key, value in attrib.items():
            if _local(key) == name:
                return value
    return ""


def _children(elem: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in elem if _local(child.tag) == name]


def _first_child(elem: ET.Element, name: str) -> ET.Element | None:
    found = _children(elem, name)
    return found[0] if found else None


def _walk(elem: ET.Element, name: str) -> list[ET.Element]:
    return [node for node in elem.iter() if _local(node.tag) == name]


def _text_of(elem: ET.Element) -> str:
    parts: list[str] = []
    for node in _walk(elem, "t"):
        if node.text:
            parts.append(node.text)
        if node.tail:
            parts.append(node.tail)
    return "".join(parts)


def _sample(text: str) -> str:
    raw = " ".join(text.split())
    if len(raw) <= SAMPLE_LIMIT:
        return raw
    return raw[:SAMPLE_LIMIT] + "…"


def _height_to_pt(raw: str) -> float | None:
    if not raw:
        return None
    try:
        return int(raw) / HWPUNIT_PER_PT
    except ValueError:
        return None


def _parse_fonts(header: ET.Element) -> dict[str, str]:
    """HANGUL fontface 의 id → 글꼴 이름."""

    fonts: dict[str, str] = {}
    for face in _walk(header, "fontface"):
        lang = _attr(face, "lang").upper()
        if lang and lang != "HANGUL":
            continue
        for font in _children(face, "font"):
            font_id = _attr(font, "id")
            name = _attr(font, "face")
            if font_id and name:
                fonts[font_id] = name
        if fonts:
            break
    if not fonts:
        for font in _walk(header, "font"):
            font_id = _attr(font, "id")
            name = _attr(font, "face")
            if font_id and name and font_id not in fonts:
                fonts[font_id] = name
    return fonts


def _parse_para_pr(header: ET.Element) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for node in _walk(header, "paraPr"):
        pr_id = _attr(node, "id")
        if not pr_id:
            continue
        align = _first_child(node, "align")
        line = _first_child(node, "lineSpacing")
        out[pr_id] = {
            "id": pr_id,
            "align": _attr(align, "horizontal") if align is not None else "",
            "valign": _attr(align, "vertical") if align is not None else "",
            "line_spacing_type": _attr(line, "type") if line is not None else "",
            "line_spacing_value": _attr(line, "value") if line is not None else "",
        }
    return out


def _parse_char_pr(header: ET.Element, fonts: dict[str, str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for node in _walk(header, "charPr"):
        pr_id = _attr(node, "id")
        if not pr_id:
            continue
        font_ref = _first_child(node, "fontRef")
        font_id = _attr(font_ref, "hangul") if font_ref is not None else ""
        bold = _first_child(node, "bold") is not None
        italic = _first_child(node, "italic") is not None
        underline_el = _first_child(node, "underline")
        underline = False
        underline_color = ""
        if underline_el is not None:
            utype = (_attr(underline_el, "type") or "").upper()
            underline = utype != "NONE"
            underline_color = _attr(underline_el, "color") or ""
        out[pr_id] = {
            "id": pr_id,
            "font": fonts.get(font_id, ""),
            "font_id": font_id,
            "size_pt": _height_to_pt(_attr(node, "height")),
            "bold": bold,
            "italic": italic,
            "underline": underline,
            "underline_color": underline_color,
            "color": _attr(node, "textColor") or "",
        }
    return out


def _parse_border_fills(header: ET.Element) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for node in _walk(header, "borderFill"):
        fill_id = _attr(node, "id")
        if not fill_id:
            continue
        fill = ""
        brush = _first_child(node, "fillBrush")
        if brush is not None:
            win = _first_child(brush, "winBrush")
            if win is not None:
                fill = _attr(win, "faceColor")
        out[fill_id] = {"id": fill_id, "fill": fill}
    return out


def inspect_owpml_parts(header_xml: str, section_xmls: list[str]) -> dict[str, Any]:
    """header.xml + section*.xml 문자열에서 서식 그룹을 만든다."""

    if not header_xml.strip():
        raise HwpxError("HWPX header.xml 이 비어 있습니다.")
    try:
        header = ET.fromstring(header_xml)
    except ET.ParseError as exc:
        raise HwpxError(f"HWPX header.xml 을 해석할 수 없습니다: {exc}") from exc

    fonts = _parse_fonts(header)
    para_defs = _parse_para_pr(header)
    char_defs = _parse_char_pr(header, fonts)
    fill_defs = _parse_border_fills(header)

    para_keys: list[tuple[str, str, str]] = []
    run_keys: list[str] = []
    cell_keys: list[str] = []
    para_samples: dict[tuple[str, str, str], str] = {}
    run_samples: dict[str, str] = {}
    paragraph_count = 0
    table_count = 0

    for raw in section_xmls:
        if not raw.strip():
            continue
        try:
            section = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise HwpxError(f"HWPX section XML 을 해석할 수 없습니다: {exc}") from exc
        table_count += len(_walk(section, "tbl"))
        for para in _walk(section, "p"):
            paragraph_count += 1
            para_pr = _attr(para, "paraPrIDRef")
            style_id = _attr(para, "styleIDRef")
            align = (para_defs.get(para_pr) or {}).get("align") or ""
            key = (para_pr, style_id, str(align))
            para_keys.append(key)
            sample = _sample(_text_of(para))
            if key not in para_samples or (sample and not para_samples[key]):
                para_samples[key] = sample
            for run in _children(para, "run"):
                char_pr = _attr(run, "charPrIDRef")
                run_keys.append(char_pr)
                run_sample = _sample(_text_of(run))
                if char_pr not in run_samples or (run_sample and not run_samples[char_pr]):
                    run_samples[char_pr] = run_sample
        for cell in _walk(section, "tc"):
            cell_keys.append(_attr(cell, "borderFillIDRef"))

    para_groups = []
    for (para_pr, style_id, align), count in Counter(para_keys).items():
        para_groups.append(
            {
                "para_pr_id": para_pr,
                "style_id": style_id,
                "align": align,
                "count": count,
                "sample_text": para_samples.get((para_pr, style_id, align), ""),
            }
        )
    para_groups.sort(key=lambda item: (-int(item["count"]), str(item["para_pr_id"])))

    run_groups = []
    for char_pr, count in Counter(run_keys).items():
        definition = char_defs.get(char_pr) or {}
        run_groups.append(
            {
                "char_pr_id": char_pr,
                "font": definition.get("font") or "",
                "size_pt": definition.get("size_pt"),
                "bold": bool(definition.get("bold")),
                "italic": bool(definition.get("italic")),
                "underline": bool(definition.get("underline")),
                "underline_color": definition.get("underline_color") or "",
                "color": definition.get("color") or "",
                "count": count,
                "sample_text": run_samples.get(char_pr, ""),
            }
        )
    run_groups.sort(key=lambda item: (-int(item["count"]), str(item["char_pr_id"])))

    cell_groups = []
    for fill_id, count in Counter(cell_keys).items():
        definition = fill_defs.get(fill_id) or {}
        cell_groups.append(
            {
                "border_fill_id": fill_id,
                "fill": definition.get("fill") or "",
                "count": count,
            }
        )
    cell_groups.sort(key=lambda item: (-int(item["count"]), str(item["border_fill_id"])))

    return {
        "paragraph_count": paragraph_count,
        "table_count": table_count,
        "paragraph_groups": para_groups,
        "run_groups": run_groups,
        "cell_fill_groups": cell_groups,
        "definitions": {
            "fonts": fonts,
            "paragraph_properties": para_defs,
            "char_properties": char_defs,
            "border_fills": fill_defs,
        },
    }


def _read_hwpx_xml(path: Path) -> tuple[str, list[str]]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            header_name = next(
                (name for name in names if name.replace("\\", "/").endswith("Contents/header.xml")),
                None,
            )
            if header_name is None:
                raise HwpxError(
                    f"HWPX 패키지에 Contents/header.xml 이 없습니다: {path.name}"
                )
            header_xml = archive.read(header_name).decode("utf-8")
            section_names = sorted(
                name
                for name in names
                if "/section" in name.replace("\\", "/").lower() and name.endswith(".xml")
            )
            if not section_names:
                raise HwpxError(
                    f"HWPX 패키지에 section XML 이 없습니다: {path.name}"
                )
            sections = [archive.read(name).decode("utf-8") for name in section_names]
    except HwpxError:
        raise
    except BadZipFile as exc:
        raise HwpxError(
            f"HWPX(ZIP) 형식이 아닙니다: {path.name}. "
            "손상되었거나 바이너리 .hwp 일 수 있습니다."
        ) from exc
    except OSError as exc:
        raise HwpxError(f"HWPX 파일을 읽을 수 없습니다 ({path.name}): {exc}") from exc
    except UnicodeDecodeError as exc:
        raise HwpxError(f"HWPX XML 인코딩을 읽을 수 없습니다 ({path.name}): {exc}") from exc
    return header_xml, sections


def inspect_hwpx(path: str | Path) -> dict[str, Any]:
    """``.hwpx`` 경로에서 서식 그룹 JSON 을 만든다. COM/잠금 없음."""

    raw = str(path or "").strip()
    if not raw:
        raise UsageError("hwpx_inspect 에는 .hwpx 경로가 필요합니다.")
    target = Path(raw).expanduser()
    suffix = target.suffix.lower()
    if suffix == ".hwp":
        raise HwpxError(
            "바이너리 .hwp 는 검사할 수 없습니다. "
            "한글에서 .hwpx 로 저장한 뒤 다시 시도하세요."
        )
    if not target.is_file():
        raise HwpxError(f"HWPX 파일을 찾을 수 없습니다: {target}")
    header_xml, sections = _read_hwpx_xml(target)
    groups = inspect_owpml_parts(header_xml, sections)
    return {
        "ok": True,
        "command": "hwpx_inspect",
        "path": str(target),
        "backend": "owpml-xml",
        "hangul_required": False,
        "lock_required": False,
        "python_hwpx_version": hwpx_version(),
        **groups,
    }
