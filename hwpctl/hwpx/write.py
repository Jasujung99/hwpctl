"""HWPX 쓰기 래퍼. 문단·부분 런·표·크림 구역 헤더를 조립한다.

``python-hwpx`` 6.x 고수준 API 만 쓴다.
저수준 ``add_shape`` / ``add_control`` 은 깨진 파일을 만들 수 있어 노출하지 않는다.
한/글 COM 과 작성 잠금은 쓰지 않는다.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from hwpctl.colors import parse_color
from hwpctl.errors import HwpxError, UsageError
from hwpctl.hwpx.document import require_hwpx

ALIGNMENTS = {"LEFT", "CENTER", "RIGHT", "JUSTIFY"}

# 공고문 크림 구역 헤더(원본 p1–p3 실측 근사).
CREAM_FILL = "#F5E6C8"
TABLE_HEADER_FILL = "#C5D8EA"
TABLE_LABEL_FILL = "#D6E3F0"
GOTHIC_FONT = "함초롬돋움"
MYEONGJO_FONT = "함초롬바탕"

RunLike = Mapping[str, Any]


def _hex_color(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    r, g, b = parse_color(str(value))
    return f"#{r:02X}{g:02X}{b:02X}"


def _normalize_align(alignment: str | None) -> str | None:
    if alignment is None or not str(alignment).strip():
        return None
    key = str(alignment).strip().upper()
    if key not in ALIGNMENTS:
        raise UsageError("문단 정렬은 left/center/right/justify 중 하나여야 합니다.")
    return key


def _paragraph_index(document: Any, paragraph: Any) -> int | None:
    """최상위 문단 번호. 표 셀 안 문단은 python-hwpx 인덱스가 없어 None."""

    right = getattr(paragraph, "element", None)
    for idx, item in enumerate(list(getattr(document, "paragraphs", []) or [])):
        if item is paragraph:
            return idx
        left = getattr(item, "element", None)
        if left is not None and left is right:
            return idx
    return None


def _apply_on_paragraph(document: Any, paragraph: Any, **kwargs: Any) -> Any:
    idx = _paragraph_index(document, paragraph)
    if idx is None:
        return None
    return apply_paragraph_format(document, paragraph_index=idx, **kwargs)


def insert_paragraph(
    document: Any,
    text: str,
    *,
    style: str | int | None = None,
    para_pr_id_ref: str | int | None = None,
    char_pr_id_ref: str | int | None = None,
    inherit_style: bool = True,
    font: str | None = None,
    size: float | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
    underline: bool | None = None,
    color: str | None = None,
    align: str | None = None,
    line_spacing_percent: float | None = None,
    indent_left_mm: float | None = None,
    indent_right_mm: float | None = None,
    first_line_indent_mm: float | None = None,
    spacing_before_pt: float | None = None,
    spacing_after_pt: float | None = None,
    page_break_before: bool | None = None,
    bottom_border: bool = False,
    border_color: str = "#000000",
    border_width: str = "0.4 mm",
) -> Any:
    """문단 추가. 글꼴·크기·굵게·색·밑줄·정렬·줄간격을 한 번에 지정할 수 있다."""

    require_hwpx()
    if not hasattr(document, "add_paragraph"):
        raise HwpxError("문서 객체에 add_paragraph 가 없습니다.")
    try:
        paragraph = document.add_paragraph(
            text,
            style=style,
            para_pr_id_ref=para_pr_id_ref,
            char_pr_id_ref=char_pr_id_ref,
            inherit_style=inherit_style,
        )
    except Exception as exc:
        raise HwpxError(f"HWPX 문단을 넣을 수 없습니다: {exc}") from exc

    idx = _paragraph_index(document, paragraph)
    if idx is not None and any(
        v is not None for v in (font, size, bold, italic, underline, color)
    ):
        set_run_props(
            document,
            paragraph_index=idx,
            bold=bold,
            italic=italic,
            underline=underline,
            font=font,
            size=size,
            color=color,
        )
    _apply_on_paragraph(
        document,
        paragraph,
        alignment=align,
        line_spacing_percent=line_spacing_percent,
        indent_left_mm=indent_left_mm,
        indent_right_mm=indent_right_mm,
        first_line_indent_mm=first_line_indent_mm,
        spacing_before_pt=spacing_before_pt,
        spacing_after_pt=spacing_after_pt,
        page_break_before=page_break_before,
        bottom_border=bottom_border,
        border_color=border_color,
        border_width=border_width,
    )
    return paragraph


def insert_runs(
    document: Any,
    runs: Sequence[RunLike],
    *,
    inherit_style: bool = False,
    align: str | None = None,
    line_spacing_percent: float | None = None,
    indent_left_mm: float | None = None,
    indent_right_mm: float | None = None,
    first_line_indent_mm: float | None = None,
    spacing_before_pt: float | None = None,
    spacing_after_pt: float | None = None,
    page_break_before: bool | None = None,
    bottom_border: bool = False,
) -> Any:
    """한 문단에 부분 런(빨간 기한, 파란 URL 등)을 이어 붙인다."""

    require_hwpx()
    if not runs:
        raise UsageError("넣을 런이 없습니다.")
    try:
        paragraph = document.add_paragraph("", inherit_style=inherit_style, include_run=False)
    except Exception as exc:
        raise HwpxError(f"HWPX 문단을 넣을 수 없습니다: {exc}") from exc
    adder = getattr(paragraph, "add_run", None)
    if not callable(adder):
        raise HwpxError("문단 객체에 add_run 이 없습니다.")
    for spec in runs:
        add_run(document, paragraph, spec)
    _apply_on_paragraph(
        document,
        paragraph,
        alignment=align,
        line_spacing_percent=line_spacing_percent,
        indent_left_mm=indent_left_mm,
        indent_right_mm=indent_right_mm,
        first_line_indent_mm=first_line_indent_mm,
        spacing_before_pt=spacing_before_pt,
        spacing_after_pt=spacing_after_pt,
        page_break_before=page_break_before,
        bottom_border=bottom_border,
    )
    return paragraph


def add_run(document: Any, paragraph: Any, spec: RunLike) -> Any:
    """기존 문단에 런 하나를 붙인다. ``styles.ensure_run`` 으로 charPr 을 상속·덮어쓴다."""

    require_hwpx()
    text = "" if spec.get("text") is None else str(spec.get("text"))
    char_pr_id = ensure_run_style(
        document,
        bold=spec.get("bold"),
        italic=spec.get("italic"),
        underline=spec.get("underline"),
        underline_color=spec.get("underline_color"),
        font=spec.get("font"),
        size=spec.get("size"),
        color=spec.get("color"),
        base_char_pr_id=spec.get("base_char_pr_id"),
    )
    adder = getattr(paragraph, "add_run", None)
    if not callable(adder):
        raise HwpxError("문단 객체에 add_run 이 없습니다.")
    try:
        return adder(text, char_pr_id_ref=char_pr_id)
    except Exception as exc:
        raise HwpxError(f"HWPX 런을 넣을 수 없습니다: {exc}") from exc


def ensure_run_style(
    document: Any,
    *,
    bold: bool | None = None,
    italic: bool | None = None,
    underline: bool | None = None,
    underline_color: str | None = None,
    font: str | None = None,
    size: float | None = None,
    color: str | None = None,
    base_char_pr_id: str | int | None = None,
) -> str:
    require_hwpx()
    styles = getattr(document, "styles", None)
    ensure = getattr(styles, "ensure_run", None)
    if not callable(ensure):
        raise HwpxError("python-hwpx styles.ensure_run 을 쓸 수 없습니다.")
    kwargs: dict[str, Any] = {}
    if bold is not None:
        kwargs["bold"] = bool(bold)
    if italic is not None:
        kwargs["italic"] = bool(italic)
    if underline is not None:
        kwargs["underline"] = bool(underline)
    if underline_color:
        kwargs["underline"] = True
        kwargs["underline_color"] = _hex_color(underline_color)
    if font:
        kwargs["font"] = font
    if size is not None:
        kwargs["size"] = size
    hex_color = _hex_color(color)
    if hex_color:
        kwargs["color"] = hex_color
    if base_char_pr_id is not None:
        kwargs["base_char_pr_id"] = base_char_pr_id
    try:
        return str(ensure(**kwargs) if kwargs else ensure())
    except Exception as exc:
        raise HwpxError(f"HWPX 글자 서식을 만들 수 없습니다: {exc}") from exc


def set_run_props(
    document: Any,
    *,
    paragraph_index: int | None = None,
    run_index: int | None = None,
    base_char_pr_id: str | int | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
    underline: bool | None = None,
    underline_color: str | None = None,
    font: str | None = None,
    size: float | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    """``styles.ensure_run`` 으로 charPr 을 보장한 뒤 런에 연결한다."""

    require_hwpx()
    if all(
        value is None
        for value in (bold, italic, underline, underline_color, font, size, color, base_char_pr_id)
    ):
        raise UsageError("적용할 글자 서식이 없습니다.")
    char_pr_id = ensure_run_style(
        document,
        bold=bold,
        italic=italic,
        underline=underline,
        underline_color=underline_color,
        font=font,
        size=size,
        color=color,
        base_char_pr_id=base_char_pr_id,
    )

    paragraphs = list(getattr(document, "paragraphs", []) or [])
    if not paragraphs:
        raise HwpxError("서식을 적용할 문단이 없습니다.")
    if paragraph_index is None:
        target = paragraphs[-1]
    else:
        if paragraph_index < 0 or paragraph_index >= len(paragraphs):
            raise UsageError(f"문단 번호가 범위를 벗어났습니다: {paragraph_index}")
        target = paragraphs[paragraph_index]

    runs = list(getattr(target, "runs", []) or [])
    applied = 0
    if run_index is None:
        chosen = runs
    else:
        if run_index < 0 or run_index >= len(runs):
            raise UsageError(f"런 번호가 범위를 벗어났습니다: {run_index}")
        chosen = [runs[run_index]]
    for run in chosen:
        run.char_pr_id_ref = char_pr_id
        applied += 1

    return {
        "ok": True,
        "char_pr_id": str(char_pr_id),
        "applied_runs": applied,
    }


def apply_paragraph_format(
    document: Any,
    *,
    paragraph_index: int | None = None,
    alignment: str | None = None,
    line_spacing_percent: float | None = None,
    indent_left_mm: float | None = None,
    indent_right_mm: float | None = None,
    first_line_indent_mm: float | None = None,
    spacing_before_pt: float | None = None,
    spacing_after_pt: float | None = None,
    page_break_before: bool | None = None,
    bottom_border: bool = False,
    border_color: str = "#000000",
    border_width: str = "0.12 mm",
) -> Any:
    """문단 가로 정렬·줄간격·들여쓰기·쪽 나눔. ``styles.apply_paragraph_format``."""

    require_hwpx()
    styles = getattr(document, "styles", None)
    apply = getattr(styles, "apply_paragraph_format", None)
    if not callable(apply):
        raise HwpxError("python-hwpx styles.apply_paragraph_format 을 쓸 수 없습니다.")
    idx = paragraph_index
    if idx is None:
        paragraphs = list(getattr(document, "paragraphs", []) or [])
        if not paragraphs:
            raise HwpxError("정렬할 문단이 없습니다.")
        idx = len(paragraphs) - 1
    kwargs: dict[str, Any] = {"paragraph_index": idx, "bottom_border": bottom_border}
    align = _normalize_align(alignment)
    if align:
        kwargs["alignment"] = align
    if line_spacing_percent is not None:
        kwargs["line_spacing_percent"] = line_spacing_percent
    if indent_left_mm is not None:
        kwargs["indent_left_mm"] = indent_left_mm
    if indent_right_mm is not None:
        kwargs["indent_right_mm"] = indent_right_mm
    if first_line_indent_mm is not None:
        kwargs["first_line_indent_mm"] = first_line_indent_mm
    if spacing_before_pt is not None:
        kwargs["spacing_before_pt"] = spacing_before_pt
    if spacing_after_pt is not None:
        kwargs["spacing_after_pt"] = spacing_after_pt
    if page_break_before is not None:
        kwargs["page_break_before"] = page_break_before
    if bottom_border:
        kwargs["border_color"] = border_color
        kwargs["border_width"] = border_width
    meaningful = {
        key: value
        for key, value in kwargs.items()
        if key not in {"paragraph_index", "bottom_border"} or value
    }
    if list(meaningful.keys()) == [] or (
        not align
        and line_spacing_percent is None
        and indent_left_mm is None
        and indent_right_mm is None
        and first_line_indent_mm is None
        and spacing_before_pt is None
        and spacing_after_pt is None
        and page_break_before is None
        and not bottom_border
    ):
        return None
    try:
        return apply(**kwargs)
    except Exception as exc:
        raise HwpxError(f"HWPX 문단 서식을 적용할 수 없습니다: {exc}") from exc


def apply_paragraph_align(
    document: Any,
    alignment: str,
    *,
    paragraph_index: int | None = None,
) -> Any:
    """문단 가로 정렬. 하위 호환 래퍼."""

    return apply_paragraph_format(
        document, paragraph_index=paragraph_index, alignment=alignment
    )


def ensure_border_fill(
    document: Any,
    *,
    fill_color: str | None = None,
    border_color: str = "#000000",
    border_width: str = "0.12 mm",
    border_type: str = "SOLID",
    active_borders: Sequence[str] | None = None,
) -> str:
    require_hwpx()
    styles = getattr(document, "styles", None)
    ensure = getattr(styles, "ensure_border_fill", None)
    if not callable(ensure):
        raise HwpxError("python-hwpx styles.ensure_border_fill 을 쓸 수 없습니다.")
    kwargs: dict[str, Any] = {
        "border_color": _hex_color(border_color) or "#000000",
        "border_width": border_width,
        "border_type": border_type,
    }
    if fill_color:
        kwargs["fill_color"] = _hex_color(fill_color)
    if active_borders is not None:
        kwargs["active_borders"] = list(active_borders)
    try:
        return str(ensure(**kwargs))
    except Exception as exc:
        raise HwpxError(f"HWPX 테두리/배경을 만들 수 없습니다: {exc}") from exc


def create_table_and_fill(
    document: Any,
    rows: int,
    cols: int,
    cells: Sequence[Sequence[Any]] | None = None,
    *,
    header_fill: str = "",
    fills: Sequence[Sequence[str | None]] | None = None,
    col_widths: Sequence[float] | None = None,
    width: int | None = None,
    border_color: str = "#000000",
    border_width: str = "0.12 mm",
) -> Any:
    """표 생성 후 셀 텍스트·배경·열 너비."""

    require_hwpx()
    if rows < 1 or cols < 1:
        raise UsageError("표 행·열은 1 이상이어야 합니다.")
    adder = getattr(document, "add_table", None)
    if not callable(adder):
        raise HwpxError("문서 객체에 add_table 이 없습니다.")
    border_fill_id = ensure_border_fill(
        document,
        border_color=border_color,
        border_width=border_width,
    )
    try:
        table = adder(rows, cols, width=width, border_fill_id_ref=border_fill_id)
    except TypeError:
        try:
            table = adder(rows, cols)
        except Exception as exc:
            raise HwpxError(f"HWPX 표를 만들 수 없습니다: {exc}") from exc
    except Exception as exc:
        raise HwpxError(f"HWPX 표를 만들 수 없습니다: {exc}") from exc

    if cells:
        for row_idx, row in enumerate(cells):
            if row_idx >= rows:
                break
            for col_idx, value in enumerate(row):
                if col_idx >= cols:
                    break
                if isinstance(value, Mapping) or (
                    isinstance(value, Sequence) and not isinstance(value, (str, bytes))
                ):
                    fill_cell_runs(document, table, row_idx, col_idx, value)
                else:
                    try:
                        table.set_cell_text(row_idx, col_idx, "" if value is None else str(value))
                    except Exception as exc:
                        raise HwpxError(
                            f"HWPX 셀을 채울 수 없습니다 ({row_idx},{col_idx}): {exc}"
                        ) from exc

    fill = (header_fill or "").strip()
    if fill:
        for col_idx in range(cols):
            set_cell_fill(document, table, 0, col_idx, fill)

    if fills:
        for row_idx, row in enumerate(fills):
            if row_idx >= rows:
                break
            for col_idx, value in enumerate(row):
                if col_idx >= cols or not value:
                    continue
                set_cell_fill(document, table, row_idx, col_idx, str(value))

    if col_widths:
        setter = getattr(table, "set_column_widths", None)
        if not callable(setter):
            raise HwpxError("표 객체에 set_column_widths 가 없습니다.")
        try:
            setter(list(col_widths))
        except Exception as exc:
            raise HwpxError(f"HWPX 열 너비를 지정할 수 없습니다: {exc}") from exc
    return table


def set_cell_fill(document: Any, table: Any, row: int, col: int, fill: str) -> None:
    shader = getattr(table, "set_cell_shading", None)
    if callable(shader):
        try:
            shader(row, col, _hex_color(fill) or fill)
            return
        except Exception as exc:
            raise HwpxError(f"HWPX 셀 배경을 칠할 수 없습니다: {exc}") from exc
    fill_id = ensure_border_fill(document, fill_color=fill)
    binder = getattr(table, "set_cell_border_fill", None)
    if not callable(binder):
        raise HwpxError("표 객체에 set_cell_shading / set_cell_border_fill 이 없습니다.")
    binder(row, col, fill_id)


def fill_cell_runs(
    document: Any,
    table: Any,
    row: int,
    col: int,
    runs: Sequence[RunLike] | Mapping[str, Any],
    *,
    align: str | None = None,
    line_spacing_percent: float | None = None,
) -> Any:
    """셀 내용을 부분 런으로 채운다(한 문단)."""

    specs: Sequence[RunLike]
    if isinstance(runs, Mapping) and "text" in runs:
        specs = [runs]
    elif isinstance(runs, Sequence) and not isinstance(runs, (str, bytes)):
        specs = runs
    else:
        raise UsageError("셀 런은 매핑 또는 런 목록이어야 합니다.")
    cell = table.cell(row, col)
    paragraphs = list(getattr(cell, "paragraphs", []) or [])
    if paragraphs:
        paragraph = paragraphs[0]
        existing_runs = list(getattr(paragraph, "runs", []) or [])
        for run in existing_runs:
            remover = getattr(paragraph.element, "remove", None)
            if callable(remover):
                try:
                    paragraph.element.remove(run.element)
                except Exception:
                    pass
    else:
        paragraph = cell.add_paragraph("")
    for spec in specs:
        add_run(document, paragraph, spec)
    if align or line_spacing_percent is not None:
        _apply_on_paragraph(
            document,
            paragraph,
            alignment=align,
            line_spacing_percent=line_spacing_percent,
        )
    return paragraph


def add_cell_paragraph(
    document: Any,
    table: Any,
    row: int,
    col: int,
    runs: Sequence[RunLike] | str,
    *,
    align: str | None = None,
    line_spacing_percent: float | None = 160,
    indent_left_mm: float | None = None,
    font: str | None = None,
    size: float | None = None,
    bold: bool | None = None,
) -> Any:
    """셀에 문단을 하나 더 넣는다."""

    cell = table.cell(row, col)
    if isinstance(runs, str):
        specs: list[RunLike] = [
            {
                "text": runs,
                "font": font,
                "size": size,
                "bold": bold,
            }
        ]
    else:
        specs = list(runs)
    paragraph = cell.add_paragraph("")
    existing = list(getattr(paragraph, "runs", []) or [])
    for run in existing:
        try:
            paragraph.element.remove(run.element)
        except Exception:
            pass
    for spec in specs:
        merged = dict(spec)
        merged.setdefault("font", font)
        merged.setdefault("size", size)
        if bold is not None:
            merged.setdefault("bold", bold)
        add_run(document, paragraph, merged)
    _apply_on_paragraph(
        document,
        paragraph,
        alignment=align,
        line_spacing_percent=line_spacing_percent,
        indent_left_mm=indent_left_mm,
    )
    return paragraph


def cream_section_header(
    document: Any,
    number: str,
    title: str,
    *,
    cream: str = CREAM_FILL,
    width: int | None = None,
    page_break_before: bool = False,
) -> Any:
    """크림 배경의 구역 헤더 표 ``[번호 | 제목]``."""

    if page_break_before:
        insert_paragraph(
            document,
            "",
            inherit_style=False,
            page_break_before=True,
            size=1,
        )
    table = create_table_and_fill(
        document,
        1,
        2,
        [[number, title]],
        fills=[[cream, cream]],
        col_widths=[1, 12],
        width=width,
        border_color="#000000",
        border_width="0.4 mm",
    )
    for col in (0, 1):
        fill_cell_runs(
            document,
            table,
            0,
            col,
            [
                {
                    "text": number if col == 0 else title,
                    "font": GOTHIC_FONT,
                    "size": 16 if col == 1 else 14,
                    "bold": True,
                }
            ],
            align="CENTER" if col == 0 else "LEFT",
        )
    return table


def boxed_block(
    document: Any,
    header: str | None,
    body_rows: Sequence[Sequence[RunLike] | str],
    *,
    cream_header: bool = True,
    width: int | None = None,
) -> Any:
    """테두리 상자. 선택적 크림 헤더 + 본문 문단들."""

    rows = 2 if header else 1
    table = create_table_and_fill(
        document,
        rows,
        1,
        width=width,
        border_color="#000000",
        border_width="0.12 mm",
    )
    body_row = 1 if header else 0
    if header:
        if cream_header:
            set_cell_fill(document, table, 0, 0, CREAM_FILL)
        fill_cell_runs(
            document,
            table,
            0,
            0,
            [{"text": header, "font": GOTHIC_FONT, "size": 13, "bold": True}],
            align="LEFT",
        )
    first = True
    for item in body_rows:
        if first:
            if isinstance(item, str):
                fill_cell_runs(
                    document,
                    table,
                    body_row,
                    0,
                    [{"text": item, "font": MYEONGJO_FONT, "size": 11}],
                    align="JUSTIFY",
                    line_spacing_percent=160,
                )
            else:
                fill_cell_runs(
                    document,
                    table,
                    body_row,
                    0,
                    item,
                    align="JUSTIFY",
                    line_spacing_percent=160,
                )
            first = False
        else:
            add_cell_paragraph(
                document,
                table,
                body_row,
                0,
                item,
                align="JUSTIFY",
                line_spacing_percent=160,
            )
    return table


def set_page_setup(
    document: Any,
    *,
    paper_size: str = "A4",
    margin_left_mm: float = 20,
    margin_right_mm: float = 20,
    margin_top_mm: float = 18,
    margin_bottom_mm: float = 16,
    header_margin_mm: float = 10,
    footer_margin_mm: float = 10,
) -> Any:
    require_hwpx()
    page = getattr(document, "page", None)
    setup = getattr(page, "setup", None)
    if not callable(setup):
        raise HwpxError("문서 객체에 page.setup 이 없습니다.")
    try:
        return setup(
            paper_size=paper_size,
            margin_left_mm=margin_left_mm,
            margin_right_mm=margin_right_mm,
            margin_top_mm=margin_top_mm,
            margin_bottom_mm=margin_bottom_mm,
            header_margin_mm=header_margin_mm,
            footer_margin_mm=footer_margin_mm,
        )
    except Exception as exc:
        raise HwpxError(f"HWPX 용지 설정을 적용할 수 없습니다: {exc}") from exc


def set_page_number_footer(
    document: Any,
    *,
    prefix: str = "- ",
    suffix: str = " -",
) -> Any:
    require_hwpx()
    page = getattr(document, "page", None)
    setter = getattr(page, "set_page_number", None)
    if not callable(setter):
        raise HwpxError("문서 객체에 page.set_page_number 가 없습니다.")
    try:
        return setter(target="footer", prefix=prefix, suffix=suffix, align="CENTER")
    except Exception as exc:
        raise HwpxError(f"HWPX 쪽번호를 넣을 수 없습니다: {exc}") from exc


def drop_leading_empty_paragraph(document: Any) -> bool:
    """스켈레톤의 빈 첫 문단을 제거한다."""

    paragraphs = list(getattr(document, "paragraphs", []) or [])
    if not paragraphs:
        return False
    first = paragraphs[0]
    text = str(getattr(first, "text", "") or "").strip()
    tables = list(getattr(first, "tables", []) or [])
    if text or tables:
        return False
    section = getattr(first, "section", None)
    remover = getattr(section, "remove_paragraph", None)
    if not callable(remover):
        return False
    try:
        remover(first)
    except Exception:
        return False
    return True
