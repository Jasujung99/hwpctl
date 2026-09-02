from __future__ import annotations

from pathlib import Path

import pytest

from hwpctl.colors import parse_color
from hwpctl.engine import Engine, _normalize_cells, suggested_save_as_path
from hwpctl.errors import DestructiveGuardError, HangulCommandError, UsageError
from hwpctl.hangul import a1, expand_range, parse_a1
from hwpctl.layout import plan_table_layout
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
        self.title = "빈 문서 1 - 한글"
        self.page_count = 2
        self.page_counts: list[int] = []
        self.created_shape: tuple[int, int] | None = None
        # 새 시각 서식 명령의 COM 액션 수. Engine이 실제 어댑터 반환값을
        # Undo 스택에 그대로 기록하는지 검증할 때 쓴다.
        self.text_box_actions = 3
        self.cell_fill_actions = 1
        self.blank_paragraph_creations: list[bool] = []
        self._table_control = type("TableCtrl", (), {"CtrlID": "tbl"})()
        self.create_enters_cell = False
        self.blank_paragraph_count = 1
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

    def table_control(self, table: int):
        self.calls.append(("table_control", table))
        return self._table_control

    def delete_table_control(self, ctrl) -> None:
        assert ctrl is self._table_control
        self.calls.append(("delete_table_control", None))

    def ensure_blank_paragraph_before_body(self, text: str) -> bool:
        self.calls.append(("ensure_blank_paragraph_before_body", text))
        self.in_cell = False
        self.blank_paragraph_creations.append(True)
        return True

    def count_blank_paragraphs_before_body(self, text: str) -> int:
        self.calls.append(("count_blank_paragraphs_before_body", text))
        return self.blank_paragraph_count

    def remove_empty_paragraph_immediately_before_body(self, text: str) -> None:
        self.calls.append(("remove_empty_paragraph_immediately_before_body", text))
        self.blank_paragraph_count -= 1

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

    def set_table_column_width(self, n: int, col: int, width_mm: float) -> int:
        self.calls.append(("set_table_column_width", (n, col, width_mm)))
        old = self.layout["column_widths_mm"][col]
        self.layout["column_widths_mm"][col] = width_mm
        self.layout["table_width_mm"] += width_mm - old
        for cell in self.layout["cells"]:
            if cell["col"] == col:
                cell["line_count"] = cell["hard_line_count"]
                cell["soft_wrapped"] = False
        return 1

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

    def set_cell_margin_current(self, left, right, top, bottom) -> None:
        self.calls.append(("set_cell_margin_current", (left, right, top, bottom)))

    def table_cell_addresses(self) -> list[str]:
        rows, cols = self.created_shape or (self.layout["rows"], self.layout["cols"])
        return [a1(r, c) for r in range(rows) for c in range(cols)]

    def set_all_cell_margins(self, left, right, top, bottom) -> int:
        addresses = self.table_cell_addresses()
        for addr in addresses:
            self.goto_addr(addr)
            self.set_cell_margin_current(left, right, top, bottom)
        return len(addresses)

    def get_table_column_widths(self) -> list[float]:
        return list(self.layout["column_widths_mm"])

    def table_column_addresses(self) -> dict[int, str]:
        return {col: a1(0, col) for col in range(self.layout["cols"])}

    def table_row_addresses(self) -> dict[int, str]:
        return {row: a1(row, 0) for row in range(self.layout["rows"])}

    def set_col_width_current(self, width: float) -> None:
        self.calls.append(("set_col_width_current", width))

    def get_col_width(self) -> float:
        return 50.0

    def set_row_height_current(self, height: float) -> None:
        self.calls.append(("set_row_height_current", height))

    def get_row_height(self) -> float:
        return 10.0

    def merge_cells(self, start: str, end: str) -> None:
        self.calls.append(("merge_cells", (start, end)))

    def set_valign_current(self, align: str) -> int:
        self.calls.append(("set_valign_current", align))
        return {"top": 0, "center": 1, "bottom": 2}[align]

    def set_cell_border_current(self, **kwargs) -> None:
        self.calls.append(("set_cell_border_current", kwargs))

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
            window_title=self.title,
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

    def select_exact_body_paragraph(self, text: str, occurrence: int = 1):
        self.calls.append(("select_exact_body_paragraph", (text, occurrence)))
        return {"text": text, "position": (0, 4, 1), "in_cell": False}

    def get_page_text(self, page_index_1: int) -> str:
        return f"page-{page_index_1}"

    def list_tables(self, preview_rows: int = 8):
        return [{"index": 0, "rows": 2, "cols": 2, "preview": [["a", "b"]]}]

    def set_font(self, **kwargs) -> None:
        self.calls.append(("set_font", kwargs))

    def set_align(self, align: str) -> None:
        self.calls.append(("set_align", align))

    def set_paragraph_format(self, **kwargs) -> None:
        self.calls.append(("set_paragraph_format", kwargs))

    def insert_text(self, text: str) -> None:
        self.calls.append(("insert_text", text))

    def create_table(self, rows: int, cols: int, header: bool = True) -> None:
        self.created_shape = (rows, cols)
        if self.create_enters_cell:
            self.in_cell = True
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

    def set_cell_fill(self, *, fill) -> int:
        self.calls.append(("set_cell_fill", fill))
        return self.cell_fill_actions

    def exit_table(self) -> None:
        self.calls.append(("exit_table", None))
        self.in_cell = False

    def insert_text_box(self, text: str, width_mm: float, height_mm: float, **kwargs) -> int:
        self.calls.append(
            (
                "insert_text_box",
                {
                    "text": text,
                    "width_mm": width_mm,
                    "height_mm": height_mm,
                    **kwargs,
                },
            )
        )
        return self.text_box_actions

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

    def break_page(self) -> None:
        self.calls.append(("break_page", None))

    def break_paragraph(self) -> None:
        self.calls.append(("break_paragraph", None))

    def set_page_number(self, **kwargs) -> None:
        self.calls.append(("set_page_number", kwargs))

    def set_page_visibility(self, **kwargs) -> None:
        self.calls.append(("set_page_visibility", kwargs))

    def restart_page_number(self, **kwargs) -> None:
        self.calls.append(("restart_page_number", kwargs))

    def set_table_properties(self, **kwargs) -> int:
        self.calls.append(("set_table_properties", kwargs))
        return 1

    def set_table_position(self, **kwargs) -> int:
        self.calls.append(("set_table_position", kwargs))
        return 1

    def set_current_table_properties(self, **kwargs) -> int:
        self.calls.append(("set_current_table_properties", kwargs))
        return 1

    def set_current_inline_table_position(self, **kwargs) -> int:
        self.calls.append(("set_current_inline_table_position", kwargs))
        return 1

    def set_pagedef(self, **kwargs) -> None:
        self.calls.append(("set_pagedef", kwargs))

    def set_style(self, style) -> None:
        self.calls.append(("set_style", style))

    def run(self, action: str) -> bool:
        self.calls.append(("run", action))
        return True


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Engine, FakeCanvas]:
    fake = FakeCanvas()
    monkeypatch.setenv("HWPCTL_LOCK", str(tmp_path / "lock"))
    monkeypatch.setenv("HWPCTL_STATE", str(tmp_path / "state.json"))
    eng = Engine(
        lock_timeout=1,
        canvas_factory=lambda new=False, allow_launch=False, hwnd=0: fake,
        document_lister=lambda: [
            {
                "instance": "!HwpObject.120.9",
                "document_index": 0,
                "window_handle": 9999,
                "window_title": "빈 문서 1 - 한글",
                "pid": 1234,
                "path": "",
                "unsaved": True,
                "modified": True,
                "page_count": 3,
                "active": True,
                "visible": True,
            }
        ],
    )
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


def test_insert_paragraph_writes_structured_runs_layout_and_page_break(engine) -> None:
    """빈 문서 재구현은 HWPML 주입 없이 문단·런 공개 사양만으로 조립한다."""
    eng, fake = engine

    out = eng.insert_paragraph(
        runs=[
            {
                "text": "Q. ",
                "bold": True,
                "superscript": True,
                "underline": {
                    "enabled": True,
                    "type": "bottom",
                    "shape": "solid",
                    "color": "#112233",
                },
                "strikeout": {
                    "enabled": True,
                    "type": "continuous",
                    "shape": "solid",
                    "color": "#445566",
                },
                "kerning": True,
                "font": "함초롬돋움",
                "size": 15,
                "letter_spacing_percent": -3,
                "width_scale_percent": 110,
            },
            {"text": "문의 내용", "color": "#112233"},
        ],
        paragraph={
            "align": "justify",
            "first_line_indent_mm": -20.7,
            "line_spacing_percent": 150,
            "break_latin_word": "keep_word",
            "break_non_latin_word": "keep_word",
        },
        page_break_before=True,
    )

    assert out["undo_units"] == 1
    assert out["page_break_before"] is True
    assert ("break_page", None) in fake.calls
    assert (
        "set_paragraph_format",
        {
            "align": "justify",
            "first_line_indent_mm": -20.7,
            "line_spacing_percent": 150.0,
            "break_latin_word": "keep_word",
            "break_non_latin_word": "keep_word",
        },
    ) in fake.calls
    font_call = next(value for name, value in fake.calls if name == "set_font")
    assert font_call["face"] == "함초롬돋움"
    assert font_call["superscript"] is True
    assert font_call["underline"]["color"] == "#112233"
    assert font_call["strikeout"]["type"] == "continuous"
    assert font_call["kerning"] is True
    assert font_call["letter_spacing_percent"] == -3
    assert font_call["width_scale_percent"] == 110
    assert [value for name, value in fake.calls if name == "insert_text"] == ["Q. ", "문의 내용"]
    assert fake.calls.count(("break_paragraph", None)) == 1
    assert load_state().undo_stack == [out["hangul_actions"]]


def test_insert_paragraph_rejects_invalid_structured_specs_before_edit(engine) -> None:
    eng, fake = engine
    with pytest.raises(UsageError, match="text와 runs"):
        eng.insert_paragraph("중복", runs=[{"text": "런"}])
    with pytest.raises(UsageError, match="line_spacing_percent"):
        eng.insert_paragraph(paragraph={"line_spacing_percent": 20})
    with pytest.raises(UsageError, match="letter_spacing_percent"):
        eng.insert_paragraph(runs=[{"text": "런", "letter_spacing_percent": 0.5}])
    with pytest.raises(UsageError, match="break_latin_word"):
        eng.insert_paragraph(paragraph={"break_latin_word": "wrap_anywhere"})
    with pytest.raises(UsageError, match="superscript"):
        eng.insert_paragraph(runs=[{"text": "런", "superscript": "true"}])
    with pytest.raises(UsageError, match="underline.shape"):
        eng.insert_paragraph(runs=[{"text": "런", "underline": {"shape": "wave"}}])
    with pytest.raises(UsageError, match="kerning"):
        eng.insert_paragraph(runs=[{"text": "런", "kerning": 1}])
    assert fake.calls == []


def test_write_cell_replaces_contents_with_structured_paragraphs_in_one_undo_unit(engine) -> None:
    eng, fake = engine

    out = eng.write_cell(
        table=0,
        cell="b2",
        paragraphs=[
            {
                "runs": [{"text": "제목", "bold": True}],
                "paragraph": {"align": "center", "after_spacing_mm": 1.5},
            },
            {"text": "설명", "paragraph": {"line_spacing_percent": 140}},
        ],
    )

    assert out["cell"] == "B2"
    assert out["paragraph_count"] == 2
    assert out["undo_units"] == 1
    assert ("get_into_nth_table", 0) in fake.calls
    assert ("goto_addr", "B2") in fake.calls
    assert ("select_cell_text", None) in fake.calls
    texts = [value for name, value in fake.calls if name == "insert_text"]
    assert texts == ["", "제목", "설명"]
    # 두 문단 사이에만 BreakPara가 있고 셀 끝에 빈 문단을 만들지 않는다.
    assert fake.calls.count(("break_paragraph", None)) == 1
    assert load_state().undo_stack == [out["hangul_actions"]]


def test_write_cell_rejects_bad_target_and_page_break_before_edit(engine) -> None:
    eng, fake = engine
    with pytest.raises(UsageError, match="A1"):
        eng.write_cell(table=0, cell="not-a-cell", paragraphs=[])
    with pytest.raises(UsageError, match="page_break_before"):
        eng.write_cell(
            table=0,
            cell="A1",
            paragraphs=[{"text": "셀", "page_break_before": True}],
        )
    assert fake.calls == []


def test_set_page_number_is_native_canvas_action_and_one_undo_unit(engine) -> None:
    eng, fake = engine
    out = eng.set_page_number(position="bottom_center", separator="-")
    assert out["undo_units"] == 1
    assert ("set_page_number", {"position": "bottom_center", "separator": "-"}) in fake.calls
    assert load_state().undo_stack == [1]


def test_create_table_header_fill_and_default_margin(engine) -> None:
    eng, fake = engine
    eng.create_table(rows=8, cols=4, header_fill="gray")
    assert ("create_table", (8, 4, True)) in fake.calls
    # 새 표 기본 칸 안여백: 좌우 3.5mm, 상하 2.0mm — 방금 만든 표에 적용
    margins = [call for call in fake.calls if call[0] == "set_cell_margin_current"]
    assert len(margins) == 32
    assert margins[0][1] == (3.5, 3.5, 2.0, 2.0)
    assert ("cell_fill", "gray") in fake.calls
    # 다른 표(0번 표)로 이동하지 않아야 한다 (#9 회귀 방지)
    assert not any(c[0] == "get_into_nth_table" for c in fake.calls)
    assert load_state().undo_stack[-1] == 34


def test_create_table_custom_and_disabled_padding(engine) -> None:
    eng, fake = engine
    eng.create_table(rows=2, cols=2, cell_margin="4,3")
    margins = [call for call in fake.calls if call[0] == "set_cell_margin_current"]
    assert len(margins) == 4
    assert margins[0][1] == (4.0, 4.0, 3.0, 3.0)
    fake.calls.clear()
    eng.create_table(rows=2, cols=2, cell_margin="none")
    assert not any(c[0] == "set_cell_margin_current" for c in fake.calls)


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


def test_exit_table_dispatches_without_creating_an_undo_entry(engine) -> None:
    eng, fake = engine

    out = eng.dispatch("exit_table")

    assert out == {
        "ok": True,
        "command": "exit_table",
        "left_table": True,
        "undo_units": 0,
    }
    assert ("exit_table", None) in fake.calls
    assert fake.in_cell is False
    assert load_state().undo_stack == []


def test_layout_review_wrapped_cell_increases_column_width(engine) -> None:
    eng, fake = engine
    out = eng.layout_review(table=0)
    calls = [call for call in fake.calls if call[0] == "set_table_column_width"]
    assert len(calls) == 1
    assert calls[0][1][2] > 50.0
    assert out["tables"][0]["column_changes"][0]["column"] == 1
    assert out["hangul_actions"] >= 1
    assert load_state().undo_stack[-1] == out["hangul_actions"]


def test_layout_review_stops_at_body_width_cap(engine) -> None:
    eng, fake = engine
    fake.layout["max_table_width_mm"] = 100.0
    out = eng.layout_review(table=0)
    assert not any(call[0] == "set_table_column_width" for call in fake.calls)
    assert any("상한" in warning for warning in out["warnings"])


def test_layout_review_dry_run_does_not_change_width(engine) -> None:
    eng, fake = engine
    out = eng.layout_review(table=0, dry_run=True)
    assert out["tables"][0]["column_changes"]
    assert not any(call[0] == "set_table_column_width" for call in fake.calls)
    assert not any(call[0] == "set_table_row_height" for call in fake.calls)
    assert out["undo_units"] == 0
    assert load_state().undo_stack == []


def test_layout_review_warns_when_one_page_becomes_two(engine) -> None:
    eng, fake = engine
    fake.page_counts = [1, 2]
    out = eng.layout_review(table=0)
    assert out["page_count"] == {"before": 1, "after": 2, "changed": True}
    assert any("1쪽에서 2쪽" in warning for warning in out["warnings"])


def test_layout_review_records_successful_actions_before_later_failure(engine) -> None:
    eng, fake = engine
    second = fake.layout["cells"][1]
    second.update(
        {
            "text": "두 번째 열의 아주 긴 내용",
            "line_count": 2,
            "hard_line_count": 1,
            "soft_wrapped": True,
        }
    )
    original = fake.set_table_column_width

    def fail_second(n: int, col: int, width_mm: float) -> int:
        if col == 1:
            raise HangulCommandError("두 번째 열 조절 실패")
        return original(n, col, width_mm)

    fake.set_table_column_width = fail_second  # type: ignore[method-assign]
    with pytest.raises(HangulCommandError):
        eng.layout_review(table=0)
    assert load_state().undo_stack == [1]


def test_layout_plan_never_uses_negative_growth_for_already_wide_column(engine) -> None:
    _, fake = engine
    fake.layout["table_width_mm"] = 60.0
    fake.layout["max_table_width_mm"] = 100.0
    fake.layout["column_widths_mm"] = [50.0, 10.0]
    fake.layout["cells"][1]["soft_wrapped"] = True
    fake.layout["cells"][1]["line_count"] = 2
    plan = plan_table_layout(fake.layout)
    assert plan["target_column_widths_mm"][0] == 50.0
    assert plan["width_planned_mm"] >= plan["width_before_mm"]


def test_undo_replays_hangul_steps(engine) -> None:
    eng, fake = engine
    eng.insert_paragraph("하나")
    eng.create_table(8, 4, header_fill="gray")  # 생성 + 셀별 안여백 32 + 머리행색
    out = eng.undo()
    assert out["hangul_undo_steps"] == 34
    assert fake.undone == 34


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


def test_close_all_requires_force_and_clears_target_after_document_level_closes(engine) -> None:
    eng, _ = engine
    with pytest.raises(DestructiveGuardError):
        eng.close_all(force=False)

    eng.document_closer = lambda: {
        "closed": [{"instance": "!HwpObject.120.1", "document_index": 0}],
        "failures": [],
    }
    eng.document_lister = lambda: []
    out = eng.close_all(force=True)
    assert out["ok"] is True
    assert out["closed_count"] == 1
    assert out["remaining_count"] == 0
    assert load_state().target_hwnd == 0


def test_open_dirty_requires_discard(engine) -> None:
    eng, fake = engine
    fake.modified = True
    with pytest.raises(DestructiveGuardError) as exc:
        eng.open(path=None)
    assert "--discard" in exc.value.message


def test_save_as_refuses_same_path(engine, tmp_path: Path) -> None:
    eng, fake = engine
    dest = tmp_path / "new-parent" / "same.hwp"
    fake.path = str(dest)
    with pytest.raises(DestructiveGuardError):
        eng.save_as(str(dest), overwrite=True)
    assert not dest.parent.exists()
    assert not any(call[0] == "save_as" for call in fake.calls)


def test_save_as_refuses_existing_different_path_without_overwrite(
    engine, tmp_path: Path
) -> None:
    eng, fake = engine
    source = tmp_path / "source.hwp"
    source.write_text("source", encoding="utf-8")
    dest = tmp_path / "existing-other.hwp"
    dest.write_text("must-stay", encoding="utf-8")
    fake.path = str(source)

    with pytest.raises(DestructiveGuardError) as exc:
        eng.save_as(str(dest))

    assert "--overwrite" in exc.value.message
    assert dest.read_text(encoding="utf-8") == "must-stay"
    assert not any(call[0] == "save_as" for call in fake.calls)


def test_save_as_allows_existing_different_path_with_overwrite(
    engine, tmp_path: Path
) -> None:
    eng, fake = engine
    source = tmp_path / "source.hwp"
    source.write_text("source", encoding="utf-8")
    dest = tmp_path / "existing-other.hwp"
    dest.write_text("replace", encoding="utf-8")
    fake.path = str(source)

    out = eng.save_as(str(dest), overwrite=True)

    assert out["overwritten"] is True
    assert ("save_as", (str(dest), "")) in fake.calls


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


def test_open_new_updates_pin_so_followup_writes_succeed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """회귀: pyhwpx 는 ROT 첫 인스턴스(120.1)에 붙고 pin 은 120.2 에 있다.

    라이브(한글 12.0.0.850):
    - !HwpObject.120.1 hwnds [3738628] doc4.hwp  — Hwp(new=False) 가 붙는 쪽
    - !HwpObject.120.2 hwnds [855126, 2100322] — open --new 가 만든 인스턴스
    pin=855126. 다음 명령은 hwnd=855126 으로 120.2 를 골라야 한다.
    """
    monkeypatch.setenv("HWPCTL_LOCK", str(tmp_path / "lock"))
    monkeypatch.setenv("HWPCTL_STATE", str(tmp_path / "state.json"))

    rot_first = FakeCanvas()
    rot_first.hwnd = 3738628
    rot_first.title = "doc4.hwp - 한글"
    rot_first.path = r"C:\docs\doc4.hwp"

    created = FakeCanvas()
    created.hwnd = 855126
    created.title = "빈 문서 2 - 한글"
    created.path = ""

    calls: list[dict] = []

    def factory(new=False, allow_launch=False, hwnd=0):
        calls.append({"new": new, "allow_launch": allow_launch, "hwnd": hwnd})
        if new:
            return created
        if hwnd == created.hwnd:
            return created
        # hwnd 미지정 — pyhwpx/ROT 첫 창 (120.1)
        return rot_first

    eng = Engine(lock_timeout=1, canvas_factory=factory)

    st = eng.status()
    assert st["window_title"] == "doc4.hwp - 한글"
    assert load_state().target_hwnd == 3738628

    out = eng.open(new=True)
    assert out["ok"] is True
    assert out["new"] is True
    assert out["window_title"] == "빈 문서 2 - 한글"
    assert load_state().target_hwnd == 855126
    assert any(c["new"] is True and c["hwnd"] == 0 for c in calls)
    assert not any(name == "new_document" for name, _ in created.calls)

    before = len(calls)
    st2 = eng.status()
    assert st2["window_title"] == "빈 문서 2 - 한글"
    assert calls[before]["hwnd"] == 855126
    assert calls[before]["new"] is False

    created.calls.clear()
    title = eng.insert_title("제목")
    assert title["ok"] is True
    assert any(c[0] == "insert_text" for c in created.calls)
    assert not any(c[0] == "insert_text" for c in rot_first.calls)


def test_open_new_uses_connector_document_and_pins_active_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """open --new는 연결 단계가 만든 문서를 그대로 쓰며 두 번째 FileNew를 하지 않는다."""
    monkeypatch.setenv("HWPCTL_LOCK", str(tmp_path / "lock"))
    monkeypatch.setenv("HWPCTL_STATE", str(tmp_path / "state.json"))

    canvas = FakeCanvas()
    canvas.hwnd = 855126
    canvas.title = "보고서.hwp - 한글"
    factory_calls: list[dict[str, int | bool]] = []

    def factory(new=False, allow_launch=False, hwnd=0):
        factory_calls.append({"new": new, "allow_launch": allow_launch, "hwnd": hwnd})
        if new:
            # Connector가 새 문서를 이미 만들고 활성 창 핸들을 돌려준다.
            canvas.hwnd = 3738628
            canvas.title = "빈 문서 2 - 한글"
            canvas.path = ""
        return canvas

    eng = Engine(lock_timeout=1, canvas_factory=factory)
    eng.status()
    assert load_state().target_hwnd == 855126

    out = eng.open(new=True)
    assert not any(name == "new_document" for name, _ in canvas.calls)
    assert factory_calls[-1] == {"new": True, "allow_launch": True, "hwnd": 0}
    assert load_state().target_hwnd == 3738628
    assert out["window_title"] == "빈 문서 2 - 한글"


def test_open_without_new_still_creates_one_document(engine) -> None:
    eng, fake = engine
    out = eng.open()
    assert out["new"] is False
    assert [call for call in fake.calls if call[0] == "new_document"] == [("new_document", None)]


def test_open_path_moves_pin_when_document_handle_changes(engine) -> None:
    """open <path> 가 다른 창/문서로 바뀌면 pin 도 그 핸들을 따른다."""
    eng, fake = engine
    eng.status()
    assert load_state().target_hwnd == 1111
    orig_open = fake.open_path

    def open_and_switch(path: str) -> None:
        orig_open(path)
        fake.hwnd = 2222
        fake.title = "새파일.hwp - 한글"

    fake.open_path = open_and_switch  # type: ignore[method-assign]
    out = eng.open(path=r"C:\docs\새파일.hwp", discard=True)
    assert out["path"] == r"C:\docs\새파일.hwp"
    assert load_state().target_hwnd == 2222
    eng.insert_paragraph("본문")
    assert any(c[0] == "insert_text" for c in fake.calls)


def test_followup_still_rejects_unpinned_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """안전장치: 우리가 연 창이 아닌 다른 창에는 여전히 쓰지 않는다."""
    monkeypatch.setenv("HWPCTL_LOCK", str(tmp_path / "lock"))
    monkeypatch.setenv("HWPCTL_STATE", str(tmp_path / "state.json"))

    pinned = FakeCanvas()
    pinned.hwnd = 3738628
    other = FakeCanvas()
    other.hwnd = 855126

    def factory(new=False, allow_launch=False, hwnd=0):
        if new or hwnd == pinned.hwnd:
            return pinned
        return other

    eng = Engine(lock_timeout=1, canvas_factory=factory)
    eng.open(new=True)
    assert load_state().target_hwnd == 3738628

    def rogue_factory(new=False, allow_launch=False, hwnd=0):
        return other  # ROT 첫 창에 붙어 버린 상황

    eng.canvas_factory = rogue_factory
    with pytest.raises(HangulCommandError) as exc:
        eng.insert_paragraph("비밀")
    assert "다른 창" in exc.value.message
    assert not any(c[0] == "insert_text" for c in other.calls)


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


def test_list_documents_is_global_read_only_status(engine) -> None:
    eng, fake = engine
    out = eng.list_documents()
    assert out == {
        "ok": True,
        "command": "list_documents",
        "read_only": True,
        "count": 1,
        "documents": [
            {
                "instance": "!HwpObject.120.9",
                "document_index": 0,
                "window_handle": 9999,
                "window_title": "빈 문서 1 - 한글",
                "pid": 1234,
                "path": "",
                "unsaved": True,
                "modified": True,
                "page_count": 3,
                "active": True,
                "visible": True,
            }
        ],
    }
    # 대상 문서 고정·커서 이동을 위해 캔버스에 붙지 않는다.
    assert fake.calls == []
    assert load_state().target_hwnd == 0


def test_set_cell_margin_whole_table(engine) -> None:
    eng, fake = engine
    out = eng.set_cell_margin(table=0)
    assert ("get_into_nth_table", 0) in fake.calls
    margins = [call for call in fake.calls if call[0] == "set_cell_margin_current"]
    assert len(margins) == 2
    assert margins[0][1] == (3.5, 3.5, 2.0, 2.0)
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


def test_set_col_width_mm_and_ratio(engine) -> None:
    eng, fake = engine
    out = eng.set_col_width("30,70", table=0, unit="mm")
    assert out["widths_mm"] == [30.0, 70.0]
    assert [c[1] for c in fake.calls if c[0] == "set_col_width_current"] == [30.0, 70.0]
    assert load_state().undo_stack[-1] == 2

    fake.calls.clear()
    out = eng.set_col_width([1, 3], table=0, unit="ratio")
    assert out["widths_mm"] == [25.0, 75.0]
    assert [c[1] for c in fake.calls if c[0] == "set_col_width_current"] == [25.0, 75.0]


def test_set_col_width_rejects_bad_ratio(engine) -> None:
    eng, _ = engine
    with pytest.raises(UsageError):
        eng.set_col_width([1], table=0, unit="ratio")
    with pytest.raises(UsageError):
        eng.set_col_width([1, 2], table=0, column=1, unit="ratio")


def test_get_col_width_current_and_table(engine) -> None:
    eng, _ = engine
    current = eng.get_col_width()
    assert current["width_mm"] == 50.0
    all_columns = eng.get_col_width(table=0)
    assert all_columns["widths_mm"] == [50.0, 50.0]
    assert load_state().undo_stack == []


def test_set_and_get_row_height(engine) -> None:
    eng, fake = engine
    out = eng.set_row_height(12.5, table=0, row=1)
    assert out["height_mm"] == 12.5
    assert ("set_row_height_current", 12.5) in fake.calls
    assert load_state().undo_stack[-1] == 1
    read = eng.get_row_height(table=0, row=1)
    assert read["height_mm"] == 10.0


def test_merge_cells_and_undo(engine) -> None:
    eng, fake = engine
    out = eng.merge_cells("A1:B2", table=0)
    assert ("merge_cells", ("A1", "B2")) in fake.calls
    assert out["undo_units"] == 1
    assert load_state().undo_stack[-1] == 1
    with pytest.raises(UsageError):
        eng.merge_cells("A1", table=0)


def test_set_valign_table_walks_each_cell(engine) -> None:
    eng, fake = engine
    out = eng.set_valign("bottom", table=0)
    assert out["vert_align"] == 2
    calls = [c for c in fake.calls if c[0] == "set_valign_current"]
    assert len(calls) == 2
    assert load_state().undo_stack[-1] == 2


def test_set_cell_border_range_and_rejects_type_horz(engine) -> None:
    eng, fake = engine
    out = eng.set_cell_border(
        sides="left,bottom",
        color="#112233",
        table=0,
        cell_range="A1:B1",
    )
    calls = [c[1] for c in fake.calls if c[0] == "set_cell_border_current"]
    assert len(calls) == 2
    assert calls[0]["sides"] == ["left", "bottom"]
    assert out["hangul_actions"] == 2
    with pytest.raises(UsageError) as exc:
        eng.set_cell_border(sides="horizontal", table=0)
    assert "TypeHorz" in exc.value.message


def test_set_style_named_style_records_undo(engine) -> None:
    eng, fake = engine
    out = eng.set_style("개요 1")
    assert ("set_style", "개요 1") in fake.calls
    assert out["undo_units"] == 1
    assert load_state().undo_stack[-1] == 1


def test_set_pagedef_and_page_break(engine) -> None:
    eng, fake = engine
    out = eng.set_pagedef(
        paper_width=210,
        paper_height=297,
        left=20,
        right=20,
        landscape=True,
    )
    assert out["landscape"] is True
    call = next(c[1] for c in fake.calls if c[0] == "set_pagedef")
    assert call["paper_width"] == 210
    assert call["left"] == 20
    assert load_state().undo_stack[-1] == 1

    fake.calls.clear()
    page = eng.page(break_page=True)
    assert ("break_page", None) in fake.calls
    assert page["page_count"] == 2
    assert page["undo_units"] == 1
    with pytest.raises(UsageError):
        eng.page(goto=2, break_page=True)


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


def test_format_paragraph_by_text_validates_then_formats_one_normal_body_paragraph(engine) -> None:
    eng, fake = engine
    text = " ◦ 본문 한 문단입니다. "

    check = eng.format_paragraph_by_text(text=text, dry_run=True)
    assert check["dry_run"] is True
    assert check["matched"] == text
    assert check["undo_units"] == 0
    assert not any(name == "set_font" for name, _value in fake.calls)

    fake.calls.clear()
    out = eng.format_paragraph_by_text(
        text=text,
        font="휴먼명조",
        size=15,
        bold=False,
        paragraph={
            "align": "justify",
            "first_line_indent_mm": -21.3,
            "line_spacing_percent": 155,
            "break_latin_word": "keep_word",
            "break_non_latin_word": "keep_word",
        },
    )

    assert out["undo_units"] == 1
    assert ("select_exact_body_paragraph", (text, 1)) in fake.calls
    font_call = [value for name, value in fake.calls if name == "set_font"][0]
    assert font_call["face"] == "휴먼명조"
    assert font_call["height_pt"] == 15
    paragraph_call = [value for name, value in fake.calls if name == "set_paragraph_format"][0]
    assert paragraph_call["line_spacing_percent"] == 155
    assert ("set_pos", (0, 3, 7)) in fake.calls
    assert any(name == "restore_selection" for name, _value in fake.calls)


def test_format_paragraph_by_text_rejects_multiline_or_empty_format(engine) -> None:
    eng, fake = engine
    with pytest.raises(UsageError, match="줄바꿈"):
        eng.format_paragraph_by_text(text="한 문단\n다음 문단", dry_run=True)
    with pytest.raises(UsageError, match="적용할"):
        eng.format_paragraph_by_text(text="본문")
    assert fake.calls == []


def test_recreate_inline_table_before_paragraph_rebuilds_without_cut_or_clipboard(engine) -> None:
    eng, fake = engine
    question = "Q. 지원 제외되는 업종이 있나요? 업종과 무관하게 신청할 수 있나요?"
    answer = " ◦ 소상공인 정책자금 지원 제외 업종의 경우 신청 불가합니다."
    fake.selected = question
    fake.create_enters_cell = True
    table_spec = {
        "kind": "table",
        "rows": 1,
        "cols": 1,
        "column_widths_mm": [168.991139],
        "row_heights_mm": [16.178389],
        "merges": [],
        "exit_cell": "A1",
        "cells": {
            "A1": {
                "paragraphs": [
                    {
                        "paragraph": {"align": "justify", "line_spacing_percent": 150},
                        "runs": [
                            {"text": "Q. ", "font": "맑은 고딕", "size": 15, "bold": True},
                            {"text": question[3:], "font": "맑은 고딕", "size": 15, "bold": True},
                        ],
                    }
                ],
                "margin_mm": [1.799167, 1.799167, 0.497417, 0.497417],
                "valign": "center",
                "borders": [
                    {
                        "sides": "left,right,top,bottom",
                        "line_type": "Solid",
                        "width": "0.12mm",
                        "color": "#000000",
                    }
                ],
                "fill": "#FFF7CC",
            }
        },
        "position": {
            "mode": "inline",
            "affect_line_spacing": False,
            "outside_margin_mm": [0.493889, 0.493889, 0.493889, 0.493889],
            "horizontal_relative_to": "paragraph",
        },
        "properties": {"repeat_header": True, "page_break": "cell", "cell_spacing_mm": 0},
    }
    blank = {
        "kind": "paragraph",
        "paragraph": {"align": "justify", "line_spacing_percent": 155},
        "runs": [{"text": "", "font": "휴먼명조", "size": 10, "color": "#0000FF"}],
    }

    check = eng.recreate_inline_table_before_paragraph(
        old_table=0,
        expected_table_text=question,
        before_text=answer,
        table_spec=table_spec,
        blank_paragraph=blank,
        dry_run=True,
    )
    assert check["dry_run"] is True
    assert not any(name == "create_table" for name, _value in fake.calls)

    fake.calls.clear()
    out = eng.recreate_inline_table_before_paragraph(
        old_table=0,
        expected_table_text=question,
        before_text=answer,
        table_spec=table_spec,
        blank_paragraph=blank,
    )
    assert out["undo_units"] == 1
    assert ("create_table", (1, 1, False)) in fake.calls
    assert ("delete_table_control", None) in fake.calls
    assert len([c for c in fake.calls if c[0] == "ensure_blank_paragraph_before_body"]) == 2
    assert not any(value in {"InternalCut", "InternalPaste"} for name, value in fake.calls if name == "run")
    assert any(name == "set_current_table_properties" for name, _value in fake.calls)
    assert any(name == "set_current_inline_table_position" for name, _value in fake.calls)
    assert any(name == "set_paragraph_format" for name, _value in fake.calls)


def test_recreate_inline_table_before_paragraph_rejects_nonempty_blank_source(engine) -> None:
    eng, fake = engine
    table_spec = {
        "rows": 1,
        "cols": 1,
        "column_widths_mm": [100],
        "row_heights_mm": [10],
        "cells": {
            "A1": {
                "paragraphs": [{"runs": [{"text": "Q."}]}],
                "margin_mm": [1, 1, 1, 1],
                "valign": "center",
                "borders": [
                    {
                        "sides": "all",
                        "line_type": "Solid",
                        "width": "0.12mm",
                        "color": "#000000",
                    }
                ],
                "fill": "#FFFFFF",
            }
        },
        "position": {"mode": "inline"},
        "properties": {"page_break": "cell", "repeat_header": True, "cell_spacing_mm": 0},
    }
    with pytest.raises(UsageError, match="텍스트는 모두 비어"):
        eng.recreate_inline_table_before_paragraph(
            old_table=0,
            expected_table_text="Q.",
            before_text="답변",
            table_spec=table_spec,
            blank_paragraph={"runs": [{"text": "빈 문단이 아님"}]},
        )
    assert fake.calls == []


def test_trim_blank_paragraphs_before_body_removes_only_excess_enter(engine) -> None:
    eng, fake = engine
    answer = " ◦ 답변 문단"
    fake.blank_paragraph_count = 2

    check = eng.trim_blank_paragraphs_before_body(answer, keep=1, dry_run=True)
    assert check["before"] == 2
    assert check["remove"] == 1
    assert not any(name == "remove_empty_paragraph_immediately_before_body" for name, _ in fake.calls)

    fake.calls.clear()
    out = eng.trim_blank_paragraphs_before_body(answer, keep=1)
    assert out["removed"] == 1
    assert out["remaining"] == 1
    assert out["undo_units"] == 1
    assert fake.blank_paragraph_count == 1
    assert ("remove_empty_paragraph_immediately_before_body", answer) in fake.calls


def test_trim_blank_paragraphs_before_body_refuses_to_invent_missing_enter(engine) -> None:
    eng, fake = engine
    fake.blank_paragraph_count = 0
    with pytest.raises(HangulCommandError, match="빈 문단이 0개"):
        eng.trim_blank_paragraphs_before_body("답변", keep=1)
    assert not any(name == "remove_empty_paragraph_immediately_before_body" for name, _ in fake.calls)


def test_set_format_range_applies_only_requested_cells(engine) -> None:
    """회귀 방지(#12): A1:B2 는 4칸 전부, 행 전체 확대 없이 요청 칸만."""
    eng, fake = engine
    eng.set_format(fill="gray", table=0, cell_range="A1:B2")
    addrs = [c[1] for c in fake.calls if c[0] == "goto_addr"]
    assert addrs == ["A1", "B1", "A2", "B2"]
    assert len([c for c in fake.calls if c[0] == "cell_fill"]) == 4
    assert not any(c[0] == "select_row" for c in fake.calls)


def test_insert_text_box_dispatches_normalized_visual_specs_and_undo(engine) -> None:
    """새 공개 글상자 명령은 COM 세부값이 아닌 정규화된 사양만 어댑터로 넘긴다."""
    eng, fake = engine
    out = eng.dispatch(
        "insert_text_box",
        text="문의 안내",
        width_mm=118,
        height_mm=23.5,
        fill={
            "type": "linear_gradient",
            "angle": 90,
            "stops": [
                {"offset": 0, "color": "#004A99"},
                {"offset": 1, "color": "#00A7C6"},
            ],
        },
        line={"type": "solid", "color": "#113355", "width_mm": 0.3},
        shadow={
            "type": "offset",
            "color": "#000000",
            "alpha": 96,
            "offset_x_mm": 1,
            "offset_y_mm": -1,
        },
        text_shadow={
            "type": "offset",
            "color": "#101010",
            "alpha": 0,
            "offset_x_mm": 0.5,
            "offset_y_mm": 0,
        },
        position={"mode": "floating", "x_mm": 10, "y_mm": 20},
        bold=True,
        font="함초롬돋움",
        size=16,
        color="#FFFFFF",
    )

    call = next(value for name, value in fake.calls if name == "insert_text_box")
    assert call["text"] == "문의 안내"
    assert call["width_mm"] == 118.0
    assert call["height_mm"] == 23.5
    assert call["fill"] == {
        "type": "linear_gradient",
        "angle": 90.0,
        "stops": [
            {"offset": 0.0, "color": "#004A99"},
            {"offset": 1.0, "color": "#00A7C6"},
        ],
    }
    assert call["line"] == {"type": "solid", "color": "#113355", "width_mm": 0.3}
    assert call["shadow"]["alpha"] == 96.0
    assert call["text_shadow"]["alpha"] == 0
    assert call["margin"] is None  # 기본은 지원되지 않는 여백 쓰기를 요청하지 않는다.
    assert call["position"] == {"mode": "floating", "x_mm": 10.0, "y_mm": 20.0}
    assert call["color"] == "#FFFFFF"
    assert out["undo_units"] == 1
    assert out["hangul_actions"] == fake.text_box_actions
    assert load_state().undo_stack == [fake.text_box_actions]

    undone = eng.undo()
    assert undone["hangul_undo_steps"] == fake.text_box_actions
    assert fake.undone == fake.text_box_actions


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "fill",
            {
                "type": "linear_gradient",
                "angle": 90,
                "stops": [
                    {"offset": index / 10, "color": "#123456"}
                    for index in range(11)
                ],
            },
            "최대 10개",
        ),
        (
            "line",
            {"type": "solid", "color": "#123456", "width_mm": 0.13},
            "지원값",
        ),
        (
            "text_shadow",
            {"type": "offset", "color": "#000000", "alpha": 1},
            "지원되지 않습니다",
        ),
    ],
)
def test_insert_text_box_rejects_unsupported_public_visual_specs(
    engine, field, value, message
) -> None:
    eng, fake = engine
    with pytest.raises(UsageError, match=message):
        eng.insert_text_box("안내", width_mm=100, height_mm=20, **{field: value})
    assert not any(name == "insert_text_box" for name, _value in fake.calls)


def test_set_cell_fill_propagates_solid_and_gradient_with_actual_undo_counts(engine) -> None:
    eng, fake = engine

    solid = eng.set_cell_fill("#123456", table=0, cell_range="A1:B1")
    solid_calls = [value for name, value in fake.calls if name == "set_cell_fill"]
    assert solid_calls == [
        {"type": "solid", "color": "#123456"},
        {"type": "solid", "color": "#123456"},
    ]
    assert solid["hangul_actions"] == 2
    assert load_state().undo_stack == [2]
    eng.undo()
    assert fake.undone == 2

    fake.calls.clear()
    gradient = eng.set_cell_fill(
        {
            "type": "linear_gradient",
            "angle": 450,
            "stops": ["#112233", "#AABBCC"],
        }
    )
    gradient_call = next(value for name, value in fake.calls if name == "set_cell_fill")
    assert gradient_call == {
        "type": "linear_gradient",
        "angle": 90.0,
        "stops": [
            {"offset": 0.0, "color": "#112233"},
            {"offset": 1.0, "color": "#AABBCC"},
        ],
    }
    assert gradient["hangul_actions"] == 1
    assert load_state().undo_stack == [1]


def test_set_cell_fill_normalizes_radial_gradient_before_canvas_call(engine) -> None:
    eng, fake = engine

    out = eng.set_cell_fill(
        {
            "type": "radial_gradient",
            "angle": 0,
            "center_x": 50,
            "center_y": 0,
            "step": 100,
            "step_center": 50,
            "stops": ["#EAFFFC", "#FF843A"],
        },
        table=0,
        cell_range="A1",
    )

    payload = next(value for name, value in fake.calls if name == "set_cell_fill")
    assert payload["type"] == "radial_gradient"
    assert payload["center_x"] == 50
    assert payload["center_y"] == 0
    assert payload["step"] == 100
    assert payload["step_center"] == 50
    assert out["hangul_actions"] == 1
    with pytest.raises(UsageError, match="0~100 정수"):
        eng.set_cell_fill(
            {
                "type": "radial_gradient",
                "stops": ["#000000", "#FFFFFF"],
                "center_x": 12.5,
            },
            table=0,
            cell_range="A1",
        )


def test_set_format_keeps_solid_compatibility_and_uses_gradient_adapter(engine) -> None:
    eng, fake = engine
    eng.set_format(fill="#112233", table=0)
    assert ("cell_fill", "#112233") in fake.calls
    assert not any(name == "set_cell_fill" for name, _value in fake.calls)

    fake.calls.clear()
    eng.set_format(
        fill={
            "type": "linear_gradient",
            "angle": 0,
            "stops": ["#112233", "#445566"],
        },
        table=0,
    )
    assert not any(name == "cell_fill" for name, _value in fake.calls)
    assert next(value for name, value in fake.calls if name == "set_cell_fill") == {
        "type": "linear_gradient",
        "angle": 0.0,
        "stops": [
            {"offset": 0.0, "color": "#112233"},
            {"offset": 1.0, "color": "#445566"},
        ],
    }


def test_set_format_propagates_text_shadow_and_rejects_nonzero_alpha(engine) -> None:
    eng, fake = engine
    eng.set_format(
        font="함초롬돋움",
        text_shadow={
            "type": "offset",
            "color": "#102030",
            "alpha": 0,
            "offset_x_mm": 0.4,
            "offset_y_mm": 0.2,
        },
    )
    font_call = next(value for name, value in fake.calls if name == "set_font")
    assert font_call["text_shadow"] == {
        "type": "offset",
        "color": "#102030",
        "alpha": 0,
        "offset_x_mm": 0.4,
        "offset_y_mm": 0.2,
    }

    with pytest.raises(UsageError, match="지원되지 않습니다"):
        eng.set_format(text_shadow={"type": "offset", "color": "#000000", "alpha": 12})


def test_set_format_range_with_row_rejected(engine) -> None:
    eng, _ = engine
    with pytest.raises(UsageError):
        eng.set_format(fill="gray", table=0, cell_range="A1:B1", row=1)


def test_table_properties_are_public_validated_and_one_undo_unit(engine) -> None:
    eng, fake = engine

    out = eng.dispatch(
        "set_table_properties",
        table=0,
        page_break="table",
        repeat_header=False,
        cell_spacing_mm=0.5,
    )

    assert out["page_break"] == "table"
    assert out["repeat_header"] is False
    assert out["cell_spacing_mm"] == 0.5
    assert out["undo_units"] == 1
    assert ("set_table_properties", {
        "table": 0,
        "page_break": "table",
        "repeat_header": False,
        "cell_spacing_mm": 0.5,
    }) in fake.calls
    assert load_state().undo_stack == [1]

    with pytest.raises(UsageError, match="page_break"):
        eng.set_table_properties(table=0, page_break="paragraph")
    with pytest.raises(UsageError, match="repeat_header"):
        eng.set_table_properties(table=0, repeat_header=1)  # type: ignore[arg-type]
    with pytest.raises(UsageError, match="0~50"):
        eng.set_table_properties(table=0, cell_spacing_mm=50.1)


def test_table_position_keeps_json_layout_and_one_undo_unit(engine) -> None:
    eng, fake = engine
    position = {
        "mode": "floating",
        "horizontal_relative_to": "para",
        "vertical_relative_to": "para",
        "horizontal_align": "left",
        "vertical_align": "top",
        "x_mm": 0.024694,
        "y_mm": 1.608667,
        "wrap": "top_and_bottom",
        "flow_with_text": True,
        "allow_overlap": False,
        "outside_margin_mm": [0.493889, 0.493889, 0.493889, 0.493889],
    }

    out = eng.set_table_position(table=0, position=position)

    assert out["position"] == position
    assert out["undo_units"] == 1
    assert ("set_table_position", {"table": 0, "position": position}) in fake.calls
    assert load_state().undo_stack == [1]
    with pytest.raises(UsageError, match="floating"):
        eng.set_table_position(table=0, position={"mode": "floating", "x_mm": 0, "y_mm": 0})


def test_page_visibility_and_restart_are_native_one_undo_commands(engine) -> None:
    eng, fake = engine

    hidden = eng.set_page_visibility(hide_page_num=True)
    restarted = eng.restart_page_number(number=1)

    assert hidden["undo_units"] == 1
    assert restarted["undo_units"] == 1
    assert ("set_page_visibility", {
        "hide_header": False,
        "hide_footer": False,
        "hide_master_page": False,
        "hide_border": False,
        "hide_fill": False,
        "hide_page_num": True,
    }) in fake.calls
    assert ("restart_page_number", {"number": 1}) in fake.calls
    assert load_state().undo_stack == [1, 1]
    with pytest.raises(UsageError, match="1~999999"):
        eng.restart_page_number(number=0)


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
