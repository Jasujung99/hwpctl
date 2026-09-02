"""한/글 2022 실기 회귀 테스트.

기본 pytest/CI에서는 실행하지 않는다. ``HWPCTL_RUN_HANGUL_INTEGRATION=1``을 명시한
Windows 한/글 2022 환경에서만 DispatchEx로 별도 빈 문서를 만들고 저장 없이 닫는다.
사용자가 열어 둔 문서·참조본·구현본은 대상이 아니다.
"""

from __future__ import annotations

import os
import sys
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
