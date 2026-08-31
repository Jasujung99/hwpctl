"""win32com 폴백 경로 단위 테스트 (한/글 없이 스텁 COM 객체로).

핵심 회귀: goto_addr 의 이동 액션이 실패했는데도 조용히 넘어가
SelectAll 이 문서 전체를 선택 → insert_text 가 문서를 통째로 덮어쓰는 사고 경로.
"""

from __future__ import annotations

import pytest

from hwpctl.errors import HangulCommandError
from hwpctl.hangul import HangulCanvas


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

    def CreateAction(self, name: str):
        assert name == "InsertChart"
        return self.chart_action


def make_canvas(com: StubCom) -> HangulCanvas:
    return HangulCanvas(px=None, com=com, backend="win32com")


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


def test_table_inside_margin_com_items() -> None:
    com = StubCom()
    make_canvas(com).set_table_inside_margin(3.5, 3.5, 2.0, 2.0)
    pset = com.HParameterSet.HShapeObject
    assert pset.items["CellMarginLeft"] == com.MiliToHwpUnit(3.5)
    assert pset.items["CellMarginTop"] == com.MiliToHwpUnit(2.0)
    assert "TablePropertyDialog" in com.HAction.executed


def test_table_inside_margin_requires_cell() -> None:
    com = StubCom(cur_field_state=0)
    with pytest.raises(HangulCommandError) as exc:
        make_canvas(com).set_table_inside_margin(3.5, 3.5, 2.0, 2.0)
    assert "표 안" in exc.value.message


def test_cell_margin_current_com_items() -> None:
    com = StubCom()
    make_canvas(com).set_cell_margin_current(4.0, 4.0, 1.5, 1.5)
    pset = com.HParameterSet.HShapeObject
    cell = pset.ShapeTableCell
    assert pset.HSet.items["ShapeType"] == 3
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
