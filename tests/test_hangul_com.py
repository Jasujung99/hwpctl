"""win32com 폴백 경로 단위 테스트 (한/글 없이 스텁 COM 객체로).

핵심 회귀: goto_addr 의 이동 액션이 실패했는데도 조용히 넘어가
SelectAll 이 문서 전체를 선택 → insert_text 가 문서를 통째로 덮어쓰는 사고 경로.
"""

from __future__ import annotations

import pytest

from hwpctl.errors import HangulCommandError
from hwpctl.hangul import HangulCanvas


class StubHAction:
    def __init__(self, fail: set[str] | None = None) -> None:
        self.fail = fail or set()
        self.calls: list[str] = []

    def Run(self, act_id: str) -> bool:
        self.calls.append(act_id)
        return act_id not in self.fail


class StubCom:
    def __init__(
        self,
        fail: set[str] | None = None,
        cur_field_state: int = 1,
        cell_addr: str = "",
    ) -> None:
        self.HAction = StubHAction(fail)
        self.CurFieldState = cur_field_state
        self._cell_addr = cell_addr

    def KeyIndicator(self):
        # (succ, seccnt, secno, prnpageno, colno, line, pos, over, ctrlname)
        return (1, 1, 1, 1, 1, 1, 1, 0, f"({self._cell_addr})" if self._cell_addr else "")

    def GetSelectedPos(self):
        return (False, 0, 0, 0, 0, 0, 0)


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