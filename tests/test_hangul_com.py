"""win32com 폴백 경로 단위 테스트 (한/글 없이 스텁 COM 객체로).

핵심 회귀: goto_addr 의 이동 액션이 실패했는데도 조용히 넘어가
SelectAll 이 문서 전체를 선택 → insert_text 가 문서를 통째로 덮어쓰는 사고 경로.
"""

from __future__ import annotations

import pytest

from hwpctl.errors import HangulCommandError
from hwpctl.hangul import (
    HangulCanvas,
    _com_has_hwnd,
    _iter_window_handles,
    _show_window,
    _window_handle_of,
)


class StubHAction:
    def __init__(self, fail: set[str] | None = None, execute_ok: bool = True) -> None:
        self.fail = fail or set()
        self.calls: list[str] = []
        self.executed: list[str] = []
        self.execute_ok = execute_ok

    def Run(self, act_id: str) -> bool:
        self.calls.append(act_id)
        return act_id not in self.fail

    def GetDefault(self, name: str, hset) -> None:
        self.calls.append(f"GetDefault:{name}")

    def Execute(self, name: str, hset) -> bool:
        self.executed.append(name)
        return self.execute_ok


class RecordingAttrs:
    """COM 파라미터셋 하위 객체 흉내 — 대입된 속성을 items 에 기록."""

    def __init__(self) -> None:
        object.__setattr__(self, "items", {})

    def __setattr__(self, key, value) -> None:
        self.items[key] = value

    def __getattr__(self, key):
        try:
            return self.items[key]
        except KeyError as exc:
            raise AttributeError(key) from exc


class RecordingHSet:
    def __init__(self) -> None:
        self.items = {}

    def SetItem(self, key, value) -> None:
        self.items[key] = value


class RecordingPSet:
    def __init__(self) -> None:
        object.__setattr__(self, "items", {})
        object.__setattr__(self, "HSet", RecordingHSet())
        object.__setattr__(self, "FillAttr", RecordingAttrs())
        object.__setattr__(self, "ShapeTableCell", RecordingAttrs())
        object.__setattr__(self, "PageDef", RecordingAttrs())
        self.ShapeTableCell.Width = 1000
        self.ShapeTableCell.Height = 500

    def __setattr__(self, key, value) -> None:
        self.items[key] = value


class StubChartAction:
    def __init__(self, execute_ok: bool = True) -> None:
        self.execute_ok = execute_ok
        self.hset = RecordingHSet()
        self.executed = 0

    def CreateSet(self):
        return self.hset

    def GetDefault(self, hset) -> None:
        pass

    def Execute(self, hset) -> bool:
        self.executed += 1
        return self.execute_ok


class StubPSetNamespace:
    def __init__(self) -> None:
        self.HParaShape = RecordingPSet()
        self.HCellBorderFill = RecordingPSet()
        self.HShapeObject = RecordingPSet()
        self.HSecDef = RecordingPSet()
        self.HStyle = RecordingPSet()


class StubCom:
    def __init__(
        self,
        fail: set[str] | None = None,
        cur_field_state: int = 1,
        cell_addr: str = "",
        execute_ok: bool = True,
        chart_ok: bool = True,
    ) -> None:
        self.HAction = StubHAction(fail, execute_ok=execute_ok)
        self.HParameterSet = StubPSetNamespace()
        self.CurFieldState = cur_field_state
        self._cell_addr = cell_addr
        self.chart_action = StubChartAction(execute_ok=chart_ok)

    def KeyIndicator(self):
        # (succ, seccnt, secno, prnpageno, colno, line, pos, over, ctrlname)
        return (1, 1, 1, 1, 1, 1, 1, 0, f"({self._cell_addr})" if self._cell_addr else "")

    def GetSelectedPos(self):
        return (False, 0, 0, 0, 0, 0, 0)

    def HAlign(self, name: str) -> int:
        return {"Justify": 0, "Left": 1, "Center": 2, "Right": 3}[name]

    def BrushType(self, name: str) -> int:
        return 7

    def HatchStyle(self, name: str) -> int:
        return 0

    def RGBColor(self, r: int, g: int, b: int) -> int:
        return r | (g << 8) | (b << 16)

    def MiliToHwpUnit(self, mm: float) -> int:
        return int(round(mm * 7200 / 25.4))

    def HwpUnitToMili(self, value: int) -> float:
        return value * 25.4 / 7200

    def HwpLineType(self, name: str) -> int:
        assert name == "Solid"
        return 1

    def HwpLineWidth(self, width: str) -> int:
        assert width == "0.12mm"
        return 2

    def CreateAction(self, name: str):
        assert name == "InsertChart"
        return self.chart_action


def make_canvas(com: StubCom) -> HangulCanvas:
    return HangulCanvas(px=None, com=com, backend="win32com")


class StubWindow:
    def __init__(self, handle: int, visible: bool = False) -> None:
        self.WindowHandle = handle
        self.Visible = visible


class StubWindows:
    def __init__(self, handles: list[int], active_index: int = -1) -> None:
        self._items = [StubWindow(h) for h in handles]
        self.Count = len(self._items)
        self._active_index = active_index if active_index >= 0 else len(self._items) - 1

    def Item(self, i: int) -> StubWindow:
        return self._items[i]

    @property
    def Active_XHwpWindow(self) -> StubWindow:
        return self._items[self._active_index]


class StubComWindows:
    def __init__(self, handles: list[int], active_index: int = -1) -> None:
        self.XHwpWindows = StubWindows(handles, active_index)


def test_goto_addr_raises_when_nav_action_fails() -> None:
    """이동 액션이 False 를 리턴하면 예외. (과거: 무시하고 진행 → 본문에서 SelectAll)"""
    com = StubCom(fail={"TableColBegin"}, cell_addr="B2")
    canvas = make_canvas(com)
    with pytest.raises(HangulCommandError):
        canvas.goto_addr("B2")
    # 실패 이후 셀 내용 선택(SelectAll)으로 이어지면 안 된다
    assert "SelectAll" not in com.HAction.calls


def test_goto_addr_raises_outside_table() -> None:
    com = StubCom(cur_field_state=0)
    canvas = make_canvas(com)
    with pytest.raises(HangulCommandError) as exc:
        canvas.goto_addr("A1")
    assert "표 안" in exc.value.message
    assert com.HAction.calls == []


def test_goto_addr_verifies_result_address() -> None:
    """이동은 성공 코드를 리턴했지만 KeyIndicator 주소가 다르면(줄바꿈 랩 등) 예외."""
    com = StubCom(cell_addr="A1")  # 항상 A1 에 머무는 표
    canvas = make_canvas(com)
    with pytest.raises(HangulCommandError) as exc:
        canvas.goto_addr("B2")
    assert "셀 이동 결과" in exc.value.message


def test_goto_addr_success_path_uses_verified_actions() -> None:
    com = StubCom(cell_addr="B2")
    canvas = make_canvas(com)
    canvas.goto_addr("B2")
    calls = com.HAction.calls
    assert "TableColBegin" in calls
    assert "TableColPageUp" in calls  # 과거의 미확인 액션 "TableRowBegin" 금지
    assert "TableRowBegin" not in calls
    assert calls.count("TableRightCell") == 1
    assert calls.count("TableLowerCell") == 1


def test_select_cell_text_refuses_outside_cell() -> None:
    """캐럿이 본문에 있으면 SelectAll(문서 전체 선택)을 절대 실행하지 않는다."""
    com = StubCom(cur_field_state=0)
    canvas = make_canvas(com)
    with pytest.raises(HangulCommandError):
        canvas.select_cell_text()
    assert "SelectAll" not in com.HAction.calls


def test_select_cell_text_ok_in_cell_and_cell_field() -> None:
    for state in (1, 17):  # 셀 = 1, 셀필드 = 17 (CurFieldState 문서)
        com = StubCom(cur_field_state=state)
        canvas = make_canvas(com)
        canvas.select_cell_text()
        assert com.HAction.calls == ["SelectAll"]


def test_has_selection_uses_is_block_flag() -> None:
    canvas = make_canvas(StubCom())
    assert canvas.has_selection() is False

    class SelectedCom(StubCom):
        def GetSelectedPos(self):
            return (True, 0, 0, 0, 0, 0, 5)

    canvas2 = make_canvas(SelectedCom())
    assert canvas2.has_selection() is True


def test_current_cell_addr_parses_key_indicator() -> None:
    canvas = make_canvas(StubCom(cell_addr="C3"))
    assert canvas.current_cell_addr() == "C3"
    assert make_canvas(StubCom()).current_cell_addr() == ""


def test_set_align_uses_halign_enum_not_string() -> None:
    """회귀 방지(#6): AlignType 에는 문자열이 아니라 HAlign 변환 정수가 들어가야 한다."""
    com = StubCom()
    make_canvas(com).set_align("center")
    pset = com.HParameterSet.HParaShape
    assert pset.items["AlignType"] == 2  # HAlign("Center")
    assert "ParagraphShape" in com.HAction.executed


def test_set_align_raises_korean_on_failure() -> None:
    com = StubCom(execute_ok=False)
    with pytest.raises(HangulCommandError) as exc:
        make_canvas(com).set_align("center")
    assert "정렬" in exc.value.message


def test_cell_fill_uses_winbrush_items() -> None:
    """회귀 방지(#7): WinBrushFaceColor 등 실제 아이템 이름을 써야 한다."""
    com = StubCom()
    make_canvas(com).cell_fill("gray")
    fill = com.HParameterSet.HCellBorderFill.FillAttr
    assert fill.items["WinBrushFaceColor"] == com.RGBColor(217, 217, 217)
    assert fill.items["WindowsBrush"] == 1
    assert fill.items["type"] == 7  # BrushType("NullBrush|WinBrush")
    assert "CellFill" in com.HAction.executed
    assert "Cancel" in com.HAction.calls  # 선택 해제


def test_cell_fill_raises_korean_when_execute_false() -> None:
    com = StubCom(execute_ok=False)
    with pytest.raises(HangulCommandError) as exc:
        make_canvas(com).cell_fill("gray")
    assert "셀 배경" in exc.value.message


def test_table_inside_margin_is_explicitly_unsupported() -> None:
    com = StubCom()
    with pytest.raises(HangulCommandError) as exc:
        make_canvas(com).set_table_inside_margin(3.5, 3.5, 2.0, 2.0)
    assert "값이 바뀌지 않습니다" in exc.value.message
    assert "TablePropertyDialog" not in com.HAction.executed


def test_cell_margin_current_com_items() -> None:
    com = StubCom()
    make_canvas(com).set_cell_margin_current(4.0, 4.0, 1.5, 1.5)
    pset = com.HParameterSet.HShapeObject
    cell = pset.ShapeTableCell
    assert pset.HSet.items["ShapeType"] == 3
    assert pset.HSet.items["ShapeCellSize"] == 0
    assert cell.items["HasMargin"] == 1
    assert cell.items["MarginLeft"] == com.MiliToHwpUnit(4.0)
    assert cell.items["MarginBottom"] == com.MiliToHwpUnit(1.5)


def test_insert_chart_sets_dialog_disable_and_group() -> None:
    """차트: InsertChart 파라미터 3종 (포럼 1649 확인) 이 정확히 설정돼야 한다."""
    com = StubCom()
    make_canvas(com).insert_chart(chart_group=2, chart_index=0, dialog_disable=True)
    items = com.chart_action.hset.items
    assert items["ChartGroup"] == 2
    assert items["ChartIndex"] == 0
    assert items["ChartDataDialogDisable"] == 1
    assert com.chart_action.executed == 1


def test_insert_chart_failure_mentions_dialog() -> None:
    com = StubCom(chart_ok=False)
    with pytest.raises(HangulCommandError) as exc:
        make_canvas(com).insert_chart(chart_group=2)
    assert "대화상자" in exc.value.message


def test_select_all_cells_sequence_and_guard() -> None:
    com = StubCom()
    make_canvas(com).select_all_cells()
    assert com.HAction.calls[:2] == ["TableCellBlockExtendAbs", "TableCellBlockExtend"]
    out = StubCom(cur_field_state=0)
    with pytest.raises(HangulCommandError):
        make_canvas(out).select_all_cells()


def test_select_cell_range_checked_moves() -> None:
    com = StubCom(cell_addr="A1")
    make_canvas(com).select_cell_range("A1", "B3")
    calls = com.HAction.calls
    assert "TableCellBlock" in calls
    assert calls.count("TableRightCell") == 1
    assert calls.count("TableLowerCell") == 2
    bad = StubCom(cell_addr="A1", fail={"TableCellBlock"})
    with pytest.raises(HangulCommandError):
        make_canvas(bad).select_cell_range("A1", "B3")


<<<<<<< HEAD
def test_col_width_uses_table_property_dialog_and_not_getcellwidth() -> None:
    com = StubCom()
    canvas = make_canvas(com)
    assert canvas.get_col_width() == pytest.approx(1000 * 25.4 / 7200)
    assert "GetDefault:TablePropertyDialog" in com.HAction.calls
    assert not hasattr(com, "GetCellWidth")

    com.HAction.calls.clear()
    canvas.set_col_width_current(30)
    assert com.HAction.calls[:4] == [
        "TableColPageUp",
        "TableCellBlock",
        "TableCellBlockExtend",
        "TableColPageDown",
    ]
    pset = com.HParameterSet.HShapeObject
    assert pset.HSet.items["ShapeCellSize"] == 1
    assert pset.ShapeTableCell.items["Width"] == com.MiliToHwpUnit(30)
    assert "TablePropertyDialog" in com.HAction.executed


def test_row_height_uses_shape_cell_size_and_reads_default() -> None:
    com = StubCom()
    canvas = make_canvas(com)
    assert canvas.get_row_height() == pytest.approx(500 * 25.4 / 7200)
    canvas.set_row_height_current(12)
    pset = com.HParameterSet.HShapeObject
    assert pset.HSet.items["ShapeCellSize"] == 1
    assert pset.ShapeTableCell.items["Height"] == com.MiliToHwpUnit(12)


def test_merge_cells_uses_verified_block_sequence() -> None:
    com = StubCom(cell_addr="A1")
    make_canvas(com).merge_cells("A1", "B2")
    calls = com.HAction.calls
    block = calls.index("TableCellBlock")
    extend = calls.index("TableCellBlockExtend")
    right = calls.index("TableRightCell")
    lower = calls.index("TableLowerCell")
    merge = calls.index("TableMergeCell")
    assert block < extend < right < lower < merge

    bad = StubCom(cell_addr="A1", fail={"TableCellBlockExtend"})
    with pytest.raises(HangulCommandError):
        make_canvas(bad).merge_cells("A1", "B2")
    assert "TableMergeCell" not in bad.HAction.calls


@pytest.mark.parametrize(
    ("align", "action", "value"),
    [
        ("top", "TableVAlignTop", 0),
        ("center", "TableVAlignCenter", 1),
        ("bottom", "TableVAlignBottom", 2),
    ],
)
def test_set_valign_uses_verified_actions(align: str, action: str, value: int) -> None:
    com = StubCom()
    assert make_canvas(com).set_valign_current(align) == value
    assert action in com.HAction.calls


def test_cell_border_uses_cellborderfill_and_left_color_typo() -> None:
    com = StubCom()
    make_canvas(com).set_cell_border_current(
        sides=["left", "right"],
        line_type="Solid",
        width="0.12mm",
        color="#112233",
    )
    pset = com.HParameterSet.HCellBorderFill
    assert pset.items["BorderTypeLeft"] == 1
    assert pset.items["BorderWidthLeft"] == 2
    assert pset.items["BorderCorlorLeft"] == com.RGBColor(17, 34, 51)
    assert "BorderColorLeft" not in pset.items
    assert pset.items["BorderColorRight"] == com.RGBColor(17, 34, 51)
    assert "CellBorderFill" in com.HAction.executed


def test_cell_border_rejects_type_horz() -> None:
    with pytest.raises(Exception) as exc:
        make_canvas(StubCom()).set_cell_border_current(
            sides=["horizontal"],
            line_type="Solid",
            width="0.12mm",
            color="#000000",
        )
    assert "TypeHorz" in str(exc.value)


def test_pagedef_and_break_page_use_verified_actions() -> None:
    com = StubCom()
    canvas = make_canvas(com)
    canvas.set_pagedef(
        paper_width=210,
        paper_height=297,
        left=20,
        right=20,
        landscape=True,
        apply="all",
    )
    pset = com.HParameterSet.HSecDef
    assert pset.PageDef.items["PaperWidth"] == com.MiliToHwpUnit(210)
    assert pset.PageDef.items["LeftMargin"] == com.MiliToHwpUnit(20)
    assert pset.PageDef.items["Landscape"] == 1
    assert pset.HSet.items["ApplyTo"] == 3
    assert "PageSetup" in com.HAction.executed
    canvas.break_page()
    assert "BreakPage" in com.HAction.calls


def test_named_style_calls_pyhwpx_set_style_only() -> None:
    class StubPx:
        def __init__(self) -> None:
            self.styles = []

        def set_style(self, style):
            self.styles.append(style)
            return True

    px = StubPx()
    canvas = HangulCanvas(px=px, com=StubCom(), backend="pyhwpx")
    canvas.set_style("개요 1")
    assert px.styles == ["개요 1"]


def test_window_handle_uses_active_not_item0() -> None:
    """회귀: Item(0) 은 처음 연 창(이미 열린 파일). open --new 후 고정은 활성 창."""
    com = StubComWindows([855126, 3738628], active_index=1)
    canvas = HangulCanvas(px=None, com=com, backend="win32com")
    assert canvas.window_handle() == 3738628
    assert _window_handle_of(com) == 3738628
    # Item(0) 만 보면 이전 창이 나온다 — 그걸 쓰면 안 된다
    assert com.XHwpWindows.Item(0).WindowHandle == 855126


def test_window_handle_falls_back_to_item0_without_active() -> None:
    class FirstOnly:
        class Wins:
            def Item(self, i):
                assert i == 0
                return StubWindow(1111)

        XHwpWindows = Wins()

    assert _window_handle_of(FirstOnly()) == 1111
    assert _window_handle_of(object()) == 0


def test_window_handle_never_item0_when_count_gt1_and_no_active() -> None:
    """라이브: Active 속성이 없으면 Item 을 훑고, Count>1 일 때 Item(0) 금지."""

    class NoActiveWindows:
        def __init__(self) -> None:
            self._items = [StubWindow(855126, visible=True), StubWindow(3738628, visible=True)]
            self.Count = 2

        def Item(self, i: int) -> StubWindow:
            return self._items[i]

        @property
        def Active_XHwpWindow(self):
            raise AttributeError("Active_XHwpWindow")

    com = type("C", (), {"XHwpWindows": NoActiveWindows()})()
    assert _window_handle_of(com) == 3738628
    assert com.XHwpWindows.Item(0).WindowHandle == 855126


def test_iter_and_has_hwnd_covers_all_windows() -> None:
    com = StubComWindows([855126, 3738628], active_index=1)
    assert list(_iter_window_handles(com)) == [3738628, 855126]
    assert _com_has_hwnd(com, 3738628) is True
    assert _com_has_hwnd(com, 855126) is True
    assert _com_has_hwnd(com, 1) is False
    assert _com_has_hwnd(com, 0) is False


def test_show_window_sets_matching_handle_visible() -> None:
    com = StubComWindows([855126, 3738628], active_index=1)
    _show_window(com, 3738628)
    assert com.XHwpWindows.Item(1).Visible is True
    assert com.XHwpWindows.Item(0).Visible is False
    _show_window(com, 855126)
    assert com.XHwpWindows.Item(0).Visible is True
