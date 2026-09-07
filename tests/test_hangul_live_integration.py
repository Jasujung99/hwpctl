"""한/글 2022 실기 회귀 테스트.

기본 pytest/CI에서는 실행하지 않는다. ``HWPCTL_RUN_HANGUL_INTEGRATION=1``을 명시한
Windows 한/글 2022 환경에서만 DispatchEx로 별도 빈 문서를 만들고 저장 없이 닫는다.
사용자가 열어 둔 문서·참조본·구현본은 대상이 아니다.
"""

from __future__ import annotations

import os
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
