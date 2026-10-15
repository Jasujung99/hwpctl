"""insert_text_art 공개 도구·작성 명세·변환기 계약 (한/글 없이 실행)."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from types import SimpleNamespace
import zipfile

import anyio
import pytest

from hwpctl import native_objects
from hwpctl.authoring.converter import reference_to_spec
from hwpctl.authoring.model import SCHEMA
from hwpctl.authoring.runtime import build_document
from hwpctl.cli import _kwargs_for
from hwpctl.engine import Engine, _normalize_fill, _normalize_text_art
from hwpctl.errors import HangulCommandError, UsageError
from hwpctl.hangul import HangulCanvas
from hwpctl.lock import load_state
from hwpctl.mcp_server import build_mcp
from hwpctl.parser import parse_args
from hwpctl.units import mm_to_hwpunit

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "textart"


# --------------------------------------------------------------------------- COM doubles


class FakeSet:
    """ParameterSet double. ``Item`` returns a COPY of child sets, like Hangul automation."""

    def __init__(self, set_id: str = "", items: dict | None = None) -> None:
        self.SetID = set_id
        self.items = dict(items or {})
        self.arrays: dict[str, list[int]] = {}

    def ItemExist(self, name: str) -> bool:
        return name in self.items

    def Item(self, name: str):
        value = self.items[name]
        return copy.deepcopy(value) if isinstance(value, FakeSet) else value

    def SetItem(self, name: str, value) -> None:
        self.items[name] = value

    def CreateItemSet(self, name: str, set_id: str) -> "FakeSet":
        child = FakeSet(set_id)
        self.items[name] = child
        return child

    def CreateItemArray(self, name: str, size: int):
        values = [0] * size
        self.arrays[name] = values
        return SimpleNamespace(SetItem=values.__setitem__)


class FakeCtrl:
    CtrlID = "gso"
    UserDesc = "글맵시"

    def __init__(self) -> None:
        self._props = FakeSet("ShapeObject", {"Width": 20500, "Height": 5000})
        self.assigned = 0

    def GetAnchorPos(self, _index):
        return object()

    @property
    def Properties(self):
        return copy.deepcopy(self._props)

    @Properties.setter
    def Properties(self, value) -> None:
        self._props = value
        self.assigned += 1


class FakeAction:
    def __init__(self, name: str, com: "FakeCom") -> None:
        self.name, self.com = name, com

    def CreateSet(self) -> FakeSet:
        if self.name == "ShapeObjDialog":
            return FakeSet("ShapeObject", {
                "Width": 20500, "Height": 5000, "TreatAsChar": 0,
                "ShapeDrawTextart": FakeSet("DrawTextart", {"String": "내용을 입력하세요.", "Shape": 17}),
                "ShapeDrawFillAttr": FakeSet("DrawFillAttr", {"Type": 1}),
                "ShapeDrawLineAttr": FakeSet("DrawLineAttr", {}),
            })
        return FakeSet("DrawTextart")

    def GetDefault(self, _pset) -> None:
        self.com.calls.append(("GetDefault", self.name))

    def Execute(self, pset) -> bool:
        self.com.calls.append(("Execute", self.name))
        self.com.executed[self.name] = pset
        if self.name == "TextArtCreate":
            self.com.LastCtrl = self.com.created
        return self.com.results.get(self.name, True)


class FakeCom:
    def __init__(self, created=None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.executed: dict[str, FakeSet] = {}
        self.results: dict[str, bool] = {}
        self.created = created if created is not None else FakeCtrl()
        self.LastCtrl = None

    def CreateAction(self, name: str) -> FakeAction:
        return FakeAction(name, self)

    def SetPosBySet(self, _anchor) -> None:
        self.calls.append(("SetPosBySet", ""))

    def FindCtrl(self) -> bool:
        return True


@pytest.fixture()
def canvas(monkeypatch):
    com = FakeCom()
    canvas = HangulCanvas(px=None, com=com, backend="win32com")
    canvas.assert_no_dialog = lambda: None
    canvas.get_pos = lambda: (0, 0, 0)
    canvas.set_pos = lambda _pos: True
    canvas.run = lambda name: com.calls.append(("Run", name)) or True
    monkeypatch.setattr(native_objects, "after_control", lambda _canvas, ctrl: com.calls.append(("after", "")))
    return canvas


def _args(**overrides):
    base = dict(text="첫째\n둘째", width_mm=80, height_mm=20, shape="wave2", font="함초롬돋움",
                font_style="bold", fill={"type": "linear_gradient", "angle": 0,
                                         "stops": ["#FF0000", "#0000FF"], "step": 255},
                line={"type": "solid", "color": "#112233", "width_mm": 0.5}, shadow=None,
                align="center", line_spacing_percent=110, char_spacing_percent=90, position=None)
    base.update(overrides)
    return _normalize_text_art(**base)


# --------------------------------------------------------------------------- native adapter


def test_native_insert_writes_child_set_copies_back_and_resizes(canvas) -> None:
    com = canvas.com
    assert native_objects.insert_text_art(canvas, **_args()) == 2
    # GetDefault must precede Execute: Execute on a bare set raises RPC_E_SERVERFAULT.
    create = [call for call in com.calls if call[1] == "TextArtCreate"]
    assert create == [("GetDefault", "TextArtCreate"), ("Execute", "TextArtCreate")]
    dialog = com.executed["ShapeObjDialog"]
    art = dialog.items["ShapeDrawTextart"]
    assert art.items["String"] == "첫째\r\n둘째" and art.items["NumberOfLines"] == 2
    assert (art.items["FontName"], art.items["FontType"], art.items["FontStyle"]) == ("함초롬돋움", 1, "굵게")
    assert (art.items["Shape"], art.items["AlignType"]) == (17, 2)
    assert (art.items["LineSpacing"], art.items["CharSpacing"]) == (110, 90)
    assert dialog.items["TreatAsChar"] == 1  # inline by default
    fill = dialog.items["ShapeDrawFillAttr"]
    assert fill.items["GradationStep"] == 255 and fill.items["GradationColorNum"] == 2
    assert dialog.items["ShapeDrawLineAttr"].items  # outline written back, not dropped
    ctrl = com.created
    assert ctrl.assigned == 1
    assert (ctrl._props.items["Width"], ctrl._props.items["Height"]) == (mm_to_hwpunit(80), mm_to_hwpunit(20))
    assert com.calls[-1] == ("after", "")


def test_native_insert_failure_after_creation_reports_one_undo_step(canvas) -> None:
    canvas.com.results["ShapeObjDialog"] = False
    with pytest.raises(HangulCommandError) as raised:
        native_objects.insert_text_art(canvas, **_args())
    assert raised.value.partial_undo_steps == 1
    assert canvas.com.created.assigned == 0


def test_native_insert_refuses_an_unexpected_new_control(canvas) -> None:
    canvas.com.created = SimpleNamespace(CtrlID="gso", UserDesc="사각형", GetAnchorPos=lambda _i: object())
    with pytest.raises(HangulCommandError, match="New text art was not found") as raised:
        native_objects.insert_text_art(canvas, **_args())
    assert not hasattr(raised.value, "partial_undo_steps")


def test_resize_control_verifies_the_applied_size() -> None:
    ctrl = FakeCtrl()
    native_objects.resize_control(ctrl, 1000, 500)
    assert (ctrl._props.items["Width"], ctrl._props.items["Height"]) == (1000, 500)

    class Ignoring(FakeCtrl):
        @property
        def Properties(self):
            return FakeSet("ShapeObject", {"Width": 20500, "Height": 5000})

        @Properties.setter
        def Properties(self, value) -> None:
            pass

    with pytest.raises(HangulCommandError, match="size was not applied"):
        native_objects.resize_control(Ignoring(), 1000, 500)


# --------------------------------------------------------------------------- engine


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("HWPCTL_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("HWPCTL_LOCK", str(tmp_path / "writer.lock"))
    eng = Engine()
    monkeypatch.setattr(eng, "_connect", lambda **_kwargs: SimpleNamespace())
    return eng


def test_engine_records_two_hangul_steps_as_one_undo_unit(engine, monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(native_objects, "insert_text_art", lambda _canvas, **args: seen.update(args) or 2)
    out = engine.insert_text_art("제목", 80, 20, shape="Wave2", fill="#FF0000")
    assert out["ok"] and out["undo_units"] == 1 and out["hangul_actions"] == 2
    assert out["shape"] == "wave2" and seen["fill"] == {"type": "solid", "color": "#FF0000"}
    assert seen["position"]["mode"] == "inline"
    assert load_state().undo_stack == [2]


def test_engine_keeps_undo_aligned_when_properties_fail(engine, monkeypatch) -> None:
    def fail(_canvas, **_args):
        error = HangulCommandError("Text art property action failed")
        error.partial_undo_steps = 1
        raise error
    monkeypatch.setattr(native_objects, "insert_text_art", fail)
    with pytest.raises(HangulCommandError):
        engine.insert_text_art("제목", 80, 20)
    assert load_state().undo_stack == [1]


@pytest.mark.parametrize("overrides, message", [
    ({"text": " "}, "비어"),
    ({"text": "a\tb"}, "제어 문자"),
    ({"text": "a␍␊b"}, "제어 문자"),
    ({"shape": "square"}, "모양 이름"),
    ({"font_style": "heavy"}, "font_style"),
    ({"align": "middle"}, "align"),
    ({"line_spacing_percent": 49}, "50~500"),
    ({"char_spacing_percent": 501}, "50~500"),
    ({"char_spacing_percent": 100.0}, "50~500"),
    ({"width_mm": 0}, "width_mm"),
    ({"fill": {"type": "linear_gradient", "stops": ["#000000", "#808080", "#FFFFFF"]}}, "2색"),
    ({"font": "a" * 65}, "font"),
])
def test_normalizer_rejects_unsupported_values_before_com(overrides, message) -> None:
    with pytest.raises(UsageError, match=message):
        _args(**overrides)


def test_normalizer_keeps_crlf_as_newline_and_trims_font() -> None:
    args = _args(text="첫째\r\n둘째", font=" 함초롬돋움 ")
    assert args["text"] == "첫째\n둘째" and args["font"] == "함초롬돋움"


# --------------------------------------------------------------------------- shared gradient step


def test_linear_gradient_accepts_step_and_step_center() -> None:
    fill = _normalize_fill({"type": "linear_gradient", "stops": ["#000000", "#FFFFFF"],
                            "step": 255, "step_center": 40}, allow_empty=False)
    assert (fill["step"], fill["step_center"]) == (255, 40)
    assert "step" not in _normalize_fill({"type": "linear", "stops": ["#000000", "#FFFFFF"]}, allow_empty=False)
    radial = _normalize_fill({"type": "radial_gradient", "stops": ["#000000", "#FFFFFF"], "step": 255},
                             allow_empty=False)
    assert radial["step"] == 255
    with pytest.raises(UsageError, match="0~255"):
        _normalize_fill({"type": "linear_gradient", "stops": ["#000000", "#FFFFFF"], "step": 256},
                        allow_empty=False)


def test_linear_gradient_writer_uses_requested_step() -> None:
    canvas = HangulCanvas(px=None, com=SimpleNamespace(), backend="win32com")
    target = FakeSet("DrawFillAttr")
    canvas._apply_fill(target, {"type": "linear_gradient", "angle": 90,
                                "stops": [{"offset": 0, "color": "#000000"}, {"offset": 1, "color": "#FFFFFF"}],
                                "step": 255, "step_center": 30})
    assert (target.items["GradationStep"], target.items["GradationStepCenter"]) == (255, 30)
    default = FakeSet("DrawFillAttr")
    canvas._apply_fill(default, {"type": "linear_gradient", "angle": 90,
                                 "stops": [{"offset": 0, "color": "#000000"}, {"offset": 1, "color": "#FFFFFF"}]})
    assert (default.items["GradationStep"], default.items["GradationStepCenter"]) == (100, 50)


# --------------------------------------------------------------------------- CLI and MCP


def test_cli_maps_arguments_and_literal_newline() -> None:
    args = parse_args(["insert_text_art", "첫째\\n둘째", "--width", "80", "--height", "20",
                       "--shape", "arch_up", "--font-style", "bold_italic", "--align", "full",
                       "--fill", '{"type":"linear_gradient","stops":["#FF0000","#0000FF"],"step":255}',
                       "--line-spacing", "130", "--char-spacing", "95",
                       "--position", '{"mode":"floating","x_mm":10,"y_mm":20}'])
    kwargs = _kwargs_for(args)
    assert kwargs["text"] == "첫째\n둘째"
    assert (kwargs["shape"], kwargs["font_style"], kwargs["align"]) == ("arch_up", "bold_italic", "full")
    assert kwargs["fill"]["step"] == 255 and kwargs["position"]["mode"] == "floating"
    assert (kwargs["line_spacing_percent"], kwargs["char_spacing_percent"]) == (130, 95)


def test_mcp_schema_requires_text_and_size() -> None:
    tools = {tool.name: tool for tool in anyio.run(build_mcp().list_tools)}
    schema = tools["insert_text_art"].inputSchema
    assert set(schema["required"]) == {"text", "width_mm", "height_mm"}
    assert schema["properties"]["shape"]["default"] == "rectangle"
    assert set(schema["properties"]["align"]["enum"]) == {"left", "right", "center", "full"}
    assert set(schema["properties"]["font_style"]["enum"]) == {"regular", "bold", "italic", "bold_italic"}


# --------------------------------------------------------------------------- authoring spec


def test_text_art_node_compiles_to_insert_text_art(tmp_path) -> None:
    spec = {"schema": SCHEMA, "sections": [{"content": [
        {"kind": "text_art", "text": "제목", "width_mm": 80, "height_mm": 20, "shape": "wave2",
         "fill": {"type": "linear_gradient", "stops": ["#FF0000", "#0000FF"], "step": 255}},
        {"kind": "paragraph", "text": "본문"}]}]}
    result = build_document(spec, str(tmp_path / "out.hwpx"), True,
                            _dispatch_factory=lambda: pytest.fail("COM reached"))
    assert result["ok"]
    first = result["plan"][0]
    assert first["command"] == "insert_text_art" and first["arguments"]["shape"] == "wave2"
    bad = {"schema": SCHEMA, "sections": [{"content": [
        {"kind": "text_art", "text": "x", "width_mm": 80, "height_mm": 20, "typo": 1}]}]}
    with pytest.raises(UsageError):
        build_document(bad, str(tmp_path / "bad.hwpx"), True)


def _hwpml_element(name: str, index: int = 0) -> str:
    text = (FIXTURES / f"{name}.hwpml").read_bytes().decode("utf-16")
    return re.findall(r"<TEXTART .*?</TEXTART>", text, re.S)[index]


def _hwpx_element(name: str, index: int = 0) -> tuple[str, dict[str, str]]:
    with zipfile.ZipFile(FIXTURES / f"{name}.hwpx") as archive:
        section = archive.read("Contents/section0.xml").decode("utf-8")
    return (re.findall(r"<hp:textart .*?</hp:textart>", section, re.S)[index],
            dict(re.findall(r'xmlns:(h[pc])="([^"]+)"', section)))


def _hwpml_doc(tmp_path: Path, element: str) -> Path:
    head = ('<HEAD><MAPPINGTABLE><CHARSHAPELIST><CHARSHAPE Id="1" Height="1000" TextColor="#112233"/>'
            '</CHARSHAPELIST><PARASHAPELIST><PARASHAPE Id="1" Align="Left"/></PARASHAPELIST></MAPPINGTABLE></HEAD>')
    source = tmp_path / "textart.hwpml"
    source.write_text(f'<HWPML>{head}<BODY><SECTION><P ParaShape="1"><TEXT CharShape="1">{element}'
                      '</TEXT></P></SECTION></BODY></HWPML>', encoding="utf-8")
    return source


def _hwpx_doc(tmp_path: Path, element: str, namespaces: dict[str, str]) -> Path:
    source = tmp_path / "textart.hwpx"
    manifest = ('<package><manifest><item id="header" href="Contents/header.xml"/>'
                '<item id="section0" href="Contents/section0.xml"/></manifest>'
                '<spine><itemref idref="header"/><itemref idref="section0"/></spine></package>')
    section = (f'<hs:sec xmlns:hs="urn:sect" xmlns:hp="{namespaces["hp"]}" xmlns:hc="{namespaces["hc"]}">'
               f'<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0">{element}</hp:run></hp:p></hs:sec>')
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("Contents/content.hpf", manifest)
        archive.writestr("Contents/header.xml", '<head><charPr id="0"/><paraPr id="0"/></head>')
        archive.writestr("Contents/section0.xml", section)
    return source


def _text_arts(result: dict) -> list[dict]:
    found = []

    def walk(items):
        for item in items:
            if item.get("kind") == "text_art":
                found.append({key: value for key, value in item.items() if key != "source"})
            walk(item.get("content", []))
    for section in (result.get("spec") or {}).get("sections", []):
        walk(section["content"])
    return found


UI_EXPECTED = {
    "kind": "text_art", "text": "그라데이션 샘플", "shape": "wave2", "align": "left",
    "line_spacing_percent": 120, "char_spacing_percent": 100, "font": "함초롬바탕",
    "fill": {"type": "linear_gradient", "angle": 0, "stops": ["#FF0000", "#0000FF"], "step": 255, "step_center": 50},
}


@pytest.mark.parametrize("kind", ["hwpml", "hwpx"])
def test_ui_text_art_converts_without_loss(tmp_path, kind) -> None:
    if kind == "hwpml":
        source = _hwpml_doc(tmp_path, _hwpml_element("ui-wave2-linear"))
    else:
        source = _hwpx_doc(tmp_path, *_hwpx_element("ui-wave2-linear"))
    result = reference_to_spec(source, tmp_path / "out", dry_run=True)
    assert result["ok"], result["report"]["losses"]
    (node,) = _text_arts(result)
    assert {key: node[key] for key in UI_EXPECTED} == UI_EXPECTED
    assert (mm_to_hwpunit(node["width_mm"]), mm_to_hwpunit(node["height_mm"])) == (16500, 5000)
    position = node["position"]
    assert (position["mode"], position["horizontal_relative_to"], position["vertical_relative_to"]) == (
        "floating", "column", "para")
    assert [mm_to_hwpunit(value) for value in position["outside_margin_mm"]] == [56, 56, 0, 0]
    plan = build_document(result["spec"], str(tmp_path / "rebuilt.hwpx"), True,
                          _dispatch_factory=lambda: pytest.fail("COM reached"))["plan"]
    assert [step["command"] for step in plan if step["command"] == "insert_text_art"] == ["insert_text_art"]


@pytest.mark.parametrize("change, detail", [
    (lambda xml: xml.replace('Angle="0" CenterX="8250"', 'Angle="30" CenterX="8250"'), "rotated text art"),
    (lambda xml: xml.replace('ZOrder="0"', 'ZOrder="2"'), "ZORDER=2"),
    (lambda xml: xml.replace('<SHADOW Color="0" OffsetX="0" OffsetY="0" Type="None"/>',
                             '<SHADOW Color="0" OffsetX="10" OffsetY="10" Type="Drop"/>'), "text art shadow"),
    (lambda xml: xml.replace("글맵시입니다.", "사용자 설명"), "unsupported shape-object child"),
    (lambda xml: xml.replace('HorzFlip="false"', 'HorzFlip="true"'), "HORZFLIP"),
])
def test_unrepresentable_text_art_fails_closed(tmp_path, change, detail) -> None:
    element = change(_hwpml_element("ui-wave2-linear"))
    result = reference_to_spec(_hwpml_doc(tmp_path, element), tmp_path / "out", dry_run=True)
    assert not result["ok"] and result["spec"] is None
    assert any(detail in entry["detail"] for entry in result["report"]["losses"]), result["report"]["losses"]


def test_linear_gradient_step_is_preserved_by_conversion(tmp_path) -> None:
    element = _hwpml_element("ui-wave2-linear").replace('Step="255"', 'Step="100"')
    result = reference_to_spec(_hwpml_doc(tmp_path, element), tmp_path / "out", dry_run=True)
    assert result["ok"]
    (node,) = _text_arts(result)
    assert node["fill"] == {"type": "linear_gradient", "angle": 0, "stops": ["#FF0000", "#0000FF"]}
