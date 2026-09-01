"""한글 없이 쓸 수 있는 HWPX 서식 작성 래퍼.

``python-hwpx`` 6.x 고수준 API 가 분명한 것만 얇게 감싼다.
저수준 ``add_shape`` / ``add_control`` 은 깨진 파일을 만들 수 있어 노출하지 않는다.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from hwpctl.errors import HwpxError, UsageError
from hwpctl.hwpx.document import require_hwpx


def insert_paragraph(
    document: Any,
    text: str,
    *,
    style: str | int | None = None,
    para_pr_id_ref: str | int | None = None,
    char_pr_id_ref: str | int | None = None,
    inherit_style: bool = True,
) -> Any:
    """문단 추가. 기본은 직전 문단 서식 상속(``inherit_style=True``)."""

    require_hwpx()
    if not hasattr(document, "add_paragraph"):
        raise HwpxError("문서 객체에 add_paragraph 가 없습니다.")
    try:
        return document.add_paragraph(
            text,
            style=style,
            para_pr_id_ref=para_pr_id_ref,
            char_pr_id_ref=char_pr_id_ref,
            inherit_style=inherit_style,
        )
    except Exception as exc:
        raise HwpxError(f"HWPX 문단을 넣을 수 없습니다: {exc}") from exc


HWPUNIT_PER_MM = 7200 / 25.4

# ``hp:pagePr/@landscape`` does not use the common PORTRAIT/LANDSCAPE
# vocabulary. Hangul's OWPML values describe the page's short/long side:
# WIDELY is A4 세로 and NARROWLY is A4 가로. Keep these exact tokens at the
# hwpctl boundary; python-hwpx 6.3 currently serializes "PORTRAIT" instead,
# which Hangul 2022 does not honor.
HWPX_PORTRAIT = "WIDELY"
HWPX_LANDSCAPE = "NARROWLY"

_RUN_SPEC_KEYS = frozenset(
    {
        "text",
        "base_char_pr_id",
        "bold",
        "italic",
        "font",
        "size",
        "color",
        "underline",
        "underline_shape",
        "underline_color",
    }
)


def _hangul_page_orientation(orientation: str | None) -> str | None:
    """Map ergonomic orientation names to the two OWPML tokens Hangul reads."""

    if orientation is None:
        return None
    aliases = {
        "PORTRAIT": HWPX_PORTRAIT,
        "VERTICAL": HWPX_PORTRAIT,
        "세로": HWPX_PORTRAIT,
        "WIDELY": HWPX_PORTRAIT,
        "LANDSCAPE": HWPX_LANDSCAPE,
        "HORIZONTAL": HWPX_LANDSCAPE,
        "가로": HWPX_LANDSCAPE,
        "NARROWLY": HWPX_LANDSCAPE,
    }
    normalized = str(orientation).strip()
    token = aliases.get(normalized.upper()) or aliases.get(normalized)
    if token is None:
        raise UsageError(
            "쪽 방향은 portrait/landscape(또는 세로/가로) 중 하나여야 합니다."
        )
    return token


def set_page_setup(
    document: Any,
    *,
    paper_size: str | None = None,
    width_mm: float | None = None,
    height_mm: float | None = None,
    orientation: str | None = None,
    margins_mm: Mapping[str, float] | None = None,
    margin_left_mm: float | None = None,
    margin_right_mm: float | None = None,
    margin_top_mm: float | None = None,
    margin_bottom_mm: float | None = None,
    header_margin_mm: float | None = None,
    footer_margin_mm: float | None = None,
    gutter_mm: float | None = None,
    columns: int | None = None,
    column_gap_mm: float | None = None,
) -> Any:
    """Set page dimensions without python-hwpx's invalid orientation mapping.

    The upstream convenience method swaps dimensions for ``WIDELY`` and
    serializes ``PORTRAIT`` for a portrait request. Both conflict with the
    OWPML values Hangul 2022 uses. First apply physical dimensions/margins
    with no orientation, then set the exact `pagePr/@landscape` token through
    the public ``page.set_size`` API.
    """

    require_hwpx()
    page = getattr(document, "page", None)
    setup = getattr(page, "setup", None)
    set_size = getattr(page, "set_size", None)
    if not callable(setup) or not callable(set_size):
        raise HwpxError("python-hwpx 페이지 설정 API를 쓸 수 없습니다.")

    hangul_orientation = _hangul_page_orientation(orientation)
    try:
        result = setup(
            paper_size=paper_size,
            width_mm=width_mm,
            height_mm=height_mm,
            # Do not route through python-hwpx's orientation normalizer.
            orientation=None,
            margins_mm=margins_mm,
            margin_left_mm=margin_left_mm,
            margin_right_mm=margin_right_mm,
            margin_top_mm=margin_top_mm,
            margin_bottom_mm=margin_bottom_mm,
            header_margin_mm=header_margin_mm,
            footer_margin_mm=footer_margin_mm,
            gutter_mm=gutter_mm,
            columns=columns,
            column_gap_mm=column_gap_mm,
        )
        if hangul_orientation is not None:
            set_size(orientation=hangul_orientation)
    except Exception as exc:
        raise HwpxError(f"HWPX 쪽 설정을 적용할 수 없습니다: {exc}") from exc
    return result


def _resolve_paragraph(
    document: Any,
    *,
    paragraph_index: int | None,
    paragraph: Any | None,
) -> Any:
    if paragraph is not None and paragraph_index is not None:
        raise UsageError("paragraph 와 paragraph_index 는 함께 지정할 수 없습니다.")
    if paragraph is not None:
        return paragraph

    paragraphs = list(getattr(document, "paragraphs", []) or [])
    if not paragraphs:
        raise HwpxError("서식을 적용할 문단이 없습니다.")
    if paragraph_index is None:
        return paragraphs[-1]
    if paragraph_index < 0 or paragraph_index >= len(paragraphs):
        raise UsageError(f"문단 번호가 범위를 벗어났습니다: {paragraph_index}")
    return paragraphs[paragraph_index]


def _style_has_requested_value(
    *,
    base_char_pr_id: str | int | None,
    bold: bool | None,
    italic: bool | None,
    font: str | None,
    size: float | None,
    color: str | None,
    underline: bool | None,
    underline_shape: str | None,
    underline_color: str | None,
) -> bool:
    return any(
        value is not None
        for value in (
            base_char_pr_id,
            bold,
            italic,
            font if font else None,
            size,
            color if color else None,
            underline,
            underline_shape,
            underline_color,
        )
    )


def _base_run_flags(
    document: Any, base_char_pr_id: str | int | None
) -> tuple[bool, bool, bool]:
    """Read flags that ``python-hwpx`` otherwise resets to ``False``."""

    if base_char_pr_id is None:
        return (False, False, False)
    styles = getattr(document, "styles", None)
    getter = getattr(styles, "char_property", None)
    if not callable(getter):
        return (False, False, False)
    try:
        char_pr = getter(base_char_pr_id)
    except Exception:
        return (False, False, False)
    children = getattr(char_pr, "child_attributes", {}) or {}
    underline_attrs = children.get("underline") or {}
    underline = bool(underline_attrs) and str(
        underline_attrs.get("type", "")
    ).upper() != "NONE"
    return ("bold" in children, "italic" in children, underline)


def _ensure_run_style(
    document: Any,
    *,
    base_char_pr_id: str | int | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
    font: str | None = None,
    size: float | None = None,
    color: str | None = None,
    underline: bool | None = None,
    underline_shape: str | None = None,
    underline_color: str | None = None,
) -> str:
    """Create/reuse a charPr after declaring a requested font face."""

    if not _style_has_requested_value(
        base_char_pr_id=base_char_pr_id,
        bold=bold,
        italic=italic,
        font=font,
        size=size,
        color=color,
        underline=underline,
        underline_shape=underline_shape,
        underline_color=underline_color,
    ):
        raise UsageError("적용할 글자 서식이 없습니다.")

    styles = getattr(document, "styles", None)
    ensure = getattr(styles, "ensure_run", None)
    ensure_font = getattr(styles, "ensure_font", None)
    if not callable(ensure) or not callable(ensure_font):
        raise HwpxError("python-hwpx 글자 서식 API를 쓸 수 없습니다.")

    face = (font or "").strip()
    try:
        # fontRef만 쓰면 선언되지 않은 face가 무시될 수 있다. 먼저 7개 언어
        # fontface에 등록해야 한글의 글꼴 대체 규칙도 의도대로 적용된다.
        if face:
            ensure_font(face)
        base_bold, base_italic, base_underline = _base_run_flags(
            document, base_char_pr_id
        )
        if (
            base_char_pr_id is not None
            and bold is None
            and italic is None
            and underline is None
            and underline_shape is None
            and underline_color is None
            and not face
            and size is None
            and not color
        ):
            return str(base_char_pr_id)
        char_pr_id = ensure(
            base_char_pr_id=base_char_pr_id,
            bold=base_bold if bold is None else bool(bold),
            italic=base_italic if italic is None else bool(italic),
            underline=base_underline if underline is None else bool(underline),
            font=face or None,
            size=size,
            color=color or None,
            underline_shape=underline_shape,
            underline_color=underline_color,
        )
    except Exception as exc:
        raise HwpxError(f"HWPX 글자 서식을 만들 수 없습니다: {exc}") from exc
    return str(char_pr_id)


def set_run_props(
    document: Any,
    *,
    paragraph_index: int | None = None,
    paragraph: Any | None = None,
    run_index: int | None = None,
    base_char_pr_id: str | int | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
    font: str | None = None,
    size: float | None = None,
    color: str | None = None,
    underline: bool | None = None,
    underline_shape: str | None = None,
    underline_color: str | None = None,
) -> dict[str, Any]:
    """charPr을 만들고 선택한 런에 연결한다.

    ``font``는 ``fontfaces``에 먼저 선언한다. ``base_char_pr_id``를 쓸 때
    생략한 굵게/기울임/밑줄 플래그도 원본에서 유지한다.
    """

    require_hwpx()
    target = _resolve_paragraph(
        document, paragraph_index=paragraph_index, paragraph=paragraph
    )
    char_pr_id = _ensure_run_style(
        document,
        base_char_pr_id=base_char_pr_id,
        bold=bold,
        italic=italic,
        font=font,
        size=size,
        color=color,
        underline=underline,
        underline_shape=underline_shape,
        underline_color=underline_color,
    )

    runs = list(getattr(target, "runs", []) or [])
    if not runs:
        raise HwpxError("서식을 적용할 런이 없습니다.")
    if run_index is None:
        chosen = runs
    else:
        if run_index < 0 or run_index >= len(runs):
            raise UsageError(f"런 번호가 범위를 벗어났습니다: {run_index}")
        chosen = [runs[run_index]]
    for run in chosen:
        run.char_pr_id_ref = char_pr_id

    return {
        "ok": True,
        "char_pr_id": char_pr_id,
        "applied_runs": len(chosen),
    }


def append_run(
    document: Any,
    text: str,
    *,
    paragraph_index: int | None = None,
    paragraph: Any | None = None,
    base_char_pr_id: str | int | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
    font: str | None = None,
    size: float | None = None,
    color: str | None = None,
    underline: bool | None = None,
    underline_shape: str | None = None,
    underline_color: str | None = None,
) -> Any:
    """문단 끝에 독립 charPr 런을 추가한다.

    문단 전체를 다시 칠하지 않으므로 마감 시각처럼 일부만 빨간 밑줄인
    문장을 안전하게 만들 수 있다.
    """

    require_hwpx()
    target = _resolve_paragraph(
        document, paragraph_index=paragraph_index, paragraph=paragraph
    )
    has_style = _style_has_requested_value(
        base_char_pr_id=base_char_pr_id,
        bold=bold,
        italic=italic,
        font=font,
        size=size,
        color=color,
        underline=underline,
        underline_shape=underline_shape,
        underline_color=underline_color,
    )
    char_pr_id = (
        _ensure_run_style(
            document,
            base_char_pr_id=base_char_pr_id,
            bold=bold,
            italic=italic,
            font=font,
            size=size,
            color=color,
            underline=underline,
            underline_shape=underline_shape,
            underline_color=underline_color,
        )
        if has_style
        else None
    )
    adder = getattr(target, "add_run", None)
    if not callable(adder):
        raise HwpxError("문단 객체에 add_run 이 없습니다.")
    try:
        return adder(str(text), char_pr_id_ref=char_pr_id)
    except Exception as exc:
        raise HwpxError(f"HWPX 런을 넣을 수 없습니다: {exc}") from exc


def _normalize_run_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    unknown = set(spec) - _RUN_SPEC_KEYS
    if unknown:
        raise UsageError(
            "알 수 없는 런 서식: " + ", ".join(sorted(str(key) for key in unknown))
        )
    return {
        "text": "" if spec.get("text") is None else str(spec.get("text", "")),
        "base_char_pr_id": spec.get("base_char_pr_id"),
        "bold": spec.get("bold"),
        "italic": spec.get("italic"),
        "font": spec.get("font"),
        "size": spec.get("size"),
        "color": spec.get("color"),
        "underline": spec.get("underline"),
        "underline_shape": spec.get("underline_shape"),
        "underline_color": spec.get("underline_color"),
    }


def set_paragraph_runs(
    document: Any,
    runs: Sequence[Mapping[str, Any]],
    *,
    paragraph_index: int | None = None,
    paragraph: Any | None = None,
) -> Any:
    """문단을 여러 서식 런으로 교체한다.

    첫 런은 기존 런을 재사용하고 나머지는 별도 런으로 넣는다. 텍스트만
    비우는 방식이라 표/구역 제어 같은 비텍스트 자식은 제거하지 않는다.
    """

    require_hwpx()
    if not runs:
        raise UsageError("런을 하나 이상 지정하세요.")
    normalized = [_normalize_run_spec(spec) for spec in runs]
    target = _resolve_paragraph(
        document, paragraph_index=paragraph_index, paragraph=paragraph
    )
    try:
        target.text = ""
    except Exception as exc:
        raise HwpxError(f"HWPX 문단 텍스트를 비울 수 없습니다: {exc}") from exc

    existing = list(getattr(target, "runs", []) or [])
    if not existing:
        append_run(document, "", paragraph=target)
        existing = list(getattr(target, "runs", []) or [])
    if not existing:
        raise HwpxError("첫 런을 만들 수 없습니다.")

    first = normalized[0]
    existing[0].text = first["text"]
    first_style = {key: first[key] for key in _RUN_SPEC_KEYS - {"text"}}
    if _style_has_requested_value(**first_style):
        set_run_props(document, paragraph=target, run_index=0, **first_style)
    for spec in normalized[1:]:
        style = {key: spec[key] for key in _RUN_SPEC_KEYS - {"text"}}
        append_run(document, spec["text"], paragraph=target, **style)
    return target


def _hwpunit_from_mm(value: float, *, label: str) -> int:
    if value <= 0:
        raise UsageError(f"{label}은(는) 0보다 커야 합니다.")
    return round(value * HWPUNIT_PER_MM)


def _ensure_border_fill(
    document: Any,
    *,
    border_color: str,
    border_width: str,
    border_type: str,
    active_borders: Sequence[str],
    fill_color: str | None = None,
) -> str:
    styles = getattr(document, "styles", None)
    ensure = getattr(styles, "ensure_border_fill", None)
    if not callable(ensure):
        raise HwpxError("python-hwpx styles.ensure_border_fill 을 쓸 수 없습니다.")
    try:
        return str(
            ensure(
                border_color=border_color,
                border_width=border_width,
                border_type=border_type,
                active_borders=active_borders,
                fill_color=fill_color,
            )
        )
    except Exception as exc:
        raise HwpxError(f"HWPX 표 테두리/채우기를 만들 수 없습니다: {exc}") from exc


def create_table_and_fill(
    document: Any,
    rows: int,
    cols: int,
    cells: Sequence[Sequence[Any]] | None = None,
    *,
    header_fill: str = "",
    header_columns: Sequence[int] | None = None,
    width_mm: float | None = None,
    height_mm: float | None = None,
    column_widths_mm: Sequence[float] | None = None,
    border_color: str | None = None,
    border_width: str = "0.12 mm",
    border_type: str = "SOLID",
    active_borders: Sequence[str] = ("left", "right", "top", "bottom"),
) -> Any:
    """실제 표 셀의 텍스트·채움·테두리·폭을 작성한다.

    ``column_widths_mm``는 상대 비율이 아니라 최종 열 폭(mm)이다. 합계는
    ``width_mm``와 같아야 하며, 생략하면 열 폭 합계를 표 폭으로 사용한다.
    ``header_fill``은 첫 행의 지정 셀이 참조하는 ``borderFill``에 기록된다.
    ``header_columns``를 생략하면 첫 행 전체를 채운다.
    """

    require_hwpx()
    if rows < 1 or cols < 1:
        raise UsageError("표 행·열은 1 이상이어야 합니다.")
    try:
        header_cols = (
            list(range(cols))
            if header_columns is None
            else [int(col) for col in header_columns]
        )
    except (TypeError, ValueError) as exc:
        raise UsageError("header_columns는 열 번호 목록이어야 합니다.") from exc
    if any(col < 0 or col >= cols for col in header_cols):
        raise UsageError("header_columns에 표 범위를 벗어난 열이 있습니다.")
    widths: list[float] | None = None
    if column_widths_mm is not None:
        widths = [float(width) for width in column_widths_mm]
        if len(widths) != cols:
            raise UsageError("column_widths_mm 개수는 표 열 수와 같아야 합니다.")
        if any(width <= 0 for width in widths):
            raise UsageError("column_widths_mm의 각 폭은 0보다 커야 합니다.")
        summed = sum(widths)
        if width_mm is None:
            width_mm = summed
        elif abs(float(width_mm) - summed) > 0.05:
            raise UsageError("width_mm는 column_widths_mm의 합계와 같아야 합니다.")

    table_width = (
        _hwpunit_from_mm(float(width_mm), label="표 폭")
        if width_mm is not None
        else None
    )
    table_height = (
        _hwpunit_from_mm(float(height_mm), label="표 높이")
        if height_mm is not None
        else None
    )
    border_fill_id: str | None = None
    if border_color:
        border_fill_id = _ensure_border_fill(
            document,
            border_color=border_color,
            border_width=border_width,
            border_type=border_type,
            active_borders=active_borders,
        )
    adder = getattr(document, "add_table", None)
    if not callable(adder):
        raise HwpxError("문서 객체에 add_table 이 없습니다.")
    kwargs: dict[str, Any] = {}
    if table_width is not None:
        kwargs["width"] = table_width
    if table_height is not None:
        kwargs["height"] = table_height
    if border_fill_id is not None:
        kwargs["border_fill_id_ref"] = border_fill_id
    try:
        table = adder(rows, cols, **kwargs)
    except Exception as exc:
        raise HwpxError(f"HWPX 표를 만들 수 없습니다: {exc}") from exc

    if widths is not None:
        set_widths = getattr(table, "set_column_widths", None)
        if not callable(set_widths):
            raise HwpxError("표 객체에 set_column_widths 가 없습니다.")
        try:
            set_widths(widths)
        except Exception as exc:
            raise HwpxError(f"HWPX 표 열 폭을 지정할 수 없습니다: {exc}") from exc

    if cells:
        for row_idx, row in enumerate(cells):
            if row_idx >= rows:
                break
            for col_idx, value in enumerate(row):
                if col_idx >= cols:
                    break
                try:
                    table.set_cell_text(row_idx, col_idx, "" if value is None else str(value))
                except Exception as exc:
                    raise HwpxError(
                        f"HWPX 셀을 채울 수 없습니다 ({row_idx},{col_idx}): {exc}"
                    ) from exc

    fill = (header_fill or "").strip()
    if fill:
        try:
            if border_color:
                header_border_fill = _ensure_border_fill(
                    document,
                    border_color=border_color,
                    border_width=border_width,
                    border_type=border_type,
                    active_borders=active_borders,
                    fill_color=fill,
                )
                setter = getattr(table, "set_cell_border_fill", None)
                if not callable(setter):
                    raise HwpxError("표 객체에 set_cell_border_fill 이 없습니다.")
                for col_idx in header_cols:
                    setter(0, col_idx, header_border_fill)
            else:
                shader = getattr(table, "set_cell_shading", None)
                if not callable(shader):
                    raise HwpxError("표 객체에 set_cell_shading 이 없습니다.")
                for col_idx in header_cols:
                    shader(0, col_idx, fill)
        except HwpxError:
            raise
        except Exception as exc:
            raise HwpxError(f"HWPX 헤더 배경을 칠할 수 없습니다: {exc}") from exc

    return table


def _top_level_paragraph_index(document: Any, paragraph: Any) -> int | None:
    target_element = getattr(paragraph, "element", None)
    for index, candidate in enumerate(list(getattr(document, "paragraphs", []) or [])):
        if candidate is paragraph or (
            target_element is not None
            and getattr(candidate, "element", None) is target_element
        ):
            return index
    return None


def apply_paragraph_format(
    document: Any,
    *,
    paragraph_index: int | None = None,
    paragraph: Any | None = None,
    alignment: str | None = None,
    line_spacing_percent: float | None = None,
    indent_left_mm: float | None = None,
    indent_right_mm: float | None = None,
    first_line_indent_mm: float | None = None,
    spacing_before_pt: float | None = None,
    spacing_after_pt: float | None = None,
    bottom_border: bool = False,
    border_color: str = "#BFBFBF",
    border_width: str = "0.12 mm",
) -> Any:
    """문단 정렬·줄간격·여백·아래 테두리를 실제 paraPr에 연결한다.

    표 셀 안 문단은 python-hwpx의 인덱스 API 범위 밖이다. 그 경우 같은
    공개 API로 일시 문단에 paraPr을 만든 뒤, 생성된 참조만 셀 문단에 붙인다.
    """

    require_hwpx()
    target = _resolve_paragraph(
        document, paragraph_index=paragraph_index, paragraph=paragraph
    )
    styles = getattr(document, "styles", None)
    apply = getattr(styles, "apply_paragraph_format", None)
    if not callable(apply):
        raise HwpxError("python-hwpx styles.apply_paragraph_format 을 쓸 수 없습니다.")

    kwargs = {
        "alignment": alignment,
        "line_spacing_percent": line_spacing_percent,
        "indent_left_mm": indent_left_mm,
        "indent_right_mm": indent_right_mm,
        "first_line_indent_mm": first_line_indent_mm,
        "spacing_before_pt": spacing_before_pt,
        "spacing_after_pt": spacing_after_pt,
        "bottom_border": bottom_border,
        "border_color": border_color,
        "border_width": border_width,
    }
    index = _top_level_paragraph_index(document, target)
    if index is not None:
        try:
            return apply(paragraph_index=index, **kwargs)
        except Exception as exc:
            raise HwpxError(f"HWPX 문단 서식을 적용할 수 없습니다: {exc}") from exc

    temporary = None
    result: Any = None
    try:
        temporary = insert_paragraph(
            document,
            "",
            para_pr_id_ref=getattr(target, "para_pr_id_ref", None),
            inherit_style=False,
        )
        result = apply(
            paragraph_index=len(list(getattr(document, "paragraphs", []) or [])) - 1,
            **kwargs,
        )
        target.para_pr_id_ref = temporary.para_pr_id_ref
    except HwpxError:
        raise
    except Exception as exc:
        raise HwpxError(f"HWPX 셀 문단 서식을 적용할 수 없습니다: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.remove()
            except Exception as exc:
                if result is not None:
                    raise HwpxError(
                        f"HWPX 임시 문단을 제거할 수 없습니다: {exc}"
                    ) from exc
    return result


def apply_paragraph_align(
    document: Any,
    alignment: str,
    *,
    paragraph_index: int | None = None,
    paragraph: Any | None = None,
    line_spacing_percent: float | None = None,
) -> Any:
    """문단 가로 정렬과 선택적 줄간격을 paraPr에 적용한다."""

    key = (alignment or "").strip().upper()
    if key not in {"LEFT", "CENTER", "RIGHT", "JUSTIFY"}:
        raise UsageError("문단 정렬은 left/center/right/justify 중 하나여야 합니다.")
    return apply_paragraph_format(
        document,
        paragraph_index=paragraph_index,
        paragraph=paragraph,
        alignment=key,
        line_spacing_percent=line_spacing_percent,
    )
