"""레거시 HWPML을 ID와 경로에 독립적인 구조 모델로 정규화한다.

비교기는 한/글 COM을 알지 못한다. 이 모듈의 입력은 이미 읽기 전용으로 확보한
HWPML 문자열이며, 결과 모델은 디스크 위치나 HWPML 내부 스타일 ID를 노출하지
않는다. 실제 문서 원문은 이 모듈의 호출자가 비공개로 보관해야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Iterable
import xml.etree.ElementTree as ET


_TEXT_SKIP_TAGS = {
    "TABLE",
    "PICTURE",
    "DRAWINGOBJECT",
    "SHAPEOBJECT",
    "CONTAINER",
    "SECDEF",
    "COLDEF",
    "NEWNUM",
    "PAGENUMCTRL",
    "PAGEHIDE",
    "PAGEODDEVEN",
    "FOOTNOTESHAPE",
    "ENDNOTESHAPE",
    "PAGEBORDERFILL",
    "HEADER",
    "FOOTER",
    "FOOTNOTE",
    "ENDNOTE",
    "AUTONUM",
    "NEWNUMBER",
    "HIDE",
    "BOOKMARK",
    "COMPOSE",
    "DUTMAL",
    "HIDDENCOMMENT",
    "INDEXMARK",
}
_DRAWING_TAGS = {"PICTURE", "DRAWINGOBJECT", "SHAPEOBJECT", "CONTAINER", "TEXTBOX"}
_GRADIENT_TAGS = {"GRADATION", "GRADIENT", "GRADIENTFILL"}
_ID_ATTRIBUTE_NAMES = {
    "id",
    "parashape",
    "charshape",
    "borderfill",
    "style",
    "styleidref",
    "parapridref",
    "charpridref",
    "borderfillidref",
}


def _local_name(value: str) -> str:
    """XML namespace를 뺀 대문자 태그/속성 이름을 돌려준다."""

    return value.rsplit("}", 1)[-1].upper()


def _attrs(element: ET.Element) -> dict[str, str]:
    return {_local_name(key): value for key, value in element.attrib.items()}


def _attr(element: ET.Element, *names: str, default: str | None = None) -> str | None:
    values = _attrs(element)
    for name in names:
        value = values.get(_local_name(name))
        if value is not None:
            return value
    return default


def _int(value: str | None, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    expected = _local_name(name)
    return [child for child in element if _local_name(child.tag) == expected]


def _first_child(element: ET.Element, name: str) -> ET.Element | None:
    children = _children(element, name)
    return children[0] if children else None


def _first_descendant(element: ET.Element, name: str) -> ET.Element | None:
    expected = _local_name(name)
    return next((child for child in element.iter() if _local_name(child.tag) == expected), None)


def _descendants(element: ET.Element, name: str) -> Iterable[ET.Element]:
    expected = _local_name(name)
    return (child for child in element.iter() if _local_name(child.tag) == expected)


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple((key, _freeze(value[key])) for key in sorted(value))
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _content_digest(parts: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        encoded = part.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _without_ids(element: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in _attrs(element).items():
        normalized = key.casefold()
        if normalized in _ID_ATTRIBUTE_NAMES or normalized.endswith("idref"):
            continue
        result[key.casefold()] = value
    return result


def _element_signature(element: ET.Element, fonts: dict[str, dict[str, tuple[str, str]]]) -> Any:
    """글자/문단 서식 자식의 ID 독립적인 의미 표현."""

    name = _local_name(element.tag)
    if name in {"FONTID", "FONTREF"}:
        slots: dict[str, tuple[str, str]] = {}
        for language, font_id in _attrs(element).items():
            key = language.casefold()
            slots[key] = fonts.get(key, {}).get(font_id, (font_id, ""))
        return (name, tuple(sorted(slots.items())))

    children = tuple(_element_signature(child, fonts) for child in element)
    text = (element.text or "").strip()
    return (name, _freeze(_without_ids(element)), text, children)


def _shape_signature(
    shape: ET.Element | None,
    fonts: dict[str, dict[str, tuple[str, str]]],
) -> Any:
    if shape is None:
        return ()
    return (
        _freeze(_without_ids(shape)),
        tuple(_element_signature(child, fonts) for child in shape),
    )


def _border_value(node: ET.Element | None) -> str | None:
    if node is None:
        return None
    kind = _attr(node, "Type", "type", default="None")
    if kind is None or kind.casefold() == "none":
        return None
    return "/".join(
        (
            kind,
            _attr(node, "Width", "width", default="") or "",
            _attr(node, "Color", "color", default="") or "",
        )
    )


def _border_signature(shape: ET.Element | None) -> Any:
    if shape is None:
        return ()
    side_names = {
        "left": "LEFTBORDER",
        "right": "RIGHTBORDER",
        "top": "TOPBORDER",
        "bottom": "BOTTOMBORDER",
    }
    sides = {
        side: _border_value(_first_child(shape, tag)) for side, tag in side_names.items()
    }
    brush = _first_descendant(shape, "WINDOWBRUSH")
    face = _attr(brush, "FaceColor", "faceColor") if brush is not None else None
    fill = None if face in {None, "4294967295", "#FFFFFFFF"} else face
    return _freeze({"sides": sides, "fill": fill})


@dataclass(frozen=True)
class TextRun:
    """보이는 문자열과 ID가 해석된 글자 서식."""

    text: str
    formatting: Any

    @property
    def text_digest(self) -> str:
        return _digest(self.text)


@dataclass(frozen=True)
class ParagraphBlock:
    """문단 하나. 표가 있으면 본문 텍스트와 표를 함께 보존한다."""

    paragraph_formatting: Any
    page_break: str | None
    runs: tuple[TextRun, ...]
    table: "Table | None" = None

    @property
    def visible_text(self) -> str:
        return "".join(run.text for run in self.runs)

    @property
    def text_digest(self) -> str:
        return _digest(self.visible_text)

    @property
    def kind(self) -> str:
        return "table" if self.table is not None else "paragraph"

    @property
    def is_blank(self) -> bool:
        return self.table is None and not self.visible_text


@dataclass(frozen=True)
class Cell:
    """표의 실제 논리 격자 좌표를 쓰는 칸."""

    row: int
    column: int
    row_span: int
    column_span: int
    width_hwp: int
    height_hwp: int
    vertical_align: str | None
    border: Any
    paragraphs: tuple[ParagraphBlock, ...]

    @property
    def key(self) -> tuple[int, int, int, int]:
        return (self.row, self.column, self.row_span, self.column_span)


@dataclass(frozen=True)
class Table:
    rows: int
    columns: int
    formatting: Any
    cells: tuple[Cell, ...]


@dataclass(frozen=True)
class NormalizedDocument:
    """HWPML의 비공개 원문을 메모리에서만 가진 정규 구조."""

    page: Any
    blocks: tuple[ParagraphBlock, ...]
    unsupported: frozenset[str]

    @property
    def visible_text(self) -> str:
        return "".join(_block_text(block) for block in self.blocks)


def _block_text(block: ParagraphBlock) -> str:
    text = block.visible_text
    if block.table is None:
        return text
    return text + "".join(
        _block_text(paragraph)
        for cell in block.table.cells
        for paragraph in cell.paragraphs
    )


class _Normalizer:
    def __init__(self, root: ET.Element) -> None:
        self.root = root
        self.fonts = self._fonts()
        self.char_shapes = self._by_id("CHARSHAPELIST", "CHARSHAPE")
        self.para_shapes = self._by_id("PARASHAPELIST", "PARASHAPE")
        self.border_fills = self._by_id("BORDERFILLLIST", "BORDERFILL")
        self.styles = self._styles()

    def _fonts(self) -> dict[str, dict[str, tuple[str, str]]]:
        fonts: dict[str, dict[str, tuple[str, str]]] = {}
        face_list = _first_descendant(self.root, "FACENAMELIST")
        if face_list is None:
            return fonts
        for face in _descendants(face_list, "FONTFACE"):
            language = (_attr(face, "Lang", "lang", default="hangul") or "hangul").casefold()
            slots = fonts.setdefault(language, {})
            for item in _children(face, "FONT"):
                font_id = _attr(item, "Id", "id", default="") or ""
                slots[font_id] = (
                    _attr(item, "Name", "face", "name", default="") or "",
                    _attr(item, "Type", "type", default="") or "",
                )
        return fonts

    def _by_id(self, list_name: str, record_name: str) -> dict[str, ET.Element]:
        collection = _first_descendant(self.root, list_name)
        if collection is None:
            return {}
        return {
            _attr(item, "Id", "id", default="") or "": item
            for item in _descendants(collection, record_name)
        }

    def _styles(self) -> dict[str, tuple[str, str]]:
        collection = _first_descendant(self.root, "STYLELIST")
        if collection is None:
            return {}
        return {
            _attr(item, "Id", "id", default="") or "": (
                _attr(item, "ParaShape", "paraPrIDRef", default="") or "",
                _attr(item, "CharShape", "charPrIDRef", default="") or "",
            )
            for item in _descendants(collection, "STYLE")
        }

    def _paragraph_shape(self, paragraph: ET.Element) -> Any:
        style_id = _attr(paragraph, "Style", "styleIDRef", default="") or ""
        shape_id = _attr(paragraph, "ParaShape", "paraPrIDRef", default=None)
        if shape_id is None:
            shape_id = self.styles.get(style_id, ("", ""))[0]
        return _shape_signature(self.para_shapes.get(shape_id), self.fonts)

    def _character_shape(self, text: ET.Element, paragraph: ET.Element) -> Any:
        style_id = _attr(paragraph, "Style", "styleIDRef", default="") or ""
        shape_id = _attr(text, "CharShape", "charPrIDRef", default=None)
        if shape_id is None:
            shape_id = self.styles.get(style_id, ("", ""))[1]
        return _shape_signature(self.char_shapes.get(shape_id), self.fonts)

    def _visible(self, node: ET.Element) -> str:
        tag = _local_name(node.tag)
        if tag in _TEXT_SKIP_TAGS:
            return ""
        if tag == "LINEBREAK":
            return "\n"
        if tag == "TAB":
            return "\t"
        if tag in {"FWSPACE", "NBSPACE", "FIXEDWIDTHSPACE"}:
            return " "
        if tag in {"MARKPENBEGIN", "MARKPENEND"}:
            return ""
        parts = [node.text or ""]
        for child in node:
            parts.append(self._visible(child))
            parts.append(child.tail or "")
        return "".join(parts)

    def _runs(self, paragraph: ET.Element) -> tuple[TextRun, ...]:
        runs: list[TextRun] = []
        for text in _children(paragraph, "TEXT"):
            content = self._visible(text)
            if content:
                runs.append(TextRun(content, self._character_shape(text, paragraph)))
        return tuple(runs)

    def block(self, paragraph: ET.Element) -> ParagraphBlock:
        table_node = next(iter(_descendants(paragraph, "TABLE")), None)
        return ParagraphBlock(
            paragraph_formatting=self._paragraph_shape(paragraph),
            page_break=_attr(paragraph, "PageBreak", "pageBreak"),
            runs=self._runs(paragraph),
            table=self.table(table_node) if table_node is not None else None,
        )

    def table(self, table: ET.Element) -> Table:
        rows = _int(_attr(table, "RowCount", "rowCnt"), 1)
        columns = _int(_attr(table, "ColCount", "colCnt"), 1)
        cells: list[Cell] = []
        for row in _children(table, "ROW"):
            for cell in _children(row, "CELL"):
                para_list = _first_child(cell, "PARALIST")
                border_id = _attr(cell, "BorderFill", "borderFillIDRef", default="") or ""
                cells.append(
                    Cell(
                        row=_int(_attr(cell, "RowAddr", "rowAddr")),
                        column=_int(_attr(cell, "ColAddr", "colAddr")),
                        row_span=_int(_attr(cell, "RowSpan", "rowSpan"), 1),
                        column_span=_int(_attr(cell, "ColSpan", "colSpan"), 1),
                        width_hwp=_int(_attr(cell, "Width", "width")),
                        height_hwp=_int(_attr(cell, "Height", "height")),
                        vertical_align=(
                            _attr(para_list, "VertAlign", "vertAlign")
                            if para_list is not None
                            else None
                        ),
                        border=_border_signature(self.border_fills.get(border_id)),
                        paragraphs=(
                            tuple(self.block(item) for item in _children(para_list, "P"))
                            if para_list is not None
                            else ()
                        ),
                    )
                )
        cells.sort(key=lambda item: item.key)
        return Table(
            rows=rows,
            columns=columns,
            formatting=_freeze(_without_ids(table)),
            cells=tuple(cells),
        )

    def page(self) -> Any:
        page = _first_descendant(self.root, "PAGEDEF")
        if page is None:
            return ()
        margin = _first_child(page, "PAGEMARGIN")
        return _freeze(
            {
                "attrs": _without_ids(page),
                "margin": _without_ids(margin) if margin is not None else {},
            }
        )

    def unsupported(self) -> frozenset[str]:
        unsupported: set[str] = set()
        for element in self.root.iter():
            tag = _local_name(element.tag)
            if tag in _DRAWING_TAGS:
                unsupported.add("drawings")
            if tag in _GRADIENT_TAGS:
                unsupported.add("gradients")
        return frozenset(unsupported)

    def document(self) -> NormalizedDocument:
        body = _first_descendant(self.root, "BODY")
        section = _first_descendant(body, "SECTION") if body is not None else None
        blocks = tuple(self.block(item) for item in _children(section, "P")) if section is not None else ()
        return NormalizedDocument(page=self.page(), blocks=blocks, unsupported=self.unsupported())


def normalize_hwpml(hwpml: str) -> NormalizedDocument:
    """HWPML 문자열을 비교용 정규 모델로 만든다.

    이 함수는 파일 경로, COM, 한/글 인스턴스를 받지 않는다. 실제 HWP 문서에서
    HWPML을 얻는 과정은 Windows 전용 읽기 도구가 별도로 책임져야 한다.
    """

    try:
        root = ET.fromstring(hwpml)
    except ET.ParseError as exc:
        raise ValueError("HWPML XML을 읽을 수 없습니다.") from exc
    return _Normalizer(root).document()


__all__ = [
    "Cell",
    "NormalizedDocument",
    "ParagraphBlock",
    "Table",
    "TextRun",
    "normalize_hwpml",
]
