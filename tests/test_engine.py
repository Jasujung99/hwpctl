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

    def window_handle(self) -> int:
        return self.hwnd

    def has_selection(self) -> bool:
        return self.selection_active

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

        return DocInfo(
            window_title="빈 문서 1 - 한글",
            path=self.path,
            modified=self.modified,
            page=1,
            page_count=2,
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


def test_create_table_header_fill(engine) -> None:
    eng, fake = engine
    eng.create_table(rows=8, cols=4, header_fill="gray")
    assert ("create_table", (8, 4, True)) in fake.calls
    assert ("cell_fill", "gray") in fake.calls
    assert load_state().undo_stack[-1] == 2


def test_fill_cells_grid(engine) -> None:
    eng, fake = engine
    eng.fill_cells(table=0, cells=[["항목", "내용"]])
    addrs = [c[1] for c in fake.calls if c[0] == "goto_addr"]
    assert "A1" in addrs and "B1" in addrs
    assert load_state().undo_stack[-1] == 2


def test_undo_replays_hangul_steps(engine) -> None:
    eng, fake = engine
    eng.insert_paragraph("하나")
    eng.create_table(8, 4, header_fill="gray")
    out = eng.undo()
    assert out["hangul_undo_steps"] == 2
    assert fake.undone == 2


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