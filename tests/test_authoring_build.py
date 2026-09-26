from copy import deepcopy
import hashlib
import json
import threading
from types import SimpleNamespace

import pytest

from hwpctl.authoring.model import SCHEMA, parse_spec
from hwpctl.authoring.compiler import compile_spec
from hwpctl.authoring.runtime import build_document, OwnedEngine
from hwpctl.errors import UsageError, LockBusyError, HangulCommandError
from hwpctl.lock import SingleWriterLock, writer_transaction


@pytest.fixture(autouse=True)
def synthetic_process_ownership(monkeypatch):
    """Fake sessions cannot own real Win32 handles; keep proof fail-closed."""
    import hwpctl.authoring.runtime as runtime
    snapshots = iter(({101}, {101, 202}))
    monkeypatch.setattr(runtime, "_hwp_pids", lambda: next(snapshots))
    monkeypatch.setattr(runtime, "_window_pid", lambda _hwnd: 202)
    monkeypatch.setattr(runtime, "_document_identity",
                        lambda app: id(app.XHwpDocuments.Active_XHwpDocument))


def document(content):
    return {"schema": SCHEMA, "sections": [{"content": content}]}


def table(content=None, **kwargs):
    return {"kind": "table", "rows": 1, "cols": 1, "column_widths_mm": [35],
            "row_heights_mm": [12], "cells": {"A1": {"content": content or []}}, **kwargs}


def test_recursive_compiler_keeps_sequence_and_locations(tmp_path):
    raw = document([{"kind": "paragraph", "content": [
        {"kind": "run", "text": "before"}, table([
            {"kind": "paragraph", "content": [{"kind": "run", "text": "left"}, table(),
                {"kind": "run", "text": "middle"}, table(), {"kind": "run", "text": "right"}]}]),
        {"kind": "run", "text": "between"}, table(), {"kind": "run", "text": "after"}]}])
    plan = compile_spec(parse_spec(raw, base_dir=tmp_path))
    grids = [c.arguments["table"] for c in plan if c.name == "set_table_grid"]
    assert grids == [0, 1, 2, 3]
    text = [c.arguments["runs"][0]["text"] for c in plan if "runs" in c.arguments]
    assert text == ["before", "left", "middle", "right", "between", "after"]
    assert [c.arguments["destination"] for c in plan if c.name == "exit_table"] == ["parent", "parent", "body", "body"]
    assert all(c.location.startswith("sections[0].content[0]") for c in plan)


def test_full_synthetic_design_and_page_plan_without_com(tmp_path):
    asset = tmp_path / "seal.png"
    asset.write_bytes(b"synthetic picture bytes for preflight only")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    grid = {"kind": "table", "id": "scores", "rows": 2, "cols": 2,
            "column_widths_mm": [30, 30], "row_heights_mm": [12, 12],
            "merges": ["A1:B1"], "properties": {"repeat_header": True},
            "cells": {"A1": {"content": [{"kind": "paragraph", "text": "heading"}]},
                      "A2": {"content": [{"kind": "paragraph", "text": "one"}]},
                      "B2": {"content": [{"kind": "paragraph", "text": "two"}]}}}
    raw = {"schema": SCHEMA, "assets": {"seal": {"path": "seal.png", "sha256": digest}},
           "sections": [
               {"page": {"landscape": True}, "page_number": {"position": "bottom_center"},
                "content": [{"kind": "paragraph", "runs": [{"text": "FAQ", "bold": True},
                              {"text": " synthetic", "italic": True}], "source": "source/heading"},
                            grid, {"kind": "chart", "table_id": "scores", "cell_range": "A1:B2"},
                            {"kind": "picture", "asset": "seal", "width_mm": 20, "height_mm": 20,
                             "position": {"mode": "floating", "x_mm": 10, "y_mm": 12,
                                          "wrap": "square"}},
                            {"kind": "shape", "shape_kind": "ellipse", "width_mm": 18,
                             "height_mm": 18, "fill": {"type": "solid", "color": "#3355AA"}},
                            {"kind": "text_box", "width_mm": 40, "height_mm": 15,
                             "paragraphs": [{"text": "editable"}],
                             "position": {"mode": "floating", "x_mm": 20, "y_mm": 20,
                                          "horizontal_relative_to": "page", "wrap": "behind_text"}},
                            {"kind": "page_hiding", "hide_page_num": True},
                            {"kind": "new_number", "number": 3},
                            {"kind": "page_break"}]},
               {"content": [{"kind": "paragraph", "text": "second section"}]}]}
    spec_path = tmp_path / "synthetic.json"
    spec_path.write_text(json.dumps(raw), encoding="utf-8")
    result = build_document(str(spec_path), str(tmp_path / "new.hwpx"), True,
                            _dispatch_factory=lambda: pytest.fail("COM reached"))
    assert result["ok"] and result["dry_run"] and not result["completed"]
    names = [entry["command"] for entry in result["plan"]]
    assert names.index("insert_chart") < names.index("insert_image")
    assert {"merge_cells", "insert_shape", "insert_text_box", "set_page_visibility",
            "restart_page_number", "insert_section"} <= set(names)
    assert next(entry for entry in result["plan"] if entry["source"] == "source/heading")["location"] == "sections[0].content[0]"
    assert not (tmp_path / "new.hwpx").exists()


@pytest.mark.parametrize("node", [
    {"kind": "mystery"}, {"kind": "paragraph", "typo": 1},
    {"kind": "paragraph", "content": [{"kind": "run", "text": "ok", "typo": 1}]},
    table([{"kind": "page_break"}]), table(properties={"repeat_header": "yes"}),
    table(has_margin=False), {"kind": "picture", "asset": "absent"},
    {"kind": "chart", "table_id": "later", "cell_range": "A1:B2"},
])
def test_recursive_preflight_rejects_bad_content_before_com(node, tmp_path):
    with pytest.raises(UsageError):
        build_document(document([node]), str(tmp_path / "new.hwp"),
                       _dispatch_factory=lambda: pytest.fail("COM reached"))
    assert not list(tmp_path.iterdir())


def test_property_omission_is_not_an_explicit_default(tmp_path):
    raw = document([table(properties={"repeat_header": False})])
    plan = compile_spec(parse_spec(raw, base_dir=tmp_path))
    props = next(c.arguments for c in plan if c.name == "set_table_properties")
    assert props == {"table": 0, "repeat_header": False, "page_break": None, "cell_spacing_mm": None}
    assert not any(c.name in {"set_cell_margin", "set_table_inside_margin"} for c in plan)


def test_table_review_is_explicit_and_chart_range_is_preflighted(tmp_path):
    raw = document([table(id="data", review=True),
                    {"kind": "chart", "table_id": "data", "cell_range": "A1:A1"}])
    plan = compile_spec(parse_spec(raw, base_dir=tmp_path))
    assert any(c.name == "layout_review" and c.arguments == {"table": 0, "dry_run": True}
               for c in plan)
    raw["sections"][0]["content"][1]["cell_range"] = "A1:B1"
    with pytest.raises(UsageError, match="exceeds table"):
        parse_spec(raw, base_dir=tmp_path)


def test_dry_run_does_not_create_paths_or_com(tmp_path):
    output = tmp_path / "missing" / "output.hwpx"
    result = build_document(document([{"kind": "paragraph", "text": "synthetic"}]), str(output), True,
                            _dispatch_factory=lambda: pytest.fail("COM reached"))
    assert result["ok"] and not result["completed"] and not result["saved"]
    assert not output.parent.exists()


def test_nested_command_lock_borrows_only_current_thread(tmp_path, monkeypatch):
    monkeypatch.setenv("HWPCTL_LOCK", str(tmp_path / "writer.lock"))
    observed = []
    def contender():
        try:
            with SingleWriterLock(timeout=0):
                observed.append("entered")
        except LockBusyError:
            observed.append("blocked")
    with pytest.raises(RuntimeError, match="synthetic"):
        with writer_transaction():
            with SingleWriterLock(timeout=0):
                thread = threading.Thread(target=contender)
                thread.start()
                thread.join(2)
                assert observed == ["blocked"]
            with pytest.raises(RuntimeError, match="Nested"):
                with writer_transaction():
                    pass
            raise RuntimeError("synthetic")
    with SingleWriterLock(timeout=0):
        pass


class App:
    def __init__(self, fail=None, *, count=1, body=""):
        self.fail = fail
        self.closed = self.quit = self.registered = False
        self.XHwpDocuments = self
        self.Count = count
        self.body = body
        self.Active_XHwpDocument = SimpleNamespace(FullName="")
    def RegisterModule(self, *args):
        self.registered = True
        return True
    def GetTextFile(self, *args):
        return self.body
    def Close(self, save):
        assert save is False
        self.closed = True
        self.Count = 0
    def Quit(self):
        self.quit = True
        if self.fail == "quit":
            raise RuntimeError("quit failure")


class Canvas:
    def __init__(self, px, app, backend):
        self.com = app
    def window_handle(self):
        return 123
    def assert_no_dialog(self):
        pass
    def doc_info(self):
        return SimpleNamespace(path="")


class FakeOwned(OwnedEngine):
    def dispatch(self, command, **kwargs):
        from pathlib import Path
        if self.canvas.com.fail == command:
            raise RuntimeError("synthetic command failure")
        if command == "save_as":
            Path(kwargs["path"]).write_bytes(b"synthetic saved document")
            self.canvas.com.Active_XHwpDocument.FullName = kwargs["path"]
        return {"ok": True}


@pytest.mark.parametrize("fail", [None, "insert_paragraph", "save_as", "quit"])
def test_owned_lifecycle_success_and_failures(fail, tmp_path, monkeypatch):
    import hwpctl.engine as api
    monkeypatch.setattr(api, "load_state", lambda: pytest.fail("global state accessed"))
    monkeypatch.setattr(api, "save_state", lambda *args: pytest.fail("global state changed"))
    monkeypatch.setenv("HWPCTL_LOCK", str(tmp_path / "writer.lock"))
    app = App(fail)
    output = tmp_path / "new.hwp"
    result = build_document(document([{"kind": "paragraph", "text": "synthetic"}]), str(output),
        _dispatch_factory=lambda: app, _canvas_factory=Canvas, _engine_factory=FakeOwned)
    assert app.closed and app.quit
    assert result["ok"] is (fail is None)
    assert result["completed"] is (fail is None)
    assert output.exists() is (fail is None)
    if fail == "insert_paragraph":
        assert result["failure"]["location"] == "sections[0].content[0]"


@pytest.mark.parametrize("case", ["multiple", "nonblank", "existing_pid", "missing_window"])
def test_unproven_com_object_is_never_closed_or_registered(case, tmp_path, monkeypatch):
    import hwpctl.authoring.runtime as runtime
    monkeypatch.setenv("HWPCTL_LOCK", str(tmp_path / "writer.lock"))
    app = App(count=2 if case == "multiple" else 1,
              body="user draft" if case == "nonblank" else "")
    if case == "existing_pid":
        monkeypatch.setattr(runtime, "_window_pid", lambda _hwnd: 101)
    if case == "missing_window":
        monkeypatch.setattr(runtime, "_window_pid", lambda _hwnd: 0)
    result = build_document(document([{"kind": "paragraph", "text": "new"}]),
                            str(tmp_path / "new.hwp"),
                            _dispatch_factory=lambda: app, _canvas_factory=Canvas,
                            _engine_factory=FakeOwned)
    assert not result["ok"] and not result["completed"]
    assert result["cleanup"]["skipped_unverified_owner"] is True
    assert not app.closed and not app.quit and not app.registered
    assert not (tmp_path / "new.hwp").exists()


def test_owned_document_switch_skips_discard_and_publish(tmp_path, monkeypatch):
    monkeypatch.setenv("HWPCTL_LOCK", str(tmp_path / "writer.lock"))
    app = App()
    class SwitchedDocumentEngine(FakeOwned):
        def dispatch(self, command, **kwargs):
            reply = super().dispatch(command, **kwargs)
            if command == "save_as":
                self.canvas.com.Active_XHwpDocument = SimpleNamespace(FullName="")
            return reply
    result = build_document(document([{"kind": "paragraph", "text": "new"}]),
                            str(tmp_path / "new.hwp"), _dispatch_factory=lambda: app,
                            _canvas_factory=Canvas, _engine_factory=SwitchedDocumentEngine)
    assert not result["ok"] and result["saved"] and not result["completed"]
    assert result["cleanup"]["skipped_changed_owner"] is True
    assert not app.closed and not app.quit
    assert not (tmp_path / "new.hwp").exists()


def test_saved_document_path_must_match_owned_staging_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HWPCTL_LOCK", str(tmp_path / "writer.lock"))
    app = App()
    class WrongSavePath(FakeOwned):
        def dispatch(self, command, **kwargs):
            reply = super().dispatch(command, **kwargs)
            if command == "save_as":
                self.canvas.com.Active_XHwpDocument.FullName = str(tmp_path / "another.hwp")
            return reply
    result = build_document(document([{"kind": "paragraph", "text": "new"}]),
                            str(tmp_path / "new.hwp"), _dispatch_factory=lambda: app,
                            _canvas_factory=Canvas, _engine_factory=WrongSavePath)
    assert not result["ok"] and result["saved"] and not result["completed"]
    assert result["cleanup"]["skipped_changed_owner"] is True
    assert not app.closed and not app.quit
    assert not (tmp_path / "new.hwp").exists()


def test_owned_engine_rejects_global_commands_and_identity_change():
    canvas = Canvas(None, App(), "fake")
    engine = OwnedEngine(canvas, allowed={"insert_paragraph"})
    with pytest.raises(UsageError):
        engine.dispatch("open")
    canvas.window_handle = lambda: 999
    with pytest.raises(HangulCommandError, match="identity changed"):
        engine._connect()


def test_owned_engine_rejects_document_switch_with_same_window():
    canvas = Canvas(None, App(), "fake")
    engine = OwnedEngine(canvas, allowed={"insert_paragraph"})
    canvas.com.Active_XHwpDocument = SimpleNamespace(FullName="")
    with pytest.raises(HangulCommandError, match="identity changed"):
        engine._connect()


def test_existing_output_never_overwritten(tmp_path):
    target = tmp_path / "keep.hwp"
    target.write_bytes(b"keep")
    with pytest.raises(UsageError):
        build_document(document([]), str(target), True)
    assert target.read_bytes() == b"keep"


def test_reference_source_path_never_overwritten(tmp_path):
    source = tmp_path / "source.hwp"
    source.write_bytes(b"private reference")
    spec = document([])
    spec["reference"] = {"input": str(source)}
    with pytest.raises(UsageError):
        build_document(spec, str(source), dry_run=True)
    assert source.read_bytes() == b"private reference"


def test_v1_flat_table_position_upgrades_without_losing_inline_margin(tmp_path):
    from hwpctl.authoring.model import upgrade_v1
    old = {"schema": "hwpctl.blank-rebuild/1", "operations": [table(
        position={"mode": "inline", "horizontal_relative_to": "paragraph",
                  "wrap": "inline", "outside_margin_mm": [0.5, 0.5, 0.5, 0.5]})]}
    original = deepcopy(old)
    upgraded = upgrade_v1(old)
    assert old == original
    assert upgraded["sections"][0]["content"][0]["position"] == {
        "mode": "inline", "affect_line_spacing": False,
        "outside_margin_mm": [0.5, 0.5, 0.5, 0.5]}
    plan = compile_spec(parse_spec(old, base_dir=tmp_path))
    assert any(c.name == "set_table_position" for c in plan)
