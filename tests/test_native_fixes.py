"""Regression tests for native-object defects measured on Hancom Office 2022."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hwpctl import native_objects
from hwpctl.engine import Engine
from hwpctl.hangul import HangulCanvas
from hwpctl.lock import load_state


class _Anchor:
    def __init__(self, pos: tuple[int, int, int]) -> None:
        self.pos = pos

    def Item(self, name: str) -> int:
        return dict(zip(("List", "Para", "Pos"), self.pos))[name]


class _SnappingCanvas:
    """SetPosBySet on an anchor lands right after the control, at document end."""

    def __init__(self) -> None:
        self.pos = (0, 0, 0)
        self.moves: list[str] = []
        self.com = SimpleNamespace(SetPosBySet=self._set_by_set)

    def _set_by_set(self, anchor: _Anchor) -> None:
        self.pos = (anchor.pos[0], anchor.pos[1], anchor.pos[2] + 8)

    def get_pos(self):
        return self.pos

    def set_pos(self, pos) -> bool:
        return False  # past the end of the last paragraph

    def run(self, name: str) -> bool:
        self.moves.append(name)
        return False  # MoveRight has nowhere to go at the document end


def test_after_control_accepts_caret_already_after_the_control() -> None:
    canvas = _SnappingCanvas()
    ctrl = SimpleNamespace(GetAnchorPos=lambda _index: _Anchor((0, 0, 16)))
    native_objects.after_control(canvas, ctrl)
    assert canvas.pos == (0, 0, 24)
    assert canvas.moves == []


class _PSet:
    def __init__(self) -> None:
        self.items: dict[str, object] = {}
        self.children: dict[str, "_PSet"] = {}
        self.arrays: dict[str, list[int]] = {}

    def SetItem(self, name: str, value) -> None:
        self.items[name] = value

    def CreateItemSet(self, name: str, _kind: str) -> "_PSet":
        return self.children.setdefault(name, _PSet())

    def CreateItemArray(self, name: str, size: int):
        values = self.arrays.setdefault(name, [0] * size)
        return SimpleNamespace(SetItem=values.__setitem__)


@pytest.mark.parametrize("line", [False, True])
def test_creation_geometry_sets_absolute_size_and_points(line: bool) -> None:
    """Without these Hancom 2022 creates a 1 mm degenerate text box."""
    pset = _PSet()
    native_objects.apply_creation_geometry(pset, 1000, 400, line=line)
    assert pset.items["WidthRelTo"] == 4 and pset.items["HeightRelTo"] == 2
    layout = pset.children["ShapeDrawLayOut"]
    expected = [0, 0, 1000, 400] if line else [0, 0, 1000, 0, 1000, 400, 0, 400]
    assert pset.arrays == {} and layout.arrays["CreatePt"] == expected
    assert layout.items["CreateNumPt"] == len(expected) // 2


def test_insert_picture_passes_millimetres_not_hwpunits() -> None:
    calls = []

    class Com:
        def InsertPicture(self, *args):
            calls.append(args)
            return SimpleNamespace(CtrlID="gso")

    canvas = HangulCanvas(px=None, com=Com(), backend="win32com")
    canvas.assert_no_dialog = lambda: None
    canvas.insert_picture("x.emf", size_option=1, width_mm=100.5, height_mm=56.25)
    assert calls[0][6:] == (100.5, 56.25)


class _ImageCanvas:
    def __init__(self) -> None:
        self.undone = 0

    def is_cell(self) -> bool:
        return False

    def insert_picture(self, *_args, **_kwargs):
        return SimpleNamespace(CtrlID="gso")

    def undo_once(self) -> None:
        self.undone += 1


@pytest.fixture()
def image_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("HWPCTL_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("HWPCTL_LOCK", str(tmp_path / "writer.lock"))
    canvas = _ImageCanvas()
    eng = Engine()
    monkeypatch.setattr(eng, "_connect", lambda **_kwargs: canvas)
    monkeypatch.setattr(native_objects, "position_control", lambda *_args: None)
    picture = tmp_path / "art.emf"
    picture.write_bytes(b"emf")
    return eng, canvas, picture


@pytest.mark.parametrize(("position", "steps"), [
    (None, 2),
    ({"mode": "floating", "x_mm": 1, "y_mm": 2, "wrap": "behind_text"}, 3),
])
def test_insert_image_records_measured_undo_steps(image_engine, position, steps) -> None:
    eng, canvas, picture = image_engine
    eng.insert_image(str(picture), size_option=1, width_mm=10, height_mm=10, position=position)
    assert load_state().undo_stack == [steps]
    eng.undo()
    assert canvas.undone == steps


class _RunCanvas:
    def __init__(self) -> None:
        self.fonts: list[dict] = []
        self.inserted: list[str] = []

    def set_font(self, **kwargs) -> int:
        self.fonts.append(kwargs)
        return 1

    def insert_text(self, text: str) -> None:
        self.inserted.append(text)

    def break_paragraph(self) -> None:
        pass

    def set_paragraph_format(self, **_kwargs) -> None:
        pass


def _spec(runs):
    from hwpctl.engine import _normalize_paragraph_spec

    return _normalize_paragraph_spec(text="", runs=runs, paragraph=None, page_break_before=False)


def test_runs_do_not_inherit_width_scale_or_bold_from_previous_run() -> None:
    canvas = _RunCanvas()
    Engine._write_paragraph_spec(canvas, _spec([
        {"text": "11.01.", "size": 45},
        {"text": " ", "width_scale_percent": 50, "bold": True},
        {"text": "Sat", "size": 45},
    ]), terminate=False, actions=[0])
    assert canvas.fonts[1]["width_scale_percent"] == 50 and canvas.fonts[1]["bold"] is True
    # The third run leaves both unspecified: Hangul would keep 50%/bold, so reset them.
    assert canvas.fonts[2]["width_scale_percent"] == 100
    assert canvas.fonts[2]["bold"] is False


def test_sticky_reset_spans_paragraphs_of_one_writer_and_skips_untouched_attributes() -> None:
    canvas = _RunCanvas()
    sticky: set[str] = set()
    Engine._write_paragraph_spec(canvas, _spec([{"text": "a", "letter_spacing_percent": 10}]),
                                 terminate=True, actions=[0], sticky=sticky)
    Engine._write_paragraph_spec(canvas, _spec([{"text": "b", "size": 12}]),
                                 terminate=False, actions=[0], sticky=sticky)
    assert canvas.fonts[1]["letter_spacing_percent"] == 0
    assert canvas.fonts[1]["width_scale_percent"] is None  # never changed, so still inherited
    assert canvas.fonts[1]["bold"] is None


def test_text_box_records_content_actions_reported_by_the_adapter(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HWPCTL_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("HWPCTL_LOCK", str(tmp_path / "writer.lock"))

    class Canvas(_RunCanvas):
        def insert_text_box(self, **kwargs) -> int:
            # create + edit mode + whatever the content writer executed
            return 2 + kwargs["content_writer"]()

    canvas = Canvas()
    eng = Engine()
    monkeypatch.setattr(eng, "_connect", lambda **_kwargs: canvas)
    eng.insert_text_box("", width_mm=40, height_mm=10, paragraphs=[
        {"runs": [{"text": "A", "bold": True}, {"text": "B"}]},
        {"text": "C"},
    ])
    # paragraph 1: font+text, font(reset bold)+text, break; paragraph 2: text
    assert load_state().undo_stack == [2 + 6]


def test_text_box_first_paragraph_format_merges_with_box_alignment(tmp_path, monkeypatch) -> None:
    """Consecutive ParagraphShape edits of one paragraph are one Hangul Undo step."""
    monkeypatch.setenv("HWPCTL_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("HWPCTL_LOCK", str(tmp_path / "writer.lock"))

    class Canvas(_RunCanvas):
        def insert_text_box(self, **kwargs) -> int:
            return 3 + kwargs["content_writer"]()  # create + edit mode + box alignment

    canvas = Canvas()
    eng = Engine()
    monkeypatch.setattr(eng, "_connect", lambda **_kwargs: canvas)
    eng.insert_text_box("", width_mm=40, height_mm=10, paragraphs=[
        {"runs": [{"text": "A"}], "paragraph": {"align": "left"}},
    ])
    # paragraph format (merged, 0) + text (1): same as the live measurement (4 steps)
    assert load_state().undo_stack == [4]
