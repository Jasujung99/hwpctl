"""글맵시(TextArt) 실측 사실과 한/글 없이 읽는 리더.

한글 2022 ``12.0.0.850``에서 새 문서로 실측했다(``tests/fixtures/textart/README.md``).

- COM ``DrawTextart.Shape`` 번호는 ``SHAPES``의 순서와 같다. 55 이상은 한/글이 받아들이지만
  저장할 때 모양 이름이 비므로 쓰지 않는다.
- ``DrawTextart.AlignType`` 0..3은 LEFT, RIGHT, CENTER, FULL이다(HWPML은 Left/Right/Center/Full).
- ``DrawTextart.FontStyle``은 지역화된 이름(보통·굵게·기울임·굵게 기울임)을 그대로 받는다.
- 여러 줄 내용은 COM에 CR LF로 넣고, HWPX·HWPML에는 U+240D U+240A(기호 문자)로 저장된다.
- ``FontType=2``(HFT)를 줘도 저장 결과는 TTF다. 글맵시 글꼴은 TTF만 다룬다.
- 자동화의 ``ShapeObjDialog``는 하위 셋(``ShapeDrawTextart`` 등)의 복사본을 돌려주므로
  고친 뒤 ``SetItem``으로 다시 넣어야 반영된다.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET
import zipfile

from hwpctl.errors import UsageError
from hwpctl.units import hwpunit_to_mm

# Index == COM DrawTextart.Shape. Names are the HWPX ``textShape`` spellings.
SHAPES: tuple[str, ...] = (
    "PARALLELOGRAM", "INVERTED_PARALLELOGRAM", "INVERTED_UPWARD_CASCADE", "INVERTED_DOWNWARD_CASCADE",
    "UPWARD_CASCADE", "DOWNWARD_CASCADE", "REDUCE_RIGHT", "REDUCE_LEFT",
    "ISOSCELES_TRAPEZOID", "INVERTED_ISOSCELES_TRAPEZOID", "TOP_RIBBON_RECTANGLE", "BOTTOM_RIBBON_RECTANGLE",
    "CHEVRON_DOWN", "CHEVRON", "BOW_TIE", "HEXAGON",
    "WAVE1", "WAVE2", "WAVE3", "WAVE4",
    "LEFT_TILT_CYLINDER", "RIGHT_TILT_CYLINDER", "BOTTOM_WIDE_CYLINDER", "TOP_WIDE_CYLINDER",
    "THIN_CURVE_UP1", "THIN_CURVE_UP2", "THIN_CURVE_DOWN1", "THIN_CURVE_DOWN2",
    "INVERSED_FINGERNAIL", "FINGERNAIL", "GINKO_LEAF1", "GINKO_LEAF2",
    "INFLATE_RIGHT", "INFLATE_LEFT", "INFLATE_UP_CONVEX", "INFLATE_BOTTOM_CONVEX",
    "DEFLATE_TOP", "DEFLATE_BOTTOM", "DEFLATE", "INFLATE",
    "INFLATE_TOP", "INFLATE_BOTTOM", "RECTANGLE", "LEFT_CYLINDER",
    "CYLINDER", "RIGHT_CYLINDER", "CIRCLE", "CURVE_DOWN",
    "ARCH_UP", "ARCH_DOWN", "SINGLE_LINE_CIRCLE1", "SINGLE_LINE_CIRCLE2",
    "TRIPLE_LINE_CIRCLE1", "TRIPLE_LINE_CIRCLE2", "DOUBLE_LINE_CIRCLE",
)
DEFAULT_SHAPE = "rectangle"
# Index == COM DrawTextart.AlignType.
ALIGNS: tuple[str, ...] = ("left", "right", "center", "full")
FONT_STYLES: dict[str, str] = {"regular": "보통", "bold": "굵게", "italic": "기울임", "bold_italic": "굵게 기울임"}
FILE_NEWLINE = "␍␊"
TEXTART_COMMENT = "글맵시입니다."


def shape_index(name: Any) -> int:
    """공개 모양 이름(대소문자 무관, 예: ``rectangle``, ``wave2``)을 COM 번호로 바꾼다."""
    if not isinstance(name, str) or name.strip().upper() not in SHAPES:
        raise UsageError(
            f"글맵시 모양 이름이 아닙니다: {name!r}. 예: rectangle, wave2, parallelogram, arch_up"
        )
    return SHAPES.index(name.strip().upper())


def shape_name(value: Any) -> str:
    """COM 번호, HWPX 이름 또는 HWPML 번호 문자열을 공개 소문자 이름으로 바꾼다."""
    if isinstance(value, str) and value.strip().upper() in SHAPES:
        return value.strip().lower()
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if type(value) is int and 0 <= value < len(SHAPES):
        return SHAPES[value].lower()
    raise UsageError(f"알 수 없는 글맵시 모양입니다: {value!r}")


def align_name(value: Any) -> str:
    """COM 번호 또는 파일 표기(LEFT/Left/FULL…)를 공개 이름으로 바꾼다."""
    if type(value) is int and 0 <= value < len(ALIGNS):
        return ALIGNS[value]
    if isinstance(value, str) and value.strip().lower() in ALIGNS:
        return value.strip().lower()
    raise UsageError(f"알 수 없는 글맵시 정렬입니다: {value!r}")


def font_style_key(value: Any) -> str:
    """지역화된 글꼴 스타일 이름을 공개 키(regular/bold/italic/bold_italic)로 바꾼다."""
    for key, localized in FONT_STYLES.items():
        if value in (key, localized):
            return key
    raise UsageError(f"알 수 없는 글맵시 글꼴 스타일입니다: {value!r}")


def text_from_file(value: str) -> str:
    """HWPX·HWPML에 저장된 내용의 줄바꿈 기호(U+240D U+240A)를 ``\\n``으로 되돌린다."""
    return value.replace(FILE_NEWLINE, "\n")


def text_to_com(value: str) -> str:
    """공개 ``\\n`` 줄바꿈을 COM ``DrawTextart.String``이 받는 CR LF로 바꾼다."""
    return value.replace("\r\n", "\n").replace("\n", "\r\n")


def _tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1].upper()


def _attrs(node: ET.Element | None) -> dict[str, str]:
    if node is None:
        return {}
    return {key.rsplit("}", 1)[-1].upper(): value for key, value in node.attrib.items()}


def _child(node: ET.Element | None, name: str) -> ET.Element | None:
    if node is None:
        return None
    return next((child for child in node if _tag(child) == name.upper()), None)


def _color(raw: str | None) -> str | None:
    """HWPX ``#RRGGBB`` 또는 HWPML BGR 정수(COLORREF)를 ``#RRGGBB``로 바꾼다."""
    if raw is None:
        return None
    raw = raw.strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", raw):
        return raw.upper()
    if raw.isdigit():
        value = int(raw)
        if value > 0xFFFFFF:
            return None
        return "#{:02X}{:02X}{:02X}".format(value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF)
    return None


def _bool(raw: str | None) -> bool | None:
    if raw is None:
        return None
    return raw.strip().lower() in {"1", "true"}


def _fill(brush: ET.Element | None) -> dict[str, Any] | None:
    if brush is None or len(brush) != 1:
        return None
    item = brush[0]
    attrs = _attrs(item)
    tag = _tag(item)
    if tag in {"WINBRUSH", "WINDOWBRUSH"}:
        return {"type": "solid", "color": _color(attrs.get("FACECOLOR")),
                "alpha": int(attrs.get("ALPHA", "0") or 0)}
    if tag == "GRADATION":
        kind = attrs.get("TYPE", "").upper()
        colors = [_color(_attrs(color).get("VALUE")) for color in item if _tag(color) == "COLOR"]
        return {"type": {"LINEAR": "linear_gradient", "RADIAL": "radial_gradient"}.get(kind, kind.lower()),
                "angle": int(attrs.get("ANGLE", "0")), "center_x": int(attrs.get("CENTERX", "0")),
                "center_y": int(attrs.get("CENTERY", "0")), "step": int(attrs.get("STEP", "0")),
                "step_center": int(attrs.get("STEPCENTER", "0")), "alpha": int(attrs.get("ALPHA", "0") or 0),
                "colors": colors}
    return {"type": tag.lower()}


def parse_text_art(node: ET.Element, kind: str) -> dict[str, Any]:
    """HWPX ``hp:textart`` 또는 HWPML ``TEXTART`` 한 개의 사실을 공개 이름으로 읽는다.

    값의 의미 검사(손실 판단)는 호출자가 한다. 이 함수는 한/글·COM 없이 동작한다.
    """
    if kind not in {"hwpx", "hwpml"} or _tag(node) != "TEXTART":
        raise UsageError("parse_text_art expects a HWPX/HWPML TEXTART element")
    attrs = _attrs(node)
    if kind == "hwpx":
        frame, size, pos = attrs, _attrs(_child(node, "SZ")), _attrs(_child(node, "POS"))
        drawing = node
        props = _child(node, "TEXTARTPR")
        comment = _child(node, "SHAPECOMMENT")
    else:
        shape_object = _child(node, "SHAPEOBJECT")
        frame = _attrs(shape_object)
        size, pos = _attrs(_child(shape_object, "SIZE")), _attrs(_child(shape_object, "POSITION"))
        drawing = _child(node, "DRAWINGOBJECT")
        props = _child(node, "TEXTARTSHAPE")
        comment = _child(shape_object, "SHAPECOMMENT")
    pattrs = _attrs(props)
    line = _attrs(_child(drawing, "LINESHAPE"))
    width, height = int(size.get("WIDTH", "0")), int(size.get("HEIGHT", "0"))
    return {
        "text": text_from_file(attrs.get("TEXT", "")),
        "font_name": pattrs.get("FONTNAME", ""),
        "font_style": font_style_key(pattrs.get("FONTSTYLE", "보통")),
        "font_type": pattrs.get("FONTTYPE", "").lower(),
        "shape": shape_name(pattrs.get("TEXTSHAPE", "")),
        "align": align_name(pattrs.get("ALIGN", "")),
        "line_spacing_percent": int(pattrs.get("LINESPACING", "0")),
        "char_spacing_percent": int(pattrs.get("CHARSPACING", "0")),
        "width_hu": width,
        "height_hu": height,
        "width_mm": round(hwpunit_to_mm(width), 2),
        "height_mm": round(hwpunit_to_mm(height), 2),
        "treat_as_char": _bool(pos.get("TREATASCHAR")),
        "vert_rel_to": pos.get("VERTRELTO", "").lower(),
        "horz_rel_to": pos.get("HORZRELTO", "").lower(),
        "flow_with_text": _bool(pos.get("FLOWWITHTEXT")),
        "z_order": int(frame.get("ZORDER", "0")),
        "line_style": line.get("STYLE", "").lower(),
        "fill": _fill(_child(drawing, "FILLBRUSH")),
        "comment": (comment.text or "") if comment is not None else None,
    }


def _hwpx_sections(path: Path) -> list[bytes]:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if re.fullmatch(r"Contents/section\d+\.xml", name)]
        names.sort(key=lambda name: int(re.search(r"\d+", name.rsplit("/", 1)[-1]).group()))
        return [archive.read(name) for name in names]


def read_text_arts(path: str | Path) -> list[dict[str, Any]]:
    """``.hwpx`` 또는 ``.hwpml`` 파일의 글맵시를 문서 순서대로 읽는다(한/글·COM 불필요)."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".hwpx":
        kind, roots = "hwpx", [ET.fromstring(data) for data in _hwpx_sections(path)]
    elif suffix == ".hwpml":
        kind, roots = "hwpml", [ET.fromstring(path.read_bytes())]
    else:
        raise UsageError("글맵시 리더는 .hwpx 또는 .hwpml만 읽습니다.")
    return [parse_text_art(node, kind) for root in roots for node in root.iter() if _tag(node) == "TEXTART"]
