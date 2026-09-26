"""한/글 2022 실기 회귀 테스트.

기본 pytest/CI에서는 실행하지 않는다. ``HWPCTL_RUN_HANGUL_INTEGRATION=1``을 명시한
Windows 한/글 2022 환경에서만 DispatchEx로 별도 합성 문서를 만들고 소유 창만 닫는다.
저장·재열기/내보내기 검사는 pytest 임시 폴더의 합성 파일만 사용한다.
사용자가 열어 둔 문서·참조본·구현본은 대상이 아니다.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from typing import Any

import pytest

from hwpctl.engine import Engine
from hwpctl.hangul import HangulCanvas, a1


pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("HWPCTL_RUN_HANGUL_INTEGRATION") != "1",
    reason="Windows + 한/글 2022에서 HWPCTL_RUN_HANGUL_INTEGRATION=1일 때만 실행",
)


def _new_blank_canvas() -> tuple[Any, HangulCanvas]:
    win32com = pytest.importorskip("win32com.client")
    app = win32com.DispatchEx("HWPFrame.HwpObject")
    app.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
    if int(getattr(app.XHwpDocuments, "Count", 0) or 0) == 0:
        app.XHwpDocuments.Add(False)
    return app, HangulCanvas(px=None, com=app, backend="win32com")


def _close_without_saving(app: Any) -> None:
    try:
        app.XHwpDocuments.Close(False)
    finally:
        app.Quit()


def _isolated_engine(canvas: HangulCanvas) -> tuple[Engine, list[tuple[str, int]]]:
    """실기 문서만 대상으로 Engine 계약을 실행하되 사용자 Undo 상태에는 쓰지 않는다."""
    engine = Engine()
    records: list[tuple[str, int]] = []
    engine._connect = lambda: canvas  # type: ignore[method-assign]
    engine._record_undo = lambda command, steps: records.append((command, steps))  # type: ignore[method-assign]
    return engine, records


def test_table_grid_geometry_survives_a_page_boundary() -> None:
    """행별 실제 셀 순회가 하단(다음 쪽)까지 Width·Height를 적용하는지 확인한다."""
    app, canvas = _new_blank_canvas()
    try:
        rows, cols = 20, 3  # 16~17mm 행 20개는 A4 본문 영역을 넘어선다.
        widths = [29.0, 47.0, 31.0]
        heights = [16.0 + (row % 2) for row in range(rows)]
        canvas.create_table(rows=rows, cols=cols, header=False)
        canvas.get_into_nth_table(0)
        assert canvas.table_cell_addresses() == [
            a1(row, col) for row in range(rows) for col in range(cols)
        ]
        saved = canvas.get_pos()
        assert saved
        try:
            engine, records = _isolated_engine(canvas)
            result = engine.set_table_grid(
                table=0,
                column_widths_mm=widths,
                row_heights_mm=heights,
            )
            assert result["hangul_actions"] == rows * cols
            assert result["cursor_restored"] is True
            assert records == [("set_table_grid", rows * cols)]
            assert canvas.get_pos() == saved
            for row, col in ((0, 0), (0, 2), (10, 1), (19, 0), (19, 2)):
                canvas.goto_addr(a1(row, col))
                assert canvas.get_col_width() == pytest.approx(widths[col], abs=0.05)
                assert canvas.get_row_height() == pytest.approx(heights[row], abs=0.05)
        finally:
            assert canvas.set_pos(saved)
    finally:
        _close_without_saving(app)


def test_parent_exit_stops_in_the_immediate_parent_cell() -> None:
    app, canvas = _new_blank_canvas()
    try:
        canvas.create_table(rows=1, cols=1, header=False)
        canvas.create_table(rows=1, cols=1, header=False)
        canvas.goto_addr("A1")
        inner_position = canvas.get_pos()
        assert inner_position

        engine, records = _isolated_engine(canvas)
        result = engine.exit_table(destination="parent")

        parent_position = canvas.get_pos()
        assert parent_position
        assert canvas.is_cell()
        assert parent_position[0] != inner_position[0]
        assert result["context"] == "parent_cell"
        assert result["in_cell"] is True
        assert records == []
    finally:
        _close_without_saving(app)


def test_nonterminating_paragraph_keeps_one_native_paragraph() -> None:
    """terminate=false 뒤의 다음 문단 작성이 빈 문단을 몰래 하나 만들지 않는다."""
    app, canvas = _new_blank_canvas()
    try:
        engine, records = _isolated_engine(canvas)
        first = engine.insert_paragraph("앞", terminate=False)
        second = engine.insert_paragraph("뒤", terminate=True)

        text = canvas.get_body_text()
        assert "앞뒤" in text
        assert text.count("\r\n") == 1
        assert first["terminate"] is False
        assert second["terminate"] is True
        assert records[0][0] == "insert_paragraph"
        assert records[1][0] == "insert_paragraph"
    finally:
        _close_without_saving(app)


def test_font_slots_preserve_hft_type_for_hanyang_gyeongothic() -> None:
    """HFT 글꼴은 이름과 타입을 같은 HCharShape 실행에 넣어야 대체되지 않는다."""
    app, canvas = _new_blank_canvas()
    try:
        text = "한양견고딕 HFT 실기 검증"
        canvas.set_font(
            font_slots={"hangul": {"name": "한양견고딕", "type": "hft"}}
        )
        canvas.insert_text(text)
        assert text in canvas.get_body_text()

        # HCharShape COM 객체는 쓰기 항목을 다시 읽어 주지 않는 설치본이 있다.
        # 저장하지 않는 읽기 전용 HWPML에서 실제 TEXT → CharShape → FONTID →
        # Hangul FONTFACE 연결을 따라가면, 글꼴 이름만 등록된 경우가 아니라
        # 방금 쓴 한국어 텍스트가 HFT 글꼴을 실제로 참조하는지 검증할 수 있다.
        root = ET.fromstring(str(app.GetTextFile("HWPML2X", "") or ""))

        def local_name(element: Any) -> str:
            return str(element.tag).rsplit("}", 1)[-1].upper()

        font_faces: dict[str, Any] = {}
        for face in root.iter():
            if local_name(face) != "FONTFACE" or face.attrib.get("Lang") != "Hangul":
                continue
            for candidate in face:
                if local_name(candidate) == "FONT":
                    font_faces[candidate.attrib["Id"]] = candidate
            break

        matching_text = next(
            element
            for element in root.iter()
            if local_name(element) == "TEXT" and "".join(element.itertext()) == text
        )
        charshape_id = matching_text.attrib["CharShape"]
        charshape = next(
            element
            for element in root.iter()
            if local_name(element) == "CHARSHAPE" and element.attrib.get("Id") == charshape_id
        )
        font_id = next(
            element.attrib["Hangul"]
            for element in charshape
            if local_name(element) == "FONTID"
        )
        applied_font = font_faces[font_id]
        assert applied_font.attrib["Name"] == "한양견고딕"
        assert applied_font.attrib["Type"].lower() == "hft"
    finally:
        _close_without_saving(app)


def test_floating_table_left_alignment_uses_table_placement_enum() -> None:
    """TablePropertyDialog의 왼쪽 정렬은 문단 HAlign이 아니라 raw 0이다."""
    app, canvas = _new_blank_canvas()
    try:
        canvas.create_table(rows=1, cols=1, header=False)
        assert canvas.set_table_position(
            table=0,
            position={
                "mode": "floating",
                "outside_margin_mm": [0.0, 0.0, 0.0, 0.0],
                "horizontal_relative_to": "para",
                "vertical_relative_to": "para",
                "horizontal_align": "left",
                "vertical_align": "top",
                "wrap": "top_and_bottom",
                "x_mm": 0.0,
                "y_mm": 0.0,
            },
        ) == 1
        assert canvas.is_cell()
        canvas.insert_text("표 안")

        root = ET.fromstring(str(app.GetTextFile("HWPML2X", "") or ""))
        position = next(
            element
            for element in root.iter()
            if str(element.tag).rsplit("}", 1)[-1].upper() == "POSITION"
        )
        assert position.attrib["TreatAsChar"].lower() == "false"
        assert position.attrib["HorzAlign"] == "Left"
    finally:
        _close_without_saving(app)


def test_table_inside_margin_serializes_to_table_hwpml_and_restores_cursor() -> None:
    """표 전역 CellMargin*은 CELL/CELLMARGIN이 아닌 TABLE/INSIDEMARGIN이어야 한다."""
    app, canvas = _new_blank_canvas()
    try:
        canvas.create_table(rows=2, cols=2, header=False)
        saved = canvas.get_pos()
        assert saved

        before_root = ET.fromstring(str(app.GetTextFile("HWPML2X", "") or ""))

        def local_name(element: Any) -> str:
            return str(element.tag).rsplit("}", 1)[-1].upper()

        before_table = next(
            element for element in before_root.iter() if local_name(element) == "TABLE"
        )
        before_cell_margins = [
            dict(element.attrib)
            for element in before_table.iter()
            if local_name(element) == "CELLMARGIN"
        ]

        engine, records = _isolated_engine(canvas)
        result = engine.set_table_inside_margin(
            table=0,
            left=4.0,
            right=4.5,
            top=1.0,
            bottom=1.5,
        )

        assert result["margin_mm"] == [4.0, 4.5, 1.0, 1.5]
        assert result["cursor_restored"] is True
        assert records == [("set_table_inside_margin", 1)]
        assert canvas.get_pos() == saved

        root = ET.fromstring(str(app.GetTextFile("HWPML2X", "") or ""))

        table = next(element for element in root.iter() if local_name(element) == "TABLE")
        inside = next(element for element in table.iter() if local_name(element) == "INSIDEMARGIN")
        assert inside.attrib == {
            "Bottom": str(app.MiliToHwpUnit(1.5)),
            "Left": str(app.MiliToHwpUnit(4.0)),
            "Right": str(app.MiliToHwpUnit(4.5)),
            "Top": str(app.MiliToHwpUnit(1.0)),
        }
        assert [
            dict(element.attrib)
            for element in table.iter()
            if local_name(element) == "CELLMARGIN"
        ] == before_cell_margins
    finally:
        _close_without_saving(app)


def test_hierarchical_table_selector_matches_native_control_order():
    from hwpctl.authoring.paths import table_index_from_hwpml
    app, canvas = _new_blank_canvas()
    try:
        engine, _ = _isolated_engine(canvas)
        engine.dispatch("create_table", rows=1, cols=1, header=False, cell_margin=None)
        engine.dispatch("create_table", rows=1, cols=1, header=False, cell_margin=None)
        engine.dispatch("insert_paragraph", text="first child", terminate=False)
        engine.dispatch("exit_table", destination="parent")
        engine.dispatch("create_table", rows=1, cols=1, header=False, cell_margin=None)
        engine.dispatch("insert_paragraph", text="second child", terminate=False)
        engine.dispatch("exit_table", destination="parent")
        xml = str(app.GetTextFile("HWPML2X", ""))
        assert ["".join(e.itertext()) for e in ET.fromstring(xml).iter("TABLE")] == [
            "first childsecond child", "first child", "second child"]
        for index, expected in enumerate(("first child", "second child")):
            number = table_index_from_hwpml(xml, {"root": 0, "children": [{"cell": "A1", "index": index}]})
            engine.dispatch("move_to_cell", table=number, cell="A1")
            canvas.select_cell_text()
            assert expected in canvas.get_selected_text()
            canvas.run("Cancel")
    finally:
        _close_without_saving(app)


@pytest.mark.parametrize("extension", ["hwp", "hwpx"])
def test_radial_text_box_margin_save_reopen_is_editable(tmp_path, extension):
    app, canvas = _new_blank_canvas()
    try:
        engine, _ = _isolated_engine(canvas)
        engine.dispatch("insert_text_box", text="Synthetic radial label", width_mm=60,
                        height_mm=25, margin=[1, 2, 3, 4],
                        fill={"type": "radial_gradient", "stops": ["#FFFFFF", "#123456"]})
        output = tmp_path / f"synthetic-radial.{extension}"
        canvas.save_as(str(output))
        canvas.close_discard()
        if int(app.XHwpDocuments.Count) == 0:
            app.XHwpDocuments.Add(False)
        canvas.open_path(str(output))
        root = ET.fromstring(str(app.GetTextFile("HWPML2X", "")))
        gradients = [e for e in root.iter() if e.tag.upper() == "GRADATION"]
        assert any(e.get("Type", "").lower() == "radial" for e in gradients)
        margins = list(root.iter("TEXTMARGIN"))
        assert margins, str(app.GetTextFile("HWPML2X", ""))
        from hwpctl.units import mm_to_hwpunit
        assert tuple(int(margins[0].get(key)) for key in ("Left", "Right", "Top", "Bottom")) == tuple(
            mm_to_hwpunit(value) for value in (1, 2, 3, 4))
        assert not list(root.iter("PICTURE"))
        assert "Synthetic radial label" in "".join(root.itertext())
        # Select the actual native text-box object, not its rendered appearance.
        ctrl = app.LastCtrl
        assert str(ctrl.CtrlID) == "gso"
        app.SetPosBySet(ctrl.GetAnchorPos(0))
        app.FindCtrl()
        assert app.HAction.Run("ShapeObjTextBoxEdit")
        canvas.insert_text("Editable ")
        assert "Editable " in str(app.GetTextFile("HWPML2X", ""))
        canvas.undo_once()
        assert "Editable " not in str(app.GetTextFile("HWPML2X", ""))
    finally:
        _close_without_saving(app)


def test_synthetic_faq_save_reopen_edit_and_undo(tmp_path, monkeypatch) -> None:
    """Owned COM only; public authoring, native table, save/reopen and edit proof."""
    from examples.rebuild_faq_002_from_normalized_spec import PublicBuild, load_spec, preflight
    from hwpctl.lock import load_state

    # Retain the global writer lock; isolate only this test's pin/Undo state.
    monkeypatch.setenv("HWPCTL_STATE", str(tmp_path / "state.json"))
    app, canvas = _new_blank_canvas()
    try:
        engine = Engine(canvas_factory=lambda **kwargs: canvas)
        spec = load_spec(Path(__file__).resolve().parents[1] / "examples/specs/faq.synthetic.json")
        output = tmp_path / "faq.hwp"
        preflight(spec, output, tmp_path / "record.json")
        PublicBuild(engine=engine, spec=spec).build(output)
        assert output.is_file() and output.stat().st_size > 0
        assert load_state().target_hwnd == canvas.window_handle()
        # Some installations retain Modified after SaveAs. Close only this owned
        # saved document, then reopen; do not bypass Engine's dirty-document guard.
        engine.dispatch("close", force=True)
        if int(app.XHwpDocuments.Count) == 0:
            app.XHwpDocuments.Add(False)
        engine.dispatch("open", path=str(output))
        root = ET.fromstring(str(app.GetTextFile("HWPML2X", "") or ""))
        tables = [e for e in root.iter() if e.tag.rsplit("}", 1)[-1].upper() == "TABLE"]
        assert len(tables) == 1
        cells = [e for e in tables[0].iter() if e.tag.rsplit("}", 1)[-1].upper() == "CELL"]
        assert len(cells) == 5  # six grid slots, one two-column merged header
        assert "표 다음 본문입니다." in canvas.get_body_text()
        engine.dispatch("set_edit_marks", control_marks=True, paragraph_marks=True)
        engine.dispatch("write_cell", table=0, cell="B2", paragraphs=[{"text": "수정 확인"}])
        assert "수정 확인" in canvas.get_body_text()
        engine.dispatch("undo")
        assert "수정 확인" not in canvas.get_body_text()
        engine.dispatch("write_cell", table=0, cell="B2", paragraphs=[{"text": "저장 후 셀 편집"}])
        engine.dispatch("move_to_cell", table=0, cell="B3")
        engine.dispatch("exit_table")
        engine.dispatch("insert_paragraph", text="저장 후 문단 편집")
        edited = tmp_path / "faq-edited.hwp"
        engine.dispatch("save_as", path=str(edited))
        assert edited.is_file() and edited.stat().st_size > 0
        engine.dispatch("close", force=True)
        if int(app.XHwpDocuments.Count) == 0:
            app.XHwpDocuments.Add(False)
        engine.dispatch("open", path=str(edited))
        assert "저장 후 셀 편집" in canvas.get_body_text()
        assert "저장 후 문단 편집" in canvas.get_body_text()
        engine.dispatch("close", force=True)
    finally:
        _close_without_saving(app)


def test_floating_table_position_survives_grid_merge_and_edit():
    """Promoted from floating-merge-probe; compare native POSITION after each step."""
    app, canvas = _new_blank_canvas()
    try:
        engine, _ = _isolated_engine(canvas)
        engine.dispatch("create_table", rows=3, cols=3, header=False)
        engine.dispatch("set_table_position", table=0, position={
            "mode": "floating", "horizontal_relative_to": "para", "vertical_relative_to": "para",
            "horizontal_align": "left", "vertical_align": "top", "x_mm": 0, "y_mm": 0,
            "wrap": "top_and_bottom", "flow_with_text": True, "allow_overlap": False,
            "outside_margin_mm": [0.5, 0.5, 0.5, 0.5],
        })
        def position():
            root = ET.fromstring(str(app.GetTextFile("HWPML2X", "")))
            table = next(e for e in root.iter() if e.tag.rsplit("}", 1)[-1].upper() == "TABLE")
            return dict(next(e for e in table.iter() if e.tag.rsplit("}", 1)[-1].upper() == "POSITION").attrib)
        expected = position()
        assert expected["TreatAsChar"].lower() == "false"
        for command, args in [
            ("set_table_grid", {"column_widths_mm": [20, 28, 25], "row_heights_mm": [10, 15, 12]}),
            ("merge_cells", {"cell_range": "A1:B1"}),
            ("set_cell_margin", {"left": 1.2, "right": 1.2, "top": 0.8, "bottom": 0.8}),
            ("write_cell", {"cell": "A1", "paragraphs": [{"text": "병합 셀"}, {"text": "두 번째 문단"}]}),
        ]:
            engine.dispatch(command, table=0, **args)
            assert position() == expected, command
    finally:
        _close_without_saving(app)


@pytest.mark.parametrize("orientation,landscape", [("portrait", False), ("landscape", True)])
def test_hwpx_writer_orientation_and_edit_in_hangul(tmp_path, orientation, landscape):
    from hwpctl.hwpx import new_document, set_page_setup, create_table_and_fill, save_document
    doc = new_document()
    output = tmp_path / f"{orientation}.hwpx"
    try:
        set_page_setup(doc, paper_size="A4", orientation=orientation)
        create_table_and_fill(doc, 1, 2, [["합성", "표"]], column_widths_mm=[35, 65])
        save_document(doc, output)
    finally:
        doc.close()
    app, canvas = _new_blank_canvas()
    try:
        canvas.open_path(str(output))
        root = ET.fromstring(str(app.GetTextFile("HWPML2X", "")))
        page = next(e for e in root.iter() if e.tag.rsplit("}", 1)[-1].upper() == "PAGEDEF")
        assert (page.attrib["Landscape"].lower() in {"true", "1"}) == landscape
        engine, _ = _isolated_engine(canvas)
        engine.dispatch("write_cell", table=0, cell="B1", paragraphs=[{"text": "편집 확인"}])
        assert "편집 확인" in canvas.get_body_text()
    finally:
        _close_without_saving(app)


def test_grid_fractional_mm_roundtrip_precision():
    """Reduced synthetic case from grid_precision_live_probe, no source geometry."""
    app, canvas = _new_blank_canvas()
    try:
        engine, _ = _isolated_engine(canvas)
        engine.dispatch("create_table", rows=2, cols=3, header=False)
        widths, heights = [21.013, 32.027, 43.041], [12.017, 15.029]
        engine.dispatch("set_table_grid", table=0, column_widths_mm=widths, row_heights_mm=heights)
        root = ET.fromstring(str(app.GetTextFile("HWPML2X", "")))
        table = next(e for e in root.iter() if e.tag.rsplit("}", 1)[-1].upper() == "TABLE")
        cells = [e for e in table.iter() if e.tag.rsplit("}", 1)[-1].upper() == "CELL"]
        assert len(cells) == 6
        for cell in cells:
            row, col = int(cell.attrib["RowAddr"]), int(cell.attrib["ColAddr"])
            assert abs(int(cell.attrib["Width"]) - round(widths[col] * 7200 / 25.4)) <= 1
            assert abs(int(cell.attrib["Height"]) - round(heights[row] * 7200 / 25.4)) <= 1
    finally:
        _close_without_saving(app)


def _exercise_readonly_exports_of_owned_synthetic_document(tmp_path):
    """Exercise actual SaveAs PDF and capture lifetime, never user reference files."""
    from hwpctl.reference import export_hwpml_readonly, export_pdf_readonly, export_reference_bundle_readonly
    from hwpctl.reference.capture import _default_dispatch
    import win32gui
    import time
    owned_handles = []
    def observed_dispatch(prog_id):
        created = _default_dispatch(prog_id)
        try:
            owned_handles.append(int(created.XHwpWindows.Item(0).WindowHandle))
        except Exception:
            _close_without_saving(created)
            raise
        return created
    source = tmp_path / "synthetic-reference.hwp"
    # Tiny synthetic RGB PNG generated entirely in the test (no private assets).
    import struct
    import zlib
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    picture = tmp_path / "synthetic.png"
    picture.write_bytes(b"\x89PNG\r\n\x1a\n" +
                        chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)) +
                        chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\xff\x00\x00" * 2)) + chunk(b"IEND", b""))
    app, canvas = _new_blank_canvas()
    try:
        owned_handles.append(int(app.XHwpWindows.Item(0).WindowHandle))
        engine, _ = _isolated_engine(canvas)
        engine.dispatch("insert_paragraph", text="합성 참조 내보내기")
        engine.dispatch("insert_image", path=str(picture), size_option=1, width_mm=5, height_mm=5)
        engine.dispatch("create_table", rows=1, cols=2, header=False)
        engine.dispatch("write_cell", table=0, cell="A1", paragraphs=[{"text": "실제 표"}])
        engine.dispatch("save_as", path=str(source))
    finally:
        engine = None
        canvas = None
        _close_without_saving(app)
        # Release the creator's root proxy before a new DispatchEx session.
        # Retaining it until function exit can release a dead server proxy after
        # subsequent export sessions, producing an unraised native RPC diagnostic.
        app = None
    before = source.read_bytes()
    xml_path, pdf_path = tmp_path / "capture.hwpml", tmp_path / "capture.pdf"
    assert export_hwpml_readonly(source, xml_path, _dispatch=observed_dispatch)["source_unchanged"]
    assert export_pdf_readonly(source, pdf_path, _dispatch=observed_dispatch)["source_unchanged"]
    bundle = export_reference_bundle_readonly(source, tmp_path / "bundle", _dispatch=observed_dispatch)
    assert bundle["source_unchanged"] and bundle["assets_complete"]
    assert len(bundle["assets"]) == 1 and bundle["assets"][0]["extracted"]
    root = ET.parse(xml_path).getroot()
    assert any(e.tag.rsplit("}", 1)[-1] == "TABLE" for e in root.iter())
    assert pdf_path.read_bytes().startswith(b"%PDF-")
    assert source.read_bytes() == before
    assert len(owned_handles) == 4 and all(owned_handles)
    deadline = time.monotonic() + 3
    while any(win32gui.IsWindow(handle) for handle in owned_handles) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not any(win32gui.IsWindow(handle) for handle in owned_handles), "Owned window remained open"


def test_readonly_exports_of_owned_synthetic_document(tmp_path):
    """Native diagnostics must fail even when COM/pytest returns exit code zero.

    Run three complete create/export/close cycles in ONE fresh child interpreter.
    Capturing stderr here observes diagnostics; it does not suppress their failure.
    """
    import subprocess
    script = r'''
import faulthandler
import gc
from pathlib import Path
import runpy
import sys
faulthandler.enable()
exercise = runpy.run_path(sys.argv[1])["_exercise_readonly_exports_of_owned_synthetic_document"]
for trial in range(3):
    folder = Path(sys.argv[2]) / str(trial)
    folder.mkdir()
    exercise(folder)
    gc.collect()
    print("CLEAN_CYCLE", trial, flush=True)
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(Path(__file__).resolve()), str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    diagnostics = result.stdout + result.stderr
    assert result.returncode == 0, diagnostics
    assert "windows fatal exception" not in diagnostics.lower(), diagnostics
    assert "0x800706ba" not in diagnostics.lower(), diagnostics
    assert result.stdout.count("CLEAN_CYCLE") == 3, diagnostics
