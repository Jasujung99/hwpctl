"""Opt-in synthetic authoring round trips, not a visual-equivalence claim."""
import gc
import os
import sys
import xml.etree.ElementTree as ET

import pytest

from hwpctl.authoring.model import SCHEMA
from hwpctl.authoring.runtime import build_document
from hwpctl.authoring.runtime import OwnedEngine
from hwpctl.hangul import HangulCanvas

pytestmark = pytest.mark.skipif(sys.platform != "win32" or os.environ.get("HWPCTL_RUN_HANGUL_INTEGRATION") != "1",
                                reason="explicit Hancom native opt-in required")


def table(content):
    return {"kind": "table", "rows": 1, "cols": 1, "column_widths_mm": [45], "row_heights_mm": [18],
            "cells": {"A1": {"content": content}}, "position": {"mode": "inline"}}


def test_owned_native_structure_without_save(tmp_path, monkeypatch):
    """Inspect native controls in memory; this does not claim SaveAs success."""
    monkeypatch.setenv("HWPCTL_LOCK", str(tmp_path / "build.lock"))
    captured = {}
    class CaptureEngine(OwnedEngine):
        def dispatch(self, command, **kwargs):
            if command == "save_as":
                from pathlib import Path
                captured["xml"] = str(self.canvas.com.GetTextFile("HWPML2X", ""))
                Path(kwargs["path"]).write_bytes(b"synthetic capture placeholder")
                return {"ok": True}
            return super().dispatch(command, **kwargs)
    raw = {"schema": SCHEMA, "sections": [{"content": [
        {"kind": "paragraph", "content": [{"kind": "run", "text": "BEFORE"},
            table([{"kind": "paragraph", "text": "INNER"}]), {"kind": "run", "text": "AFTER"}]}]},
        {"content": [{"kind": "paragraph", "text": "SECOND"},
            {"kind": "shape", "shape_kind": "rectangle", "width_mm": 25, "height_mm": 15,
             "fill": {"type": "solid", "color": "#2244AA"}},
            {"kind": "text_box", "width_mm": 40, "height_mm": 20,
             "paragraphs": [{"text": "BOX1"}, {"text": "BOX2"}]},
            {"kind": "paragraph", "text": "END"}]}]}
    result = build_document(raw, str(tmp_path / "capture.hwp"), _engine_factory=CaptureEngine)
    assert result["ok"], (result.get("failure"), result["cleanup"])
    root = ET.fromstring(captured["xml"])
    assert len(list(root.iter("SECTION"))) == 2
    assert len(list(root.iter("TABLE"))) == 1
    rectangle = next(node for node in root.iter("RECTANGLE") if node.find("SHAPEOBJECT") is not None)
    assert abs(int(rectangle.attrib["X1"]) - round(25 * 7200 / 25.4)) <= 1
    assert abs(int(rectangle.attrib["Y2"]) - round(15 * 7200 / 25.4)) <= 1
    text = "".join(e.text or "" for e in root.iter("CHAR"))
    assert text == "BEFOREINNERAFTERSECONDBOX1BOX2END", text


@pytest.mark.parametrize("suffix", ["hwp", "hwpx"])
def test_owned_build_nested_order_sections_and_shapes(tmp_path, suffix, monkeypatch):
    import win32com.client
    monkeypatch.setenv("HWPCTL_LOCK", str(tmp_path / "build.lock"))
    def run(text):
        return {"kind": "run", "text": text}
    def para(text):
        return {"kind": "paragraph", "text": text}
    raw = {"schema": SCHEMA, "sections": [
        {"content": [{"kind": "paragraph", "content": [run("BEFORE"),
            table([{"kind": "paragraph", "content": [run("LEFT"), table([para("CHILD1")]),
                run("MID"), table([para("CHILD2")]), run("RIGHT")]}]),
            run("BETWEEN"), table([para("SECOND")]), run("AFTER")]}]},
        {"page": {"landscape": True}, "content": [para("SECTION2"),
            {"kind": "shape", "shape_kind": "rectangle", "width_mm": 25, "height_mm": 15,
             "fill": {"type": "solid", "color": "#2244AA"}},
            {"kind": "text_box", "width_mm": 45, "height_mm": 20, "paragraphs": [
                {"runs": [{"text": "BOX1", "bold": True}]}, {"text": "BOX2"}], "margin": [1, 2, 3, 4]},
            para("END")]}
    ]}
    output = tmp_path / ("synthetic." + suffix)
    result = build_document(raw, str(output))
    assert result["ok"], (result.get("failure"), result["cleanup"])
    assert result["completed"] and result["cleanup"] == {"created": True, "closed": True, "quit": True}
    app = win32com.client.DispatchEx("HWPFrame.HwpObject")
    try:
        app.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        assert app.Open(str(output), suffix.upper(), "readonly:true")
        xml = str(app.GetTextFile("HWPML2X", ""))
        root = ET.fromstring(xml)
        assert len(root.findall("./BODY/SECTION")) == 2
        assert len(list(root.iter("TABLE"))) == 4
        text = "".join(e.text or "" for e in root.iter("CHAR"))
        assert text == "BEFORELEFTCHILD1MIDCHILD2RIGHTBETWEENSECONDAFTERSECTION2BOX1BOX2END", text
        rects = list(root.iter("RECTANGLE"))
        assert len(rects) >= 2
        sizes = [e.attrib for e in root.iter("SIZE")]
        assert any(abs(int(s.get("Width", 0)) - round(25 * 7200 / 25.4)) <= 1 for s in sizes), sizes
    finally:
        app.XHwpDocuments.Close(False)
        app.Quit()
        app = None
        gc.collect()
