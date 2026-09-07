"""Conservative editing helpers: visible marks and unused-format compaction.

Blank-looking paragraphs can anchor floating objects. This module never removes
paragraphs, controls, text runs, or named styles based on their visual emptiness.
"""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from typing import Any

from hwpctl.errors import HangulCommandError, UsageError


def set_edit_marks(com: Any, *, control_marks: bool, paragraph_marks: bool) -> dict:
    """Set, don't toggle, HWP's view bits; preserve unrelated view settings."""
    if not isinstance(control_marks, bool) or not isinstance(paragraph_marks, bool):
        raise UsageError("조판부호·문단부호 값은 true/false여야 합니다.")
    if control_marks and not paragraph_marks:
        raise UsageError("조판부호 보기는 문단부호도 표시합니다. 둘 다 켜세요.")
    props = com.ViewProperties
    before = int(props.Item("OptionFlag"))
    wanted = (before & ~6) | (2 if control_marks else 0) | (4 if paragraph_marks else 0)
    if wanted != before:
        props.SetItem("OptionFlag", wanted)
        com.ViewProperties = props
    after = int(com.ViewProperties.Item("OptionFlag"))
    if after != wanted:
        raise HangulCommandError("보기 설정을 적용했지만 읽어 온 값이 요청과 다릅니다.")
    return {"before_flags": before, "after_flags": after,
            "control_marks": bool(after & 2), "paragraph_marks": bool(after & 6),
            "changed": before != after, "document_content_changed": False}


def compact_formatting_xml(documents: dict[str, bytes]) -> tuple[dict[str, bytes], dict]:
    """Remove only unreferenced char/para definitions, then remap all refs.

    Pass every XML/HPF part from an unsigned HWPX package. The caller owns file
    IO and must save a new package. No paragraph or layout object is deleted.
    """
    if "Contents/header.xml" not in documents:
        raise UsageError("Contents/header.xml이 필요합니다.")
    roots = {}
    for name, data in documents.items():
        if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
            raise UsageError("DTD/ENTITY가 있는 XML은 정리하지 않습니다.")
        try:
            for _, (prefix, uri) in ET.iterparse(io.BytesIO(data), events=["start-ns"]):
                if not prefix.startswith("ns"):
                    ET.register_namespace(prefix, uri)
            roots[name] = ET.fromstring(data)
        except ET.ParseError as exc:
            raise UsageError(f"잘못된 XML: {name}") from exc
    hh = "{http://www.hancom.co.kr/hwpml/2011/head}"
    header = roots["Contents/header.xml"]
    changed = set()
    report = {"removed_character_formats": 0, "removed_paragraph_formats": 0,
              "removed_paragraphs": 0, "preserved_paragraphs": 0}
    for root in roots.values():
        report["preserved_paragraphs"] += sum(
            e.tag == "{http://www.hancom.co.kr/hwpml/2011/paragraph}p" for e in root.iter())
    for group, tag, ref, metric in [
        ("charProperties", "charPr", "charPrIDRef", "removed_character_formats"),
        ("paraProperties", "paraPr", "paraPrIDRef", "removed_paragraph_formats"),
    ]:
        parent = header.find(".//" + hh + group)
        if parent is None:
            raise UsageError(f"{group}가 없습니다.")
        defs = list(parent)
        ids = [d.get("id") for d in defs]
        if any(d.tag != hh + tag for d in defs) or None in ids or len(set(ids)) != len(ids):
            raise UsageError(f"{group} 정의가 모호합니다.")
        used = {"0"} if "0" in ids else set()
        locations = []
        for name, root in roots.items():
            for elem in root.iter():
                for attr, value in elem.attrib.items():
                    if attr.split("}")[-1] == ref:
                        # Hancom exports UINT32_MAX for inherited numbering text.
                        if ref == "charPrIDRef" and value == "4294967295" and elem.tag == hh + "paraHead":
                            continue
                        used.add(value); locations.append((name, elem, attr, value))
        if used - set(ids):
            raise UsageError(f"해결되지 않는 {ref} 참조가 있습니다.")
        kept = [d for d in defs if d.get("id") in used]
        remap = {d.get("id"): str(i) for i, d in enumerate(kept)}
        report[metric] = len(defs) - len(kept)
        for d in defs:
            if d.get("id") not in used:
                parent.remove(d); changed.add("Contents/header.xml")
            elif d.get("id") != remap[d.get("id")]:
                d.set("id", remap[d.get("id")]); changed.add("Contents/header.xml")
        if parent.get("itemCnt") != str(len(kept)):
            parent.set("itemCnt", str(len(kept))); changed.add("Contents/header.xml")
        for name, elem, attr, old in locations:
            if old != remap[old]:
                elem.set(attr, remap[old]); changed.add(name)
    result = dict(documents)
    for name in changed:
        result[name] = ET.tostring(roots[name], encoding="utf-8", xml_declaration=True)
    report["changed_parts"] = sorted(changed)
    return result, report
