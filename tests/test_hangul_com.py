"""win32com 폴백 경로 단위 테스트 (한/글 없이 스텁 COM 객체로).

핵심 회귀: goto_addr 의 이동 액션이 실패했는데도 조용히 넘어가
SelectAll 이 문서 전체를 선택 → insert_text 가 문서를 통째로 덮어쓰는 사고 경로.
"""

from __future__ import annotations

import pytest

import hwpctl.hangul as hangul
from hwpctl.errors import HangulCommandError, UsageError
from hwpctl.hangul import (
    HangulCanvas,
    _com_has_hwnd,
    _document_records_from_com,
    _ensure_document_if_empty,
    _iter_window_handles,
    _make_window_current,
    _pick_com_by_hwnd,
    _show_window,
    _window_handle_of,
    close_all_open_documents_discard,
    list_open_documents,
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


class RecordingItemArray:
    """HParameterSet.CreateItemArray 반환값의 최소 테스트 더블."""

    def __init__(self, length: int) -> None:
        self.items: list[int | None] = [None] * length

    def SetItem(self, index: int, value: int) -> None:
        self.items[index] = value


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

    def CreateItemSet(self, name: str, _type_name: str) -> "RecordingPSet":
        child = RecordingPSet()
        self.items[name] = child
        return child

    def CreateItemArray(self, name: str, length: int) -> RecordingItemArray:
        array = RecordingItemArray(length)
        self.items[name] = array
        return array


class StubDrawAction:
    """CellFill/도형 계열 CreateAction의 ParameterSet 경로를 기록한다."""

    def __init__(self, execute_ok: bool = True) -> None:
        self.execute_ok = execute_ok
        self.hset = RecordingPSet()
        self.defaults = 0
        self.executed = 0

    def CreateSet(self) -> RecordingPSet:
        return self.hset

    def GetDefault(self, _pset) -> None:
        self.defaults += 1

    def Execute(self, _pset) -> bool:
        self.executed += 1
        return self.execute_ok


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
        self.HCharShape = RecordingPSet()
        self.HParaShape = RecordingPSet()
        self.HCellBorderFill = RecordingPSet()
        self.HShapeObject = RecordingPSet()
        self.HSecDef = RecordingPSet()
        self.HStyle = RecordingPSet()
        self.HPageNumPos = RecordingPSet()
        self.HPageHiding = RecordingPSet()


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
        self.cell_fill_action = StubDrawAction(execute_ok=execute_ok)
        self.new_number_action = StubDrawAction(execute_ok=execute_ok)

    def KeyIndicator(self):
        # (succ, seccnt, secno, prnpageno, colno, line, pos, over, ctrlname)
        return (1, 1, 1, 1, 1, 1, 1, 0, f"({self._cell_addr})" if self._cell_addr else "")

    def GetSelectedPos(self):
        return (False, 0, 0, 0, 0, 0, 0)

    def HAlign(self, name: str) -> int:
        return {"Justify": 0, "Left": 1, "Center": 2, "Right": 3}[name]

    def PageNumPosition(self, name: str) -> int:
        return {
            "TopLeft": 0,
            "TopCenter": 1,
            "TopRight": 2,
            "BottomLeft": 3,
            "BottomCenter": 4,
            "BottomRight": 5,
        }[name]

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

    def HwpUnderlineType(self, name: str) -> int:
        return {"None": 0, "Bottom": 1}[name]

    def HwpUnderlineShape(self, name: str) -> int:
        assert name == "Solid"
        return 1

    def HwpStrikeOutType(self, name: str) -> int:
        return {"None": 0, "Continuous": 1}[name]

    def HwpStrikeOutShape(self, name: str) -> int:
        assert name == "Solid"
        return 1

    def CreateAction(self, name: str):
        if name == "InsertChart":
            return self.chart_action
        if name == "CellFill":
            return self.cell_fill_action
        assert name == "NewNumber"
        return self.new_number_action


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


class StubDocument:
    def __init__(self) -> None:
        self.activated = False

    def SetActive_XHwpDocument(self) -> None:
        self.activated = True


class StubDocuments:
    def __init__(self, n: int) -> None:
        self._items = [StubDocument() for _ in range(n)]
        self.Count = n

    def Item(self, i: int) -> StubDocument:
        return self._items[i]


def test_close_discard_closes_only_active_document() -> None:
    class ActiveDocument:
        def __init__(self) -> None:
            self.close_calls: list[bool] = []

        def Close(self, discard: bool) -> bool:
            self.close_calls.append(discard)
            return True

    class Documents:
        def __init__(self) -> None:
            self.Active_XHwpDocument = ActiveDocument()
            self.collection_close_called = False

        def Close(self, discard: bool) -> None:
            self.collection_close_called = True
            raise AssertionError("collection-wide close must never be used")

    class Com:
        def __init__(self) -> None:
            self.XHwpDocuments = Documents()

    com = Com()
    HangulCanvas(px=None, com=com, backend="win32com").close_discard()

    assert com.XHwpDocuments.Active_XHwpDocument.close_calls == [False]
    assert com.XHwpDocuments.collection_close_called is False


def test_close_discard_refuses_when_document_level_close_is_unavailable() -> None:
    class Documents:
        Active_XHwpDocument = object()

    class Com:
        XHwpDocuments = Documents()

    with pytest.raises(HangulCommandError, match="문서 단위 닫기"):
        HangulCanvas(px=None, com=Com(), backend="win32com").close_discard()


def test_close_all_open_documents_uses_reverse_document_level_close(monkeypatch) -> None:
    class Document:
        def __init__(self, index: int, calls: list[int]) -> None:
            self.index = index
            self.FullName = f"C:/tmp/{index}.hwp"
            self.Modified = index % 2
            self.calls = calls

        def Close(self, discard: bool) -> bool:
            assert discard is False
            self.calls.append(self.index)
            return True

    class Documents:
        def __init__(self) -> None:
            self.calls: list[int] = []
            self.items = [Document(index, self.calls) for index in range(3)]

        @property
        def Count(self) -> int:
            return len(self.items)

        def Item(self, index: int):
            return self.items[index]

        def Close(self, _discard: bool) -> None:
            raise AssertionError("collection-wide close must never be used")

    class Com:
        def __init__(self) -> None:
            self.XHwpDocuments = Documents()
            self.quit_calls = 0

        def Quit(self):
            self.quit_calls += 1
            return True

    com = Com()
    monkeypatch.setattr(hangul, "require_windows", lambda: None)
    monkeypatch.setattr(
        hangul,
        "_iter_running_hwp_com_instances",
        lambda: iter([("!HwpObject.120.5", com)]),
    )

    out = close_all_open_documents_discard()
    assert out["failures"] == []
    assert com.XHwpDocuments.calls == [2, 1, 0]
    assert [entry["document_index"] for entry in out["closed"]] == [2, 1, 0]
    assert out["closed_instances"] == ["!HwpObject.120.5"]
    assert com.quit_calls == 1


class StubComWindows:
    def __init__(self, handles: list[int], active_index: int = -1) -> None:
        self.XHwpWindows = StubWindows(handles, active_index)
        self.XHwpDocuments = StubDocuments(len(handles))


def test_document_records_are_read_without_activating_another_document(monkeypatch) -> None:
    class Document:
        def __init__(self, full_name: str, modified: int) -> None:
            self.FullName = full_name
            self.Modified = modified
            self.activation_calls = 0

        def SetActive_XHwpDocument(self) -> None:
            self.activation_calls += 1

    class Documents:
        def __init__(self, items) -> None:
            self._items = items
            self.Count = len(items)

        def Item(self, index: int):
            return self._items[index]

    class Windows:
        def __init__(self, items, active_index: int) -> None:
            self._items = items
            self.Count = len(items)
            self._active_index = active_index

        def Item(self, index: int):
            return self._items[index]

        @property
        def Active_XHwpWindow(self):
            return self._items[self._active_index]

    first = Document(r"C:\docs\saved.hwp", 0)
    second = Document("", 2)
    first_window = StubWindow(101, visible=True)
    second_window = StubWindow(202, visible=True)

    class Com:
        XHwpDocuments = Documents([first, second])
        XHwpWindows = Windows([first_window, second_window], active_index=1)
        PageCount = 5

    monkeypatch.setattr(
        hangul,
        "_native_window_metadata",
        lambda hwnd: (f"문서-{hwnd}", hwnd + 1000),
    )
    records = _document_records_from_com("!HwpObject.120.9", Com())

    assert records == [
        {
            "instance": "!HwpObject.120.9",
            "document_index": 0,
            "window_handle": 101,
            "window_title": "문서-101",
            "pid": 1101,
            "path": r"C:\docs\saved.hwp",
            "unsaved": False,
            "modified": False,
            "page_count": None,
            "active": False,
            "visible": True,
        },
        {
            "instance": "!HwpObject.120.9",
            "document_index": 1,
            "window_handle": 202,
            "window_title": "문서-202",
            "pid": 1202,
            "path": "",
            "unsaved": True,
            "modified": True,
            "page_count": 5,
            "active": True,
            "visible": True,
        },
    ]
    # 페이지 수를 얻으려고 비활성 문서를 활성화하지 않는다.
    assert first.activation_calls == 0
    assert second.activation_calls == 0


def test_list_open_documents_uses_global_rot_lister_without_connect(monkeypatch) -> None:
    class Document:
        FullName = ""
        Modified = 2

    class Collection:
        Count = 1

        def Item(self, index: int):
            assert index == 0
            return Document()

    class Windows:
        Count = 1

        def __init__(self) -> None:
            self.window = StubWindow(303, visible=True)

        def Item(self, index: int):
            assert index == 0
            return self.window

        @property
        def Active_XHwpWindow(self):
            return self.window

    class Com:
        XHwpDocuments = Collection()
        XHwpWindows = Windows()
        PageCount = 3

    monkeypatch.setattr(hangul.sys, "platform", "win32")
    monkeypatch.setattr(
        hangul,
        "_iter_running_hwp_com_instances",
        lambda: iter([("!HwpObject.120.3", Com())]),
    )
    monkeypatch.setattr(hangul, "_native_window_metadata", lambda hwnd: ("빈 문서 1 - 한글", 33))

    assert list_open_documents() == [
        {
            "instance": "!HwpObject.120.3",
            "document_index": 0,
            "window_handle": 303,
            "window_title": "빈 문서 1 - 한글",
            "pid": 33,
            "path": "",
            "unsaved": True,
            "modified": True,
            "page_count": 3,
            "active": True,
            "visible": True,
        }
    ]


def test_new_document_is_added_only_when_dispatch_has_none() -> None:
    class Docs:
        def __init__(self, count: int) -> None:
            self.Count = count
            self.add_calls: list[bool] = []

        def Add(self, visible: bool) -> None:
            self.add_calls.append(visible)
            self.Count += 1

    class Com:
        def __init__(self, count: int) -> None:
            self.XHwpDocuments = Docs(count)

    existing = Com(1)
    assert _ensure_document_if_empty(existing) is False
    assert existing.XHwpDocuments.add_calls == []

    empty = Com(0)
    assert _ensure_document_if_empty(empty) is True
    assert empty.XHwpDocuments.add_calls == [False]
    assert empty.XHwpDocuments.Count == 1


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


def test_goto_addr_steps_through_actual_cells_after_merge() -> None:
    class WalkingAction(StubHAction):
        def __init__(self, owner) -> None:
            super().__init__()
            self.owner = owner

        def Run(self, act_id: str) -> bool:
            ok = super().Run(act_id)
            if not ok:
                return False
            if act_id in {"TableColBegin", "TableColPageUp"}:
                self.owner.index = 0
            elif act_id == "TableRightCell":
                self.owner.index = min(self.owner.index + 1, len(self.owner.addresses) - 1)
            return True

    class MergedWalkCom(StubCom):
        def __init__(self) -> None:
            super().__init__(cell_addr="A1")
            self.addresses = ["A1", "C1", "D1", "A2"]
            self.index = 0
            self.HAction = WalkingAction(self)

        def KeyIndicator(self):
            addr = self.addresses[self.index]
            return (1, 1, 1, 1, 1, 1, 1, 0, f"({addr})")

    com = MergedWalkCom()
    make_canvas(com).goto_addr("C1")
    assert com.HAction.calls.count("TableRightCell") == 1


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


def test_exit_table_uses_moveright_and_verifies_cursor_left_cell() -> None:
    com = StubCom(cur_field_state=1)
    canvas = make_canvas(com)
    original_run = canvas.run

    def move_out(action: str) -> bool:
        assert action in {"MoveListEnd", "MoveRight"}
        if action == "MoveRight":
            com.CurFieldState = 0
        return original_run(action)

    canvas.run = move_out  # type: ignore[method-assign]
    canvas.exit_table()

    assert com.HAction.calls == ["MoveListEnd", "MoveRight"]
    assert canvas.is_cell() is False


def test_exit_table_rejects_outside_or_nonfinal_cell() -> None:
    outside = StubCom(cur_field_state=0)
    with pytest.raises(HangulCommandError, match="표 셀 안에 있지 않아"):
        make_canvas(outside).exit_table()
    assert "MoveListEnd" not in outside.HAction.calls
    assert "MoveRight" not in outside.HAction.calls

    still_in_cell = StubCom(cur_field_state=1)
    with pytest.raises(HangulCommandError, match="마지막 셀"):
        make_canvas(still_in_cell).exit_table()
    assert still_in_cell.HAction.calls == ["MoveListEnd", "MoveRight", "MoveParentList"]


def test_exit_table_uses_parent_list_for_multiline_final_cell() -> None:
    com = StubCom(cur_field_state=1)
    canvas = make_canvas(com)
    original_run = canvas.run

    def leave_parent_list(action: str) -> bool:
        if action == "MoveParentList":
            com.CurFieldState = 0
        return original_run(action)

    canvas.run = leave_parent_list  # type: ignore[method-assign]
    canvas.exit_table()

    assert com.HAction.calls == ["MoveListEnd", "MoveRight", "MoveParentList"]
    assert canvas.is_cell() is False


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


def test_set_cell_fill_linear_gradient_writes_drawfill_arrays() -> None:
    """공개 gradient 사양이 CellFill의 실제 DrawFillAttr 배열로 내려가야 한다."""
    com = StubCom()
    out = make_canvas(com).set_cell_fill(
        {
            "type": "linear_gradient",
            "angle": 90,
            "stops": [
                {"offset": 0, "color": "#112233"},
                {"offset": 0.5, "color": "#445566"},
                {"offset": 1, "color": "#778899"},
            ],
        }
    )
    assert out == 1
    fill = com.cell_fill_action.hset.items["FillAttr"]
    assert fill.items["GradationAngle"] == 90
    assert fill.items["GradationColorNum"] == 3
    assert fill.items["GradationColor"].items[:3] == [
        com.RGBColor(17, 34, 51),
        com.RGBColor(68, 85, 102),
        com.RGBColor(119, 136, 153),
    ]
    assert fill.items["GradationIndexPos"].items[:3] == [0, 50, 100]
    assert com.cell_fill_action.defaults == 1
    assert com.cell_fill_action.executed == 1
    assert "Cancel" in com.HAction.calls


def test_set_cell_fill_radial_gradient_writes_center_and_step_fields() -> None:
    com = StubCom()
    make_canvas(com).set_cell_fill(
        {
            "type": "radial_gradient",
            "angle": 0,
            "center_x": 50,
            "center_y": 0,
            "step": 100,
            "step_center": 50,
            "stops": [
                {"offset": 0, "color": "#EAFFFC"},
                {"offset": 1, "color": "#FF843A"},
            ],
        }
    )

    fill = com.cell_fill_action.hset.items["FillAttr"]
    assert fill.items["GradationType"] == 2
    assert fill.items["GradationCenterX"] == 50
    assert fill.items["GradationCenterY"] == 0
    assert fill.items["GradationStep"] == 100
    assert fill.items["GradationStepCenter"] == 50


def test_adapter_rejects_oversized_gradient_before_cellfill_execute() -> None:
    com = StubCom()
    with pytest.raises(UsageError, match="10개"):
        make_canvas(com).set_cell_fill(
            {
                "type": "linear_gradient",
                "angle": 0,
                "stops": [
                    {"offset": index / 10, "color": "#123456"}
                    for index in range(11)
                ],
            }
        )
    assert com.cell_fill_action.executed == 0


def test_set_font_text_shadow_uses_charshape_and_rejects_alpha() -> None:
    com = StubCom()
    make_canvas(com).set_font(
        height_pt=28,
        text_shadow={
            "type": "offset",
            "color": "#102030",
            "alpha": 0,
            "offset_x_mm": 1.0,
            "offset_y_mm": -0.5,
        },
    )
    pset = com.HParameterSet.HCharShape
    assert pset.items["ShadowType"] == 1  # CharShadowType.Drop fallback
    assert pset.items["ShadowColor"] == com.RGBColor(16, 32, 48)
    font_mm = 28 * 25.4 / 72
    assert pset.items["ShadowOffsetX"] == round(1.0 / font_mm * 100)
    assert pset.items["ShadowOffsetY"] == round(-0.5 / font_mm * 100)
    assert "CharShape" in com.HAction.executed

    with pytest.raises(UsageError, match="alpha 0"):
        make_canvas(StubCom()).set_font(
            text_shadow={"type": "offset", "color": "#000000", "alpha": 1}
        )


def test_set_font_applies_letter_spacing_and_width_scale_to_all_scripts() -> None:
    com = StubCom()
    make_canvas(com).set_font(letter_spacing_percent=-3, width_scale_percent=110)

    pset = com.HParameterSet.HCharShape
    for language in ("Hangul", "Hanja", "Japanese", "Latin", "Other", "Symbol", "User"):
        assert pset.items[f"Spacing{language}"] == -3
        assert pset.items[f"Ratio{language}"] == 110
    assert "CharShape" in com.HAction.executed


def test_set_font_applies_run_decorations_and_kerning_without_dropping_color() -> None:
    com = StubCom()
    make_canvas(com).set_font(
        superscript=True,
        underline={
            "enabled": True,
            "type": "bottom",
            "shape": "solid",
            "color": "#112233",
        },
        strikeout={
            "enabled": True,
            "type": "continuous",
            "shape": "solid",
            "color": "#445566",
        },
        kerning=True,
    )

    pset = com.HParameterSet.HCharShape
    assert pset.HSet.items["Superscript"] is True
    assert pset.HSet.items["Subscript"] is False
    assert pset.items["UnderlineType"] == 1
    assert pset.items["UnderlineShape"] == 1
    assert pset.items["UnderlineColor"] == com.RGBColor(17, 34, 51)
    assert pset.items["StrikeOutType"] == 1
    assert pset.items["StrikeOutShape"] == 1
    assert pset.items["StrikeOutColor"] == com.RGBColor(68, 85, 102)
    assert pset.HSet.items["UseKerning"] is True
    assert "CharShape" in com.HAction.executed


def test_set_font_subscript_clears_superscript() -> None:
    com = StubCom()
    make_canvas(com).set_font(subscript=True)
    pset = com.HParameterSet.HCharShape
    assert pset.HSet.items["Subscript"] is True
    assert pset.HSet.items["Superscript"] is False


def test_set_paragraph_format_maps_public_mm_and_percent_to_hparashape() -> None:
    com = StubCom()
    make_canvas(com).set_paragraph_format(
        align="justify",
        left_margin_mm=3.5,
        right_margin_mm=2.0,
        first_line_indent_mm=-20.7,
        before_spacing_mm=1.0,
        after_spacing_mm=1.5,
        line_spacing_percent=150,
        break_latin_word="keep_word",
        break_non_latin_word="break_word",
    )

    pset = com.HParameterSet.HParaShape
    assert pset.items["AlignType"] == com.HAlign("Justify")
    assert pset.items["LeftMargin"] == com.MiliToHwpUnit(3.5)
    assert pset.items["RightMargin"] == com.MiliToHwpUnit(2.0)
    assert pset.items["Indentation"] == com.MiliToHwpUnit(-20.7)
    assert pset.items["PrevSpacing"] == com.MiliToHwpUnit(1.0)
    assert pset.items["NextSpacing"] == com.MiliToHwpUnit(1.5)
    assert pset.items["LineSpacing"] == 150
    assert pset.items["LineSpacingType"] == 0
    assert pset.items["BreakLatinWord"] == 1
    assert pset.items["BreakNonLatinWord"] == 0
    assert "ParagraphShape" in com.HAction.executed


def test_break_paragraph_and_native_page_number_use_expected_actions() -> None:
    com = StubCom()
    canvas = make_canvas(com)
    canvas.break_paragraph()
    canvas.set_page_number(position="bottom_center", separator="-")

    assert "BreakPara" in com.HAction.calls
    pset = com.HParameterSet.HPageNumPos
    assert pset.items["DrawPos"] == com.PageNumPosition("BottomCenter")
    assert pset.items["NumberFormat"] == 0
    assert pset.items["SideChar"] == ord("-")
    assert "PageNumPos" in com.HAction.executed


def test_page_visibility_and_page_number_restart_use_native_controls() -> None:
    com = StubCom()
    canvas = make_canvas(com)

    canvas.set_page_visibility(
        hide_header=False,
        hide_footer=False,
        hide_master_page=False,
        hide_border=False,
        hide_fill=False,
        hide_page_num=True,
    )
    canvas.restart_page_number(number=1)

    assert com.HParameterSet.HPageHiding.items["Fields"] == 32
    assert "PageHiding" in com.HAction.executed
    assert com.new_number_action.hset.items["NumType"] == 0
    assert com.new_number_action.hset.items["NewNumber"] == 1
    assert com.new_number_action.executed == 1


def test_table_properties_use_table_property_dialog_without_rebuilding_table() -> None:
    com = StubCom()
    canvas = make_canvas(com)
    table_targets: list[int] = []
    canvas.get_into_nth_table = lambda index: table_targets.append(index)  # type: ignore[method-assign]

    assert canvas.set_table_properties(
        table=2,
        page_break="cell",
        repeat_header=True,
        cell_spacing_mm=0.5,
    ) == 1

    pset = com.HParameterSet.HShapeObject
    assert table_targets == [2]
    assert pset.HSet.items["ShapeType"] == 3
    assert pset.HSet.items["ShapeCellSize"] == 0
    assert pset.items["PageBreak"] == 2
    assert pset.items["RepeatHeader"] == 1
    assert pset.items["CellSpacing"] == com.MiliToHwpUnit(0.5)
    assert "TablePropertyDialog" in com.HAction.executed
    assert "Cancel" in com.HAction.calls


def test_table_position_uses_native_inline_shape_fields() -> None:
    com = StubCom()
    canvas = make_canvas(com)
    canvas.get_into_nth_table = lambda index: None  # type: ignore[method-assign]

    assert canvas.set_table_position(
        table=0,
        position={
            "mode": "inline",
            "affect_line_spacing": True,
            "outside_margin_mm": [0.5, 0.5, 1.0, 1.0],
        },
    ) == 1

    pset = com.HParameterSet.HShapeObject
    assert pset.HSet.items["ShapeType"] == 3
    assert pset.items["TreatAsChar"] == 1
    assert pset.items["AffectsLine"] == 1
    assert pset.items["OutsideMarginLeft"] == com.MiliToHwpUnit(0.5)
    assert pset.items["OutsideMarginTop"] == com.MiliToHwpUnit(1.0)
    assert "TablePropertyDialog" in com.HAction.executed


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
    assert com.HAction.calls[-1] == "Cancel"


def test_row_height_uses_shape_cell_size_and_reads_default() -> None:
    com = StubCom()
    canvas = make_canvas(com)
    assert canvas.get_row_height() == pytest.approx(500 * 25.4 / 7200)
    canvas.set_row_height_current(12)
    pset = com.HParameterSet.HShapeObject
    assert pset.HSet.items["ShapeCellSize"] == 1
    assert pset.ShapeTableCell.items["Height"] == com.MiliToHwpUnit(12)


def test_merge_cells_normalizes_block_state_before_and_after() -> None:
    com = StubCom(cell_addr="A1")
    make_canvas(com).merge_cells("A1", "B2")
    calls = com.HAction.calls
    block = calls.index("TableCellBlock")
    extend = calls.index("TableCellBlockExtend")
    right = calls.index("TableRightCell")
    lower = calls.index("TableLowerCell")
    merge = calls.index("TableMergeCell")
    assert calls[0] == "Cancel"
    assert block < extend < right < lower < merge
    assert calls[merge + 1] == "Cancel"

    # 실패해도 다음 명령이 이전 선택 범위를 이어받지 않도록 끝에서 해제한다.
    bad = StubCom(cell_addr="A1", fail={"TableMergeCell"})
    with pytest.raises(HangulCommandError):
        make_canvas(bad).merge_cells("A1", "B2")
    assert bad.HAction.calls[-1] == "Cancel"


def test_select_cell_range_clears_previous_block_before_moving() -> None:
    com = StubCom(cell_addr="A1")
    make_canvas(com).select_cell_range("A1", "B3")
    assert com.HAction.calls[0] == "Cancel"


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


class StyleCom(StubCom):
    """이름 스타일의 COM 해석·복원 경로만 보이는 최소 문서 스텁."""

    def __init__(self, hwpml: str) -> None:
        super().__init__()
        self.hwpml = hwpml
        self.text_file_calls: list[tuple[str, str]] = []
        self.positions: list[tuple[int, int, int]] = []
        self.selection_calls: list[tuple[int, int, int, int]] = []

    def GetTextFile(self, fmt: str, option: str) -> str:
        self.text_file_calls.append((fmt, option))
        return self.hwpml

    def GetPos(self):
        return (0, 2, 3)

    def SetPos(self, list_id: int, para: int, pos: int) -> None:
        self.positions.append((list_id, para, pos))

    def GetSelectedPos(self):
        return (True, 0, 2, 3, 0, 2, 9)

    def SelectText(self, start_para: int, start_pos: int, end_para: int, end_pos: int) -> bool:
        self.selection_calls.append((start_para, start_pos, end_para, end_pos))
        return True


def test_named_style_resolves_com_hwpml_without_mutating_document_structure() -> None:
    com = StyleCom(
        '<HWPML xmlns="http://www.hancom.co.kr/hwpml/2011/">'
        '<STYLE Name="개요 1" Id="7"/>'
        "</HWPML>"
    )

    make_canvas(com).set_style("개요 1")

    assert com.text_file_calls == [("HWPML2X", "")]
    assert com.HParameterSet.HStyle.items["Apply"] == 7
    assert "GetDefault:Style" in com.HAction.calls
    assert com.HAction.executed == ["Style"]
    # HWPML을 다시 쓰지 않고, 읽는 도중 바뀔 수 있는 커서와 블록만 복원한다.
    assert com.positions == [(0, 2, 3)]
    assert com.selection_calls == [(2, 3, 2, 9)]


@pytest.mark.parametrize(
    "hwpml",
    [
        "<HWPML><STYLE Name='다른 스타일' Id='7'/></HWPML>",
        "<HWPML><STYLE Name='개요 1' Id='7'/><STYLE Name='개요 1' Id='8'/></HWPML>",
        "<HWPML><STYLE Name='개요 1' Id='not-a-number'/></HWPML>",
        "<HWPML><STYLE Name='개요 1'/></HWPML>",
        "<HWPML><STYLE",
    ],
)
def test_named_style_com_rejects_ambiguous_or_invalid_hwpml_before_style_action(hwpml: str) -> None:
    com = StyleCom(hwpml)

    with pytest.raises(HangulCommandError):
        make_canvas(com).set_style("개요 1")

    assert com.HAction.executed == []
    assert "GetDefault:Style" not in com.HAction.calls


def test_numeric_style_com_does_not_export_hwpml() -> None:
    com = StyleCom("<HWPML/>")

    make_canvas(com).set_style(7)

    assert com.text_file_calls == []
    assert com.HParameterSet.HStyle.items["Apply"] == 7
    assert com.HAction.executed == ["Style"]


def test_named_style_com_does_not_start_style_action_when_hwpml_read_fails() -> None:
    class BrokenStyleCom(StyleCom):
        def GetTextFile(self, fmt: str, option: str) -> str:
            self.text_file_calls.append((fmt, option))
            raise RuntimeError("HWPML export failed")

    com = BrokenStyleCom("<HWPML/>")
    with pytest.raises(HangulCommandError, match="문서 구조"):
        make_canvas(com).set_style("개요 1")

    assert com.HAction.executed == []
    assert "GetDefault:Style" not in com.HAction.calls


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
    com = StubComWindows([855126, 2100322], active_index=0)
    _show_window(com, 2100322)
    assert com.XHwpWindows.Item(1).Visible is True
    assert com.XHwpWindows.Item(0).Visible is False
    _show_window(com, 855126)
    assert com.XHwpWindows.Item(0).Visible is True


def test_pick_com_by_hwnd_matches_live_rot() -> None:
    """라이브 ROT: 120.1=[3738628] doc4, 120.2=[855126, 2100322]. pin=855126."""
    rot_first = StubComWindows([3738628])  # !HwpObject.120.1 — pyhwpx 가 붙는 쪽
    pinned = StubComWindows([855126, 2100322], active_index=0)  # 120.2
    instances = [rot_first, pinned]
    assert _pick_com_by_hwnd(instances, 855126) is pinned
    assert _pick_com_by_hwnd(instances, 2100322) is pinned
    assert _pick_com_by_hwnd(instances, 3738628) is rot_first
    assert _pick_com_by_hwnd(instances, 1) is None  # ROT-first 로 조용히 떨어지지 않음
    assert _pick_com_by_hwnd(instances, None) is rot_first


def test_make_window_current_uses_visible_and_set_active_doc() -> None:
    """IXHwpWindow.Activate 없음. Visible + SetActive_XHwpDocument."""
    com = StubComWindows([855126, 2100322], active_index=0)
    _make_window_current(com, 2100322)
    assert com.XHwpWindows.Item(1).Visible is True
    assert com.XHwpDocuments.Item(1).activated is True
    assert com.XHwpDocuments.Item(0).activated is False


def test_cell_typography_stops_when_character_move_does_not_progress() -> None:
    """셀 끝에서 MoveNextChar가 True여도 위치가 고정되면 한 번에 멈춘다."""
    canvas = make_canvas(StubCom(cell_addr="A1"))
    positions = {"start": (0, 0, 0), "end": (0, 0, 2)}
    state = {"phase": "start"}
    calls: list[str] = []
    restored: list[tuple] = []

    def get_pos() -> tuple:
        return positions[state["phase"]]

    def run(action: str) -> bool:
        calls.append(action)
        if action == "MoveListEnd":
            state["phase"] = "end"
        elif action == "MoveListBegin":
            state["phase"] = "start"
        return True

    canvas.get_pos = get_pos  # type: ignore[method-assign]
    canvas.set_pos = lambda pos: restored.append(pos) or True  # type: ignore[method-assign]
    canvas.current_cell_addr = lambda: "A1"  # type: ignore[method-assign]
    canvas._get_font_size_pt = lambda: 16.0  # type: ignore[method-assign]
    canvas._get_line_spacing_percent = lambda: 200.0  # type: ignore[method-assign]
    canvas.run = run  # type: ignore[method-assign]

    assert canvas._get_cell_typography("x" * 5000) == (16.0, 200.0)
    assert calls.count("MoveNextChar") == 1
    assert restored == [(0, 0, 0)]


def test_cell_typography_keeps_largest_measurement_until_cell_end() -> None:
    canvas = make_canvas(StubCom(cell_addr="A1"))
    state = {"index": 0}
    positions = [(0, 0, 0), (0, 0, 1), (0, 0, 2)]
    fonts = [11.0, 18.0, 12.0]
    spacings = [160.0, 210.0, 180.0]
    calls: list[str] = []
    restored: list[tuple] = []

    def get_pos() -> tuple:
        return positions[state["index"]]

    def run(action: str) -> bool:
        calls.append(action)
        if action == "MoveListEnd":
            state["index"] = 2
        elif action == "MoveListBegin":
            state["index"] = 0
        elif action == "MoveNextChar":
            state["index"] = min(2, state["index"] + 1)
        return True

    canvas.get_pos = get_pos  # type: ignore[method-assign]
    canvas.set_pos = lambda pos: restored.append(pos) or True  # type: ignore[method-assign]
    canvas.current_cell_addr = lambda: "A1"  # type: ignore[method-assign]
    canvas._get_font_size_pt = lambda: fonts[state["index"]]  # type: ignore[method-assign]
    canvas._get_line_spacing_percent = lambda: spacings[state["index"]]  # type: ignore[method-assign]
    canvas.run = run  # type: ignore[method-assign]

    assert canvas._get_cell_typography("abc") == (18.0, 210.0)
    assert calls.count("MoveNextChar") == 2
    assert restored == [(0, 0, 0)]


def test_goto_page_uses_verified_move_actions_instead_of_com_gotopage() -> None:
    """COM GotoPage는 성공처럼 돌아와도 현재 쪽에 남을 수 있다."""

    class SilentGotoCom(StubCom):
        def __init__(self) -> None:
            super().__init__()
            self.goto_calls: list[int] = []

        def GotoPage(self, page: int) -> None:
            self.goto_calls.append(page)

    com = SilentGotoCom()
    canvas = make_canvas(com)

    canvas.goto_page(2)

    assert com.goto_calls == []
    assert com.HAction.calls == ["MoveDocBegin", "MovePageDown"]


def test_doc_info_reads_page_number_from_com_key_indicator() -> None:
    class PageTwoCom(StubCom):
        def KeyIndicator(self):
            return (1, 1, 1, 2, 1, 1, 1, 0, "")

    assert make_canvas(PageTwoCom()).doc_info().page == 2


def test_list_tables_uses_actual_cell_addresses_when_com_lacks_dimension_helpers() -> None:
    canvas = make_canvas(StubCom())
    canvas._table_count = lambda: 1  # type: ignore[method-assign]
    canvas.get_into_nth_table = lambda index: None  # type: ignore[method-assign]
    canvas._table_addresses = lambda: ["A1", "B1", "A2", "B2"]  # type: ignore[method-assign]
    canvas.goto_addr = lambda address: None  # type: ignore[method-assign]
    canvas._get_current_cell_text = lambda: ""  # type: ignore[method-assign]

    tables = canvas.list_tables()

    assert tables == [{"index": 0, "rows": 2, "cols": 2, "preview": [["", ""], ["", ""]]}]
