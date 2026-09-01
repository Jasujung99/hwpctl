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
        self.created_shape = (rows, cols)
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

    def break_page(self) -> None:
        self.calls.append(("break_page", None))

    def set_pagedef(self, **kwargs) -> None:
        self.calls.append(("set_pagedef", kwargs))

    def set_style(self, style) -> None:
        self.calls.append(("set_style", style))


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Engine, FakeCanvas]:
    fake = FakeCanvas()
    monkeypatch.setenv("HWPCTL_LOCK", str(tmp_path / "lock"))
    monkeypatch.setenv("HWPCTL_STATE", str(tmp_path / "state.json"))
    eng = Engine(
        lock_timeout=1,
        canvas_factory=lambda new=False, allow_launch=False, hwnd=0: fake,
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