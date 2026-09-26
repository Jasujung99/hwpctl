"""Pure tests for the public-command-only FAQ 002 rebuild driver.

They use a recording Engine, never instantiate HangulCanvas or a live HWP COM
object. Opt-in native save/reopen coverage lives in test_hangul_live_integration.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "examples" / "rebuild_faq_002_from_normalized_spec.py"
MODULE_SPEC = importlib.util.spec_from_file_location("faq_002_rebuild_driver", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
driver = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = driver
MODULE_SPEC.loader.exec_module(driver)
compatibility_driver = driver
from hwpctl.authoring import legacy as driver


def test_legacy_example_preserves_public_imports():
    assert compatibility_driver.BuildSpec is driver.BuildSpec
    assert compatibility_driver.PublicBuild is driver.PublicBuild
    assert compatibility_driver.load_spec is driver.load_spec


def test_text_box_margin_uses_existing_public_command():
    box = driver._parse_text_box({"kind": "text_box", "text": "Synthetic",
        "width_mm": 40, "height_mm": 20, "margin": [1, 2, 3, 4]}, index=0)
    assert box.args["margin"] == [1, 2, 3, 4]
    with pytest.raises(driver.SpecError, match="margin"):
        driver._parse_text_box({"kind": "text_box", "text": "Synthetic",
            "width_mm": 40, "height_mm": 20, "margin": [-1, 2, 3, 4]}, index=0)


def _spec() -> dict[str, object]:
    return {
        "schema": "hwpctl.blank-rebuild/1",
        "reference": {"label": "002 FAQ", "source_sha256": "A" * 64},
        "page": {
            "paper_width": 210,
            "paper_height": 297,
            "left": 20,
            "right": 20,
            "top": 10,
            "bottom": 10,
            "header": 0,
            "footer": 0,
            "gutter": 0,
            "landscape": False,
            "apply": "all",
        },
        "page_number": {"position": "bottom_center", "separator": "-"},
        "assets": {},
        "operations": [
            {
                "kind": "paragraph",
                "runs": [{
                    "text": "표 앞 문단",
                    "font": "맑은 고딕",
                    "size": 10,
                    "kerning": True,
                    "underline": {"enabled": True, "color": "#000000", "type": "bottom", "shape": "solid"},
                    "strikeout": {"enabled": False, "type": "continuous", "shape": "solid"},
                }],
                "paragraph": {
                    "align": "left",
                    "line_spacing_percent": 160,
                    "break_latin_word": "keep_word",
                    "break_non_latin_word": "keep_word",
                },
            },
            {
                "kind": "table",
                "rows": 1,
                "cols": 1,
                "column_widths_mm": [165],
                "row_heights_mm": [10],
                "default_margin_mm": [0, 0, 0, 0],
                "merges": [],
                "exit_cell": "A1",
                # This is the finalized flat source record.  The driver must
                # retain its meaningful inline layout fields rather than
                # treating every inline table as an implicit default.
                "position": {
                    "mode": "inline",
                    "horizontal_relative_to": "paragraph",
                    "vertical_relative_to": "paragraph",
                    "horizontal_align": "left",
                    "vertical_align": "top",
                    "x_mm": 0,
                    "y_mm": 0,
                    "wrap": "inline",
                    "flow_with_text": True,
                    "allow_overlap": False,
                    "affect_line_spacing": False,
                    "outside_margin_mm": [0.5, 0.5, 0.5, 0.5],
                },
                "properties": {
                    "repeat_header": True,
                    "page_break": "cell",
                    "cell_spacing_mm": 0,
                },
                "cells": {
                    "A1": {
                        "paragraphs": [
                            {
                                "runs": [
                                    {"text": "굵은", "bold": True},
                                    {"text": " 일반", "font": "맑은 고딕"},
                                ],
                                "paragraph": {"align": "center"},
                            }
                        ],
                        "fill": {"type": "linear_gradient", "angle": 90, "stops": ["#EAFFFC", "#FF843A"]},
                    }
                },
            },
        ],
    }


class RecordingEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def dispatch(self, command: str, **kwargs: object) -> dict[str, object]:
        self.calls.append((command, kwargs))
        return {"ok": True, "command": command, "warnings": []}


def test_driver_builds_only_through_public_dispatch(tmp_path: Path) -> None:
    spec_path = tmp_path / "faq-002.json"
    spec_path.write_text(json.dumps(_spec()), encoding="utf-8")
    spec = driver.load_spec(spec_path)
    output = tmp_path / "new-faq-002.hwp"
    log = output.with_suffix(".hwp.build.json")
    driver.preflight(spec, output, log)

    engine = RecordingEngine()
    build = driver.PublicBuild(engine=engine, spec=spec)
    build.build(output)

    commands = [command for command, _ in engine.calls]
    assert commands[:3] == ["open", "set_pagedef", "set_page_number"]
    assert "insert_paragraph" in commands
    assert "write_cell" in commands
    assert "set_table_grid" in commands
    assert "move_to_cell" in commands
    assert "set_col_width" not in commands
    assert "set_row_height" not in commands
    assert "set_table_properties" in commands
    assert "set_table_position" in commands
    assert "exit_table" in commands
    assert "fill_cells" not in commands
    assert "set_format" not in commands
    assert commands[-1] == "save_as"
    assert all("path" not in args for command, args in engine.calls if command == "open")

    calls = dict(engine.calls)
    assert calls["set_table_properties"] == {
        "table": 0,
        "page_break": "cell",
        "repeat_header": True,
        "cell_spacing_mm": 0.0,
    }
    # The source-faithful inline record is reduced to the public command's
    # inline contract; paragraph-relative offsets are meaningless once
    # TreatAsChar is true and must not leak into Engine validation.
    assert calls["set_table_position"] == {
        "table": 0,
        "position": {
            "mode": "inline",
            "affect_line_spacing": False,
            "outside_margin_mm": [0.5, 0.5, 0.5, 0.5],
        },
    }
    assert commands.index("exit_table") < commands.index("set_table_position")


def test_driver_resumes_open_blank_document_without_replaying_prior_operations(tmp_path: Path) -> None:
    spec_path = tmp_path / "faq-002.json"
    spec_path.write_text(json.dumps(_spec()), encoding="utf-8")
    spec = driver.load_spec(spec_path)
    engine = RecordingEngine()

    build = driver.PublicBuild(engine=engine, spec=spec)
    build.resume(tmp_path / "resumed.hwp", from_operation=1)

    commands = [command for command, _ in engine.calls]
    assert "open" not in commands
    assert "set_pagedef" not in commands
    assert commands[0] == "create_table"
    assert commands[-1] == "save_as"
    assert build.resumed_from_operation == 1
    assert build.counts == {
        "paragraphs": 1,
        "tables": 1,
        "cells": 1,
        "text_boxes": 0,
        "images": 0,
    }


def test_driver_rejects_plain_text_and_runs_in_same_paragraph(tmp_path: Path) -> None:
    raw = _spec()
    operation = raw["operations"][0]  # type: ignore[index]
    operation["text"] = "중복"  # type: ignore[index]
    spec_path = tmp_path / "invalid.json"
    spec_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(driver.SpecError, match="text와 비어 있지 않은 runs"):
        driver.load_spec(spec_path)


def test_driver_accepts_radial_gradient_through_public_fill_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _spec()
    table = raw["operations"][1]  # type: ignore[index]
    table["cells"]["A1"]["fill"] = {  # type: ignore[index]
        "type": "radial_gradient",
        "stops": ["#FFFFFF", "#000000"],
    }
    spec_path = tmp_path / "radial.json"
    spec_path.write_text(json.dumps(raw), encoding="utf-8")

    spec = driver.load_spec(spec_path)
    assert "radial_gradient" in driver.required_capabilities(spec)
    # The current public bridge exposes radial fill through set_cell_fill, so a
    # dry-run must succeed without opening HWP.
    driver.preflight(spec, tmp_path / "output.hwp", tmp_path / "output.hwp.build.json")

    commands = set(driver.tool_names())
    monkeypatch.setattr(driver, "tool_names", lambda: sorted(commands - {"set_cell_fill"}))
    with pytest.raises(driver.SpecError, match="radial_gradient"):
        driver.preflight(spec, tmp_path / "output.hwp", tmp_path / "output.hwp.build.json")


def test_driver_preserves_flat_position_properties_and_page_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _spec()
    table = raw["operations"][1]  # type: ignore[index]
    table["position"] = {  # type: ignore[index]
        "mode": "floating",
        "horizontal_relative_to": "paragraph",
        "vertical_relative_to": "paragraph",
        "horizontal_align": "left",
        "vertical_align": "top",
        "x_mm": 0.02,
        "y_mm": 1.61,
        "wrap": "top_and_bottom",
        "flow_with_text": True,
        "allow_overlap": False,
        "affect_line_spacing": False,
        "outside_margin_mm": [1, 1, 1, 1],
    }
    table["page_controls_after"] = [  # type: ignore[index]
        {"kind": "page_hiding", "hide_page_num": True},
        {"kind": "new_number", "number": 1, "number_type": "page"},
    ]
    spec_path = tmp_path / "future-controls.json"
    spec_path.write_text(json.dumps(raw), encoding="utf-8")
    spec = driver.load_spec(spec_path)

    assert driver.required_capabilities(spec) >= {
        "table_position", "table_properties", "page_visibility", "page_number_restart",
    }
    table_spec = next(operation for operation in spec.operations if isinstance(operation, driver.Table))
    assert table_spec.position == {
        "mode": "floating",
        "horizontal_relative_to": "para",
        "vertical_relative_to": "para",
        "horizontal_align": "left",
        "vertical_align": "top",
        "x_mm": 0.02,
        "y_mm": 1.61,
        "wrap": "top_and_bottom",
        "flow_with_text": True,
        "allow_overlap": False,
        "affect_line_spacing": False,
        "outside_margin_mm": [1.0, 1.0, 1.0, 1.0],
    }
    driver.preflight(spec, tmp_path / "output.hwp", tmp_path / "output.hwp.build.json")

    engine = RecordingEngine()
    driver.PublicBuild(engine=engine, spec=spec).build(tmp_path / "output.hwp")
    commands = [command for command, _ in engine.calls]
    assert commands.index("exit_table") < commands.index("set_table_position")
    assert commands.index("set_table_position") < commands.index("set_page_visibility")
    assert commands.index("set_page_visibility") < commands.index("restart_page_number")

    available = set(driver.tool_names())
    monkeypatch.setattr(driver, "tool_names", lambda: sorted(available - {"set_table_position"}))
    with pytest.raises(driver.SpecError, match="table_position"):
        driver.preflight(spec, tmp_path / "output.hwp", tmp_path / "output.hwp.build.json")


def test_published_synthetic_spec_dry_run_uses_no_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(driver, "Engine", lambda: pytest.fail("must not construct Engine"))
    spec = driver.load_spec(ROOT / "examples/specs/faq.synthetic.json")
    driver.preflight(spec, tmp_path / "faq.hwp", tmp_path / "record.json")
    assert driver.plan(spec)["tables"] == 1
    recorder = RecordingEngine()
    driver.PublicBuild(engine=recorder, spec=spec).build(tmp_path / "faq.hwp")
    assert {name for name, _ in recorder.calls} <= set(driver.tool_names())
    assert sum(name == "set_cell_margin" for name, _ in recorder.calls) == 1
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("mutation,match", [
    (lambda raw: raw["reference"].update(path="private.hwp"), "원본 경로"),
    (lambda raw: raw["operations"][1].update(shape_kind="ellipse"), "generic_shapes"),
    (lambda raw: raw["operations"][1].update(column_widths_mm=[float("nan")]), "0보다"),
])
def test_unsupported_or_invalid_input_fails_before_authoring(tmp_path, mutation, match):
    raw = _spec()
    mutation(raw)
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(driver.SpecError, match=match):
        driver.load_spec(path)


def test_preflight_catches_missing_asset_and_grid_command(tmp_path, monkeypatch):
    raw = _spec()
    raw["operations"][1]["cells"]["A1"]["images"] = [{"asset": "missing"}]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    spec = driver.load_spec(path)
    with pytest.raises(driver.SpecError, match="assets에 없습니다"):
        driver.preflight(spec, tmp_path / "out.hwp", tmp_path / "record.json")
    spec = driver.load_spec(ROOT / "examples/specs/faq.synthetic.json")
    names = set(driver.tool_names()) - {"set_table_grid"}
    monkeypatch.setattr(driver, "tool_names", lambda: sorted(names))
    with pytest.raises(driver.SpecError, match="set_table_grid"):
        driver.preflight(spec, tmp_path / "out.hwp", tmp_path / "record.json")


def test_preflight_refuses_overwrite_and_log_collision(tmp_path):
    spec = driver.load_spec(ROOT / "examples/specs/faq.synthetic.json")
    output = tmp_path / "out.hwp"
    with pytest.raises(driver.SpecError, match="서로 다른"):
        driver.preflight(spec, output, output)
    output.write_bytes(b"keep")
    with pytest.raises(driver.SpecError, match="덮어쓰지"):
        driver.preflight(spec, output, tmp_path / "record.json")
    assert output.read_bytes() == b"keep"
