"""Independent synthetic input for authoring model and exact table geometry."""
from fractions import Fraction

import pytest

from hwpctl.authoring.geometry import CellMeasurement as Cell, recover_table_geometry
from hwpctl.authoring.model import SCHEMA, parse_spec, upgrade_v1
from hwpctl.authoring.paths import normalize_table_path, table_index_from_hwpml
from hwpctl.errors import UsageError


def test_raw_hu_geometry_uses_all_rows_not_first_row_or_outer_size():
    cells = [Cell(0, 0, 1, 2, 900, 200, "r0/c0"),
             Cell(1, 0, 1, 1, 300, 400, "r1/c0"),
             Cell(1, 1, 1, 1, 600, 400, "r1/c1")]
    result = recover_table_geometry(2, 2, cells)
    assert result.exact
    assert result.columns.tracks_hwp == (Fraction(300), Fraction(600))
    assert result.rows.tracks_hwp == (Fraction(200), Fraction(400))
    assert result.sources == ("r0/c0", "r1/c0", "r1/c1")


def test_vertical_merge_and_missing_dimensions_are_not_scaled():
    result = recover_table_geometry(2, 2, [
        Cell(0, 0, 2, 1, 300, 600, "left"),
        Cell(0, 1, 1, 1, 600, 200, "right-top"),
        Cell(1, 1, 1, 1, None, None, "right-bottom"),
    ])
    assert result.exact
    assert result.rows.tracks_hwp == (200, 400)


def test_unknown_tracks_remain_unknown():
    result = recover_table_geometry(1, 2, [Cell(0, 0, 1, 2, 900, 200, "merged")])
    assert not result.exact
    assert result.columns.status == "underdetermined"
    assert result.columns.tracks_hwp == (None, None)
    assert result.rows.tracks_hwp == (200,)


def test_conflicting_raw_measurements_remain_conflicting():
    result = recover_table_geometry(2, 1, [
        Cell(0, 0, 1, 1, 300, 200, "first"), Cell(1, 0, 1, 1, 301, 200, "second"),
    ])
    assert not result.exact
    assert result.columns.status == "inconsistent"


def test_merge_overlap_or_hole_cannot_pass_even_with_exact_tracks():
    overlap = recover_table_geometry(1, 1, [
        Cell(0, 0, 1, 1, 300, 200, "one"), Cell(0, 0, 1, 1, 300, 200, "two"),
    ])
    assert overlap.columns.status == overlap.rows.status == "exact"
    assert not overlap.exact
    assert "one, two" in overlap.issues[0]
    hole = recover_table_geometry(2, 2, [
        Cell(0, 0, 1, 1, 300, 200, "a"), Cell(1, 1, 1, 1, 600, 400, "d"),
    ])
    assert not hole.exact
    assert "2 grid slots" in hole.issues[0]


@pytest.mark.parametrize("width", [True, 0, -1, 3.2, float("inf"), "100"])
def test_grid_rejects_non_raw_hu(width):
    with pytest.raises(ValueError, match="raw HU"):
        recover_table_geometry(1, 1, [Cell(0, 0, 1, 1, width, 200, "source")])


# Three top-level tables across two sections, two siblings nested inside the
# first table, and one grandchild. No converter creates this expected source.
XML = """<HWPML><BODY><SECTION><P><TEXT><TABLE><ROW>
<CELL RowAddr="0" ColAddr="0"><PARALIST><P><TEXT>
<TABLE><ROW><CELL RowAddr="0" ColAddr="0"><PARALIST><P><TEXT>
<TABLE><ROW><CELL RowAddr="0" ColAddr="0"/></ROW></TABLE>
</TEXT></P></PARALIST></CELL></ROW></TABLE>
<TABLE><ROW><CELL RowAddr="0" ColAddr="0"/></ROW></TABLE>
</TEXT></P></PARALIST></CELL></ROW></TABLE><TABLE/>
</TEXT></P></SECTION><SECTION><P><TEXT><TABLE/></TEXT></P></SECTION></BODY></HWPML>"""


@pytest.mark.parametrize(("path", "expected"), [
    ({"root": 0}, 0), ({"root": 1}, 4), ({"root": 2}, 5),
    ({"root": 0, "children": [{"cell": "a1", "index": 0}]}, 1),
    ({"root": 0, "children": [{"cell": "A1", "index": 1}]}, 3),
    ({"root": 0, "children": [{"cell": "A1", "index": 0}, {"cell": "A1", "index": 0}]}, 2),
])
def test_hierarchical_table_indexes_preserve_siblings_sections_and_grandchildren(path, expected):
    assert table_index_from_hwpml(XML, path) == expected


@pytest.mark.parametrize("path", [
    {"root": True}, {"root": -1}, {"root": 0, "children": None},
    {"root": 0, "children": [{"cell": "A0", "index": 0}]},
    {"root": 0, "children": [{"cell": "A1", "index": True}]},
    {"root": 0, "surprise": 1},
])
def test_bad_path_fails_before_xml_access(path):
    with pytest.raises(UsageError):
        normalize_table_path(path)


@pytest.mark.parametrize("xml", ["broken", '<!DOCTYPE x><HWPML/>',
    '<TABLE><CELL RowAddr="bad" ColAddr="0"/></TABLE>',
    '<TABLE><CELL RowAddr="0" ColAddr="0"/><CELL RowAddr="0" ColAddr="0"/></TABLE>'])
def test_invalid_source_does_not_guess_target(xml):
    with pytest.raises(UsageError):
        table_index_from_hwpml(xml, {"root": 0, "children": [{"cell": "A1", "index": 0}]})


def test_model_copies_source_and_keeps_explicit_false_and_omission_distinct(tmp_path):
    content = [{"kind": "table", "properties": {"repeat_header": False}},
               {"kind": "table", "properties": {}}]
    for table in content:
        table.update(rows=1, cols=1, column_widths_mm=[20], row_heights_mm=[10], cells={})
    raw = {"schema": SCHEMA, "sections": [{"content": content}, {"content": []}]}
    spec = parse_spec(raw, base_dir=tmp_path)
    content.clear()
    assert len(spec.sections) == 2
    assert spec.sections[0]["content"][0]["properties"]["repeat_header"] is False
    assert "repeat_header" not in spec.sections[0]["content"][1]["properties"]


@pytest.mark.parametrize("raw", [None, [], {"schema": SCHEMA, "sections": []},
    {"schema": SCHEMA, "sections": [{"content": []}], "reference": {"bad": float("nan")}},
    {"schema": SCHEMA, "sections": [{"content": []}], "unknown": 1}])
def test_model_envelope_rejects_invalid_json_or_schema(raw, tmp_path):
    with pytest.raises(UsageError):
        parse_spec(raw, base_dir=tmp_path)


def test_v1_upgrade_preserves_operation_order_and_input():
    raw = {"schema": "hwpctl.blank-rebuild/1", "operations": [
        {"kind": "paragraph", "text": "before"}, {"kind": "table", "cells": {}},
        {"kind": "paragraph", "text": "after"}]}
    upgraded = upgrade_v1(raw)
    assert upgraded["sections"][0]["content"] == [
        raw["operations"][0], {**raw["operations"][1], "review": True}, raw["operations"][2]]
    upgraded["sections"][0]["content"][0]["text"] = "changed"
    assert raw["operations"][0]["text"] == "before"
