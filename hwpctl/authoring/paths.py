"""Stable hierarchical table selectors, independent of live control indexes."""
from __future__ import annotations
import xml.etree.ElementTree as ET
from typing import Any
from hwpctl.errors import UsageError
from hwpctl.hangul import parse_a1


def normalize_table_path(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {"root", "children"}:
        raise UsageError("table path requires root and optional children")
    root = value.get("root")
    if type(root) is not int or root < 0:
        raise UsageError("table path root must be a non-negative integer")
    children = value.get("children", [])
    if not isinstance(children, list):
        raise UsageError("table path children must be an array")
    result = []
    for child in children:
        if not isinstance(child, dict) or set(child) != {"cell", "index"}:
            raise UsageError("table child requires cell and index")
        cell, index = child["cell"], child["index"]
        if not isinstance(cell, str) or type(index) is not int or index < 0:
            raise UsageError("invalid child table address")
        parse_a1(cell)
        result.append({"cell": cell.strip().upper(), "index": index})
    return {"root": root, "children": result}


def table_index_from_hwpml(hwpml: str, path: dict[str, Any]) -> int:
    path = normalize_table_path(path)
    if not isinstance(hwpml, str):
        raise UsageError("HWPML must be text")
    if "<!DOCTYPE" in hwpml.upper() or "<!ENTITY" in hwpml.upper():
        raise UsageError("HWPML DTD and entity declarations are not allowed")
    try:
        root = ET.fromstring(hwpml)
    except ET.ParseError as exc:
        raise UsageError(f"Invalid HWPML: {exc}") from exc
    tag = lambda element: element.tag.rsplit("}", 1)[-1].upper()
    parents = {child: parent for parent in root.iter() for child in parent}
    tables = [node for node in root.iter() if tag(node) == "TABLE"]

    def nearest_table(node):
        parent = parents.get(node)
        while parent is not None:
            if tag(parent) == "TABLE":
                return parent
            parent = parents.get(parent)
        return None

    def select(items, index):
        if index >= len(items):
            raise UsageError("table path does not exist")
        return items[index]

    current = select([table for table in tables if nearest_table(table) is None], path["root"])
    for step in path["children"]:
        row, col = parse_a1(step["cell"])
        matches = []
        for node in current.iter():
            if tag(node) != "CELL" or nearest_table(node) is not current:
                continue
            try:
                address = (int(node.attrib["RowAddr"]), int(node.attrib["ColAddr"]))
            except (ValueError, KeyError) as exc:
                raise UsageError("HWPML cell has invalid or missing address") from exc
            if address == (row, col):
                matches.append(node)
        if not matches:
            raise UsageError("parent cell does not exist (or is a covered merge cell)")
        if len(matches) != 1:
            raise UsageError("parent cell address is ambiguous")
        cell = matches[0]
        current = select([node for node in cell.iter() if tag(node) == "TABLE" and nearest_table(node) is current], step["index"])
    return tables.index(current)
