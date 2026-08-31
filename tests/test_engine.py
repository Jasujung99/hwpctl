from __future__ import annotations

from pathlib import Path

import pytest

from hwpctl.colors import parse_color
from hwpctl.engine import Engine, _normalize_cells, suggested_save_as_path
from hwpctl.errors import DestructiveGuardError, HangulCommandError, UsageError
from hwpctl.hangul import expand_range, parse_a1
from hwpctl.lock import load_state


class FakeCanvas:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.path = ""
        self.modified = False
        self.selected = "기존"
        self.selection_active = True
        self.in_cell = True
        self.undone = 0
        self.hwnd = 1111
        self.charshape = "CHAR0"
        self.parashape = "PARA0"
        self.page_count = 2
        self.page_counts: list[int] = []
        self.layout = {
            "index": 0,
            "rows": 1,
            "cols": 2,
            "table_width_mm": 100.0,
            "body_width_mm": 150.0,
            "max_table_width_mm": 150.0,
            "column_widths_mm": [50.0, 50.0],
            "row_heights_mm": [10.0],
            "cells": [
                {
                    "row": 0,
                    "col": 0,
                    "address": "A1",
                    "text": "긴 셀 내용",
                    "line_count": 2,
                    "hard_line_count": 1,
                    "soft_wrapped": True,
                    "font_size_pt": 10.0,
                    "line_spacing_percent": 160.0,
                    "margins_mm": {"left": 3.5, "right": 3.5, "top": 2.0, "bottom": 2.0},
                },
                {
                    "row": 0,
                    "col": 1,
                    "address": "B1",
                    "text": "짧음",
                    "line_count": 1,
                    "hard_line_count": 1,
                    "soft_wrapped": False,
                    "font_size_pt": 10.0,
                    "line_spacing_percent": 160.0,
                    "margins_mm": {"left": 3.5, "right": 3.5, "top": 2.0, "bottom": 2.0},
                },
            ],
            "warnings": [],
        }

    def window_handle(self) -> int:
        return self.hwnd

    def has_selection(self) -> bool:
        return self.selection_active

    def table_count(self) -> int:
        return 1

    def assert_no_dialog(self) -> None:
        return None

    def inspect_table_layout(self, n: int):
        assert n == self.layout["index"]
        return self.layout

    def set_table_column_widths(self, n: int, widths_mm: list[float]) -> int:
        self.calls.append(("set_table_column_widths", (n, list(widths_mm))))
        self.layout["column_widths_mm"] = list(widths_mm)
        self.layout["table_width_mm"] = sum(widths_mm)
        for cell in self.layout["cells"]:
            cell["line_count"] = cell["hard_line_count"]
            cell["soft_wrapped"] = False
        return len(widths_mm)

    def set_table_row_height(self, n: int, row: int, height_mm: float) -> int:
        self.calls.append(("set_table_row_height", (n, row, height_mm)))
        self.layout["row_heights_mm"][row] = height_mm
        return 1

    def get_pos(self):
        return (0, 3, 7)

    def set_pos(self, pos) -> bool:
        self.calls.append(("set_pos", pos))
        return True

    def selection_range(self):
        if self.selection_active:
            return (True, 0, 0, 1, 0, 0, 5)
        return None

    def restore_selection(self, sel) -> bool:
        self.calls.append(("restore_selection", sel))
        return True

    def set_table_inside_margin(self, left, right, top, bottom) -> None:
        self.calls.append(("set_table_inside_margin", (left, right, top, bottom)))

    def set_cell_margin_current(self, left, right, top, bottom) -> None:
        self.calls.append(("set_cell_margin_current", (left, right, top, bottom)))

    def select_all_cells(self) -> None:
        from hwpctl.errors import HangulCommandError as _E

        if not self.in_cell:
            raise _E("캐럿이 표 안에 있지 않습니다.")
        self.calls.append(("select_all_cells", None))

    def select_cell_range(self, start, end) -> None:
        self.calls.append(("select_cell_range", (start, end)))

    def insert_chart(self, chart_group, chart_index=0, dialog_disable=True) -> None:
        self.calls.append(
            (
                "insert_chart",
                {
                    "chart_group": chart_group,
                    "chart_index": chart_index,
                    "dialog_disable": dialog_disable,
                },
            )
        )

    def get_charshape(self):
        return self.charshape

    def set_charshape(self, pset) -> bool:
        if pset is None:
            return False
        self.calls.append(("set_charshape", pset))
        return True

    def get_parashape(self):
        return self.parashape

    def set_parashape(self, pset) -> bool:
        if pset is None:
            return False
        self.calls.append(("set_parashape", pset))
        return True

    def doc_info(self):
        from hwpctl.hangul import DocInfo

        page_count = self.page_counts.pop(0) if self.page_counts else self.page_count
        return DocInfo(
            window_title="빈 문서 1 - 한글",
            path=self.path,
            modified=self.modified,
            page=1,
            page_count=page_count,
            version=[13, 0, 0, 1],
            backend="fake",
        )

    def get_body_text(self) -> str:
        return "제목\r\n본문\r\n"

    def get_selected_text(self) -> str:
        return self.selected

    def get_page_text(self, page_index_1: int) -> str:
        return f"page-{page_index_1}"

    def list_tables(self, preview_rows: int = 8):
        return [{"index": 0, "rows": 2, "cols": 2, "preview": [["a", "b"]]}]

    def set_font(self, **kwargs) -> None:
        self.calls.append(("set_font", kwargs))

    def set_align(self, align: str) -> None:
        self.calls.append(("set_align", align))

    def insert_text(self, text: str) -> None:
        self.calls.append(("insert_text", text))

    def create_table(self, rows: int, cols: int, header: bool = True) -> None:
        self.calls.append(("create_table", (rows, cols, header)))

    def is_cell(self) -> bool:
        return self.in_cell

    def get_into_nth_table(self, n: int = 0) -> None:
        self.calls.append(("get_into_nth_table", n))

    def goto_addr(self, addr: str) -> None:
        self.calls.append(("goto_addr", addr))

    def select_row(self) -> None:
        self.calls.append(("select_row", None))

    def cell_fill(self, color: str) -> None:
        self.calls.append(("cell_fill", color))

    def select_cell_text(self) -> None:
        self.calls.append(("select_cell_text", None))

    def open_path(self, path: str) -> None:
        self.path = path
        self.modified = False
        self.calls.append(("open_path", path))

    def new_document(self) -> None:
        self.path = ""
        self.calls.append(("new_document", None))

    def save_as(self, path: str, fmt: str = "") -> None:
        self.calls.append(("save_as", (path, fmt)))

    def save_overwrite(self) -> None:
        self.calls.append(("save_overwrite", None))

    def close_discard(self) -> None:
        self.calls.append(("close_discard", None))

    def undo_once(self) -> None:
        self.undone += 1

    def goto_page(self, page_index_1: int) -> None:
        self.calls.append(("goto_page", page_index_1))


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Engine, FakeCanvas]:
    fake = FakeCanvas()
    monkeypatch.setenv("HWPCTL_LOCK", str(tmp_path / "lock"))
    monkeypatch.setenv("HWPCTL_STATE", str(tmp_path / "state.json"))
    eng = Engine(lock_timeout=1, canvas_factory=lambda new=False, allow_launch=False: fake)
    return eng, fake


def test_insert_title_counts_all_actions_and_restores_format(engine) -> None:
    """회귀 방지: insert_title 은 CharShape+ParaShape+InsertText+복원 2회 = 5개
    한/글 액션을 기록해야 하고(과거엔 1로 기록해 undo 가 서식을 남겼음),
    제목 서식이 다음 문단으로 새지 않도록 저장해 둔 모양을 복원해야 한다."""
    eng, fake = engine
    out = eng.insert_title("사업계획서")
    assert out["ok"] is True
    assert out["undo_units"] == 1
    assert out["hangul_actions"] == 5
    texts = [c[1] for c in fake.calls if c[0] == "insert_text"]
    assert texts == ["사업계획서\r\n"]
    state = load_state()
    assert state.undo_stack == [5]
    # 서식 복원이 삽입 이후에 일어나야 다음 insert_paragraph 가 오염되지 않는다
    order = [c[0] for c in fake.calls]
    insert_idx = order.index("insert_text")
    assert ("set_charshape", "CHAR0") in fake.calls
    assert ("set_parashape", "PARA0") in fake.calls
    assert order.index("set_charshape") > insert_idx
    assert order.index("set_parashape") > insert_idx


def test_insert_title_undo_rewinds_whole_unit(engine) -> None:
    eng, fake = engine
    eng.insert_title("사업계획서")
    out = eng.undo()
    assert out["hangul_undo_steps"] == 5
    assert fake.undone == 5


def test_insert_title_skips_restore_count_when_shape_unavailable(engine) -> None:
    eng, fake = engine
    fake.charshape = None
    fake.parashape = None
    out = eng.insert_title("제목")
    assert out["hangul_actions"] == 3
    assert load_state().undo_stack == [3]


def test_create_table_header_fill_and_default_margin(engine) -> None:
    eng, fake = engine
    eng.create_table(rows=8, cols=4, header_fill="gray")
    assert ("create_table", (8, 4, True)) in fake.calls
    # 새 표 기본 칸 안여백: 좌우 3.5mm, 상하 2.0mm — 방금 만든 표에 적용
    assert ("set_table_inside_margin", (3.5, 3.5, 2.0, 2.0)) in fake.calls
    assert ("cell_fill", "gray") in fake.calls
    # 다른 표(0번 표)로 이동하지 않아야 한다 (#9 회귀 방지)
    assert not any(c[0] == "get_into_nth_table" for c in fake.calls)
    assert load_state().undo_stack[-1] == 3


def test_create_table_custom_and_disabled_padding(engine) -> None:
    eng, fake = engine
    eng.create_table(rows=2, cols=2, cell_margin="4,3")
    assert ("set_table_inside_margin", (4.0, 4.0, 3.0, 3.0)) in fake.calls
    fake.calls.clear()
    eng.create_table(rows=2, cols=2, cell_margin="none")
    assert not any(c[0] == "set_table_inside_margin" for c in fake.calls)


def test_create_table_refuses_wrong_table_when_caret_outside(engine) -> None:
    """회귀 방지(#9): 표 생성 후 캐럿이 셀 밖이면 문서의 0번 표를 건드리지 말고 실패."""
    eng, fake = engine
    fake.in_cell = False
    with pytest.raises(HangulCommandError):
        eng.create_table(rows=2, cols=2, header_fill="gray")
    assert not any(c[0] == "get_into_nth_table" for c in fake.calls)
    assert not any(c[0] == "cell_fill" for c in fake.calls)


def test_fill_cells_grid(engine) -> None:
    eng, fake = engine
    eng.fill_cells(table=0, cells=[["항목", "내용"]])
    addrs = [c[1] for c in fake.calls if c[0] == "goto_addr"]
    assert "A1" in addrs and "B1" in addrs
    assert load_state().undo_stack[-1] == 2


def test_layout_review_wrapped_cell_increases_column_width(engine) -> None:
    eng, fake = engine
    out = eng.layout_review(table=0)
    calls = [call for call in fake.calls if call[0] == "set_table_column_widths"]
    assert len(calls) == 1
    widths = calls[0][1][1]
    assert widths[0] > 50.0
    assert out["tables"][0]["column_changes"][0]["column"] == 1
    assert out["hangul_actions"] >= 2  # pyhwpx는 열마다 TablePropertyDialog 1회
    assert load_state().undo_stack[-1] == out["hangul_actions"]


def test_layout_review_stops_at_body_width_cap(engine) -> None:
    eng, fake = engine
    fake.layout["max_table_width_mm"] = 100.0
    out = eng.layout_review(table=0)
    assert not any(call[0] == "set_table_column_widths" for call in fake.calls)
    assert out["hangul_actions"] == 0
    assert any("상한" in warning for warning in out["warnings"])


def test_layout_review_dry_run_does_not_change_width(engine) -> None:
    eng, fake = engine
    out = eng.layout_review(table=0, dry_run=True)
    assert out["tables"][0]["column_changes"]
    assert not any(call[0] == "set_table_column_widths" for call in fake.calls)
    assert not any(call[0] == "set_table_row_height" for call in fake.calls)
    assert out["undo_units"] == 0
    assert load_state().undo_stack == []


def test_layout_review_warns_when_one_page_becomes_two(engine) -> None:
    eng, fake = engine
    fake.page_counts = [1, 2]
    out = eng.layout_review(table=0)
    assert out["page_count"] == {"before": 1, "after": 2, "changed": True}
    assert any("1쪽에서 2쪽" in warning for warning in out["warnings"])


def test_undo_replays_hangul_steps(engine) -> None:
    eng, fake = engine
    eng.insert_paragraph("하나")
    eng.create_table(8, 4, header_fill="gray")  # 생성 + 안여백 + 머리행색 = 3
    out = eng.undo()
    assert out["hangul_undo_steps"] == 3
    assert fake.undone == 3


def test_undo_refuses_without_recorded_edits(engine) -> None:
    """회귀 방지(#11): 기록이 없으면 사용자의 수동 편집을 되돌리지 않는다."""
    eng, fake = engine
    with pytest.raises(HangulCommandError) as exc:
        eng.undo()
    assert "기록한 편집이 없어" in exc.value.message
    assert fake.undone == 0


def test_save_without_overwrite_rejected(engine) -> None:
    eng, _ = engine
    with pytest.raises(DestructiveGuardError) as exc:
        eng.save(overwrite=False)
    assert "--overwrite" in exc.value.message


def test_close_without_force_rejected(engine) -> None:
    eng, _ = engine
    with pytest.raises(DestructiveGuardError):
        eng.close(force=False)


def test_open_dirty_requires_discard(engine) -> None:
    eng, fake = engine
    fake.modified = True
    with pytest.raises(DestructiveGuardError) as exc:
        eng.open(path=None)
    assert "--discard" in exc.value.message


def test_save_as_refuses_same_path(engine, tmp_path: Path) -> None:
    eng, fake = engine
    dest = tmp_path / "same.hwp"
    dest.write_text("x", encoding="utf-8")
    fake.path = str(dest)
    with pytest.raises(DestructiveGuardError):
        eng.save_as(str(dest))


def test_replace_selection_requires_real_block(engine) -> None:
    """회귀 방지: 선택이 없어도 get_selected_text 는 '현재 단어'를 리턴한다.
    비어 있지 않은 단어가 와도 has_selection 이 False 면 교체를 거부해야 한다."""
    eng, fake = engine
    fake.selection_active = False
    fake.selected = "현재단어"  # 선택 없음 + 캐럿이 단어 위 (pyhwpx 실제 동작)
    with pytest.raises(HangulCommandError) as exc:
        eng.replace_selection("새 텍스트")
    assert "선택 영역이 없습니다" in exc.value.message
    assert not any(c[0] == "insert_text" for c in fake.calls)


def test_replace_selection_with_block(engine) -> None:
    eng, fake = engine
    fake.selection_active = True
    fake.selected = "바꿀 문장"
    out = eng.replace_selection("새 문장")
    assert out["replaced"] is True
    assert out["replaced_text"] == "바꿀 문장"
    assert ("insert_text", "새 문장") in fake.calls


def test_snapshot_selection_empty_without_block(engine) -> None:
    eng, fake = engine
    fake.selection_active = False
    fake.selected = "현재단어"
    snap = eng.snapshot()
    assert snap["selection"] == ""


def test_window_pinning_rejects_other_window(engine) -> None:
    """회귀 방지: 첫 명령이 창을 고정하고, 다른 창(핸들 변경)에 연결되면
    편집 대신 한국어 오류를 내야 한다. open 은 창을 다시 고정한다."""
    eng, fake = engine
    eng.status()
    assert load_state().target_hwnd == 1111
    fake.hwnd = 2222  # pyhwpx 가 '마지막 접근 창'인 다른 창에 붙은 상황
    with pytest.raises(HangulCommandError) as exc:
        eng.insert_paragraph("본문")
    assert "다른 창" in exc.value.message
    assert not any(c[0] == "insert_text" for c in fake.calls)
    eng.open()  # 명시적 open 이 새 창을 고정
    assert load_state().target_hwnd == 2222
    eng.insert_paragraph("본문")  # 이제 통과
    assert any(c[0] == "insert_text" for c in fake.calls)


def test_close_unpins_window(engine) -> None:
    eng, fake = engine
    eng.status()
    assert load_state().target_hwnd == 1111
    eng.close(force=True)
    assert load_state().target_hwnd == 0


def test_status_and_snapshot(engine) -> None:
    eng, _ = engine
    st = eng.status()
    assert st["backend"] == "fake"
    assert st["autosave"] is False
    snap = eng.snapshot()
    assert "제목" in snap["body"]
    assert snap["tables"][0]["cols"] == 2


def test_set_cell_margin_whole_table(engine) -> None:
    eng, fake = engine
    out = eng.set_cell_margin(table=0)
    assert ("get_into_nth_table", 0) in fake.calls
    assert ("set_table_inside_margin", (3.5, 3.5, 2.0, 2.0)) in fake.calls
    assert out["scope"] == "table:0"
    assert out["margin_mm"] == [3.5, 3.5, 2.0, 2.0]


def test_set_cell_margin_range_per_cell(engine) -> None:
    eng, fake = engine
    eng.set_cell_margin(table=0, cell_range="A1:B2", left=4, right=4, top=1, bottom=1)
    addrs = [c[1] for c in fake.calls if c[0] == "goto_addr"]
    assert addrs == ["A1", "B1", "A2", "B2"]
    margins = [c for c in fake.calls if c[0] == "set_cell_margin_current"]
    assert len(margins) == 4
    assert margins[0][1] == (4, 4, 1, 1)
    assert load_state().undo_stack[-1] == 4


def test_set_cell_margin_current_cell_without_table(engine) -> None:
    eng, fake = engine
    out = eng.set_cell_margin(left=2, right=2, top=1, bottom=1)
    assert ("set_cell_margin_current", (2, 2, 1, 1)) in fake.calls
    assert out["scope"] == "current-cell"


def test_set_cell_margin_rejects_out_of_range(engine) -> None:
    eng, _ = engine
    with pytest.raises(UsageError):
        eng.set_cell_margin(table=0, left=100)


def test_insert_chart_line_defaults(engine) -> None:
    """인생 그래프 기본: line → ChartGroup 2, 대화상자 비활성."""
    eng, fake = engine
    out = eng.insert_chart(table=0)
    assert ("get_into_nth_table", 0) in fake.calls
    assert ("select_all_cells", None) in fake.calls
    charts = [c[1] for c in fake.calls if c[0] == "insert_chart"]
    assert charts == [{"chart_group": 2, "chart_index": 0, "dialog_disable": True}]
    assert out["chart_type"] == "line"
    assert out["native"] is True
    assert load_state().undo_stack[-1] == 1


def test_insert_chart_pie_with_range(engine) -> None:
    eng, fake = engine
    eng.insert_chart(table=0, cell_range="A1:B10", chart_type="pie")
    assert ("select_cell_range", ("A1", "B10")) in fake.calls
    charts = [c[1] for c in fake.calls if c[0] == "insert_chart"]
    assert charts[0]["chart_group"] == 3
    assert charts[0]["dialog_disable"] is True


def test_insert_chart_rejects_unknown_type_and_missing_table(engine) -> None:
    eng, fake = engine
    with pytest.raises(UsageError):
        eng.insert_chart(table=0, chart_type="donut")
    fake.in_cell = False
    with pytest.raises(UsageError):
        eng.insert_chart()  # table 없음 + 캐럿도 표 밖
    assert not any(c[0] == "insert_chart" for c in fake.calls)


def test_snapshot_restores_caret_and_selection(engine) -> None:
    """회귀 방지(#10): snapshot(읽기)이 캐럿·선택을 파괴하면 안 된다."""
    eng, fake = engine
    fake.selection_active = True
    snap = eng.snapshot()
    assert snap["selection"] == "기존"
    assert ("set_pos", (0, 3, 7)) in fake.calls
    restored = [c for c in fake.calls if c[0] == "restore_selection"]
    assert restored and restored[0][1][0] is True


def test_set_format_range_applies_only_requested_cells(engine) -> None:
    """회귀 방지(#12): A1:B2 는 4칸 전부, 행 전체 확대 없이 요청 칸만."""
    eng, fake = engine
    eng.set_format(fill="gray", table=0, cell_range="A1:B2")
    addrs = [c[1] for c in fake.calls if c[0] == "goto_addr"]
    assert addrs == ["A1", "B1", "A2", "B2"]
    assert len([c for c in fake.calls if c[0] == "cell_fill"]) == 4
    assert not any(c[0] == "select_row" for c in fake.calls)


def test_set_format_range_with_row_rejected(engine) -> None:
    eng, _ = engine
    with pytest.raises(UsageError):
        eng.set_format(fill="gray", table=0, cell_range="A1:B1", row=1)


def test_normalize_margin_helper() -> None:
    from hwpctl.engine import _normalize_margin

    assert _normalize_margin("3.5,2.0") == (3.5, 3.5, 2.0, 2.0)
    assert _normalize_margin("1,2,3,4") == (1.0, 2.0, 3.0, 4.0)
    assert _normalize_margin("2.5") == (2.5, 2.5, 2.5, 2.5)
    assert _normalize_margin("none") is None
    assert _normalize_margin(None) is None
    assert _normalize_margin((1, 2, 3, 4)) == (1.0, 2.0, 3.0, 4.0)
    with pytest.raises(UsageError):
        _normalize_margin("abc")
    with pytest.raises(UsageError):
        _normalize_margin("1,2,3")
    with pytest.raises(UsageError):
        _normalize_margin("99,99")


def test_normalize_cells() -> None:
    assert _normalize_cells([["a", "b"]], None) == {"A1": "a", "B1": "b"}
    assert _normalize_cells({"C3": "x"}, {"A1": "y"}) == {"A1": "y", "C3": "x"}


def test_parse_a1_and_range() -> None:
    assert parse_a1("B12") == (11, 1)
    assert expand_range("A1:B2") == ["A1", "B1", "A2", "B2"]


def test_parse_color() -> None:
    assert parse_color("gray") == (217, 217, 217)
    assert parse_color("#FF0000") == (255, 0, 0)
    with pytest.raises(UsageError):
        parse_color("neon")


def test_suggested_save_as_keeps_stem() -> None:
    path = suggested_save_as_path("C:/docs/plan.hwp")
    assert "plan-edited-" in path
    assert path.endswith(".hwp")