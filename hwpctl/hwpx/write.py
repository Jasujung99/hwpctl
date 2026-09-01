"""HWPX 쓰기 준비 래퍼. 공고문 재현은 다음 단계.

``python-hwpx`` 6.x 고수준 API 가 분명한 것만 얇게 감싼다.
저수준 ``add_shape`` / ``add_control`` 은 깨진 파일을 만들 수 있어 노출하지 않는다.
"""

from __future__ import annotations

from typing import Any, Sequence

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


def set_run_props(
    document: Any,
    *,
    paragraph_index: int | None = None,
    run_index: int | None = None,
    base_char_pr_id: str | int | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
    font: str | None = None,
    size: float | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    """``styles.ensure_run`` 으로 charPr 을 보장한 뒤 런에 연결한다.

    ``base_char_pr_id`` 에 원본 검사 그룹의 ``char_pr_id`` 를 넘기면
    상속 후 일부 속성만 덮어쓸 수 있다(다음 단계 재현용).
    """

    require_hwpx()
    styles = getattr(document, "styles", None)
    ensure = getattr(styles, "ensure_run", None)
    if not callable(ensure):
        raise HwpxError("python-hwpx styles.ensure_run 을 쓸 수 없습니다.")

    kwargs: dict[str, Any] = {}
    if bold is not None:
        kwargs["bold"] = bold
    if italic is not None:
        kwargs["italic"] = italic
    if font:
        kwargs["font"] = font
    if size is not None:
        kwargs["size"] = size
    if color:
        kwargs["color"] = color
    if base_char_pr_id is not None:
        kwargs["base_char_pr_id"] = base_char_pr_id
    if not kwargs:
        raise UsageError("적용할 글자 서식이 없습니다.")

    try:
        char_pr_id = ensure(**kwargs)
    except Exception as exc:
        raise HwpxError(f"HWPX 글자 서식을 만들 수 없습니다: {exc}") from exc

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


def create_table_and_fill(
    document: Any,
    rows: int,
    cols: int,
    cells: Sequence[Sequence[Any]] | None = None,
    *,
    header_fill: str = "",
) -> Any:
    """표 생성 후 셀 텍스트·첫 행 배경. ``add_table`` / ``set_cell_text`` / ``set_cell_shading``."""

    require_hwpx()
    if rows < 1 or cols < 1:
        raise UsageError("표 행·열은 1 이상이어야 합니다.")
    adder = getattr(document, "add_table", None)
    if not callable(adder):
        raise HwpxError("문서 객체에 add_table 이 없습니다.")
    try:
        table = adder(rows, cols)
    except Exception as exc:
        raise HwpxError(f"HWPX 표를 만들 수 없습니다: {exc}") from exc

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
        shader = getattr(table, "set_cell_shading", None)
        if not callable(shader):
            raise HwpxError("표 객체에 set_cell_shading 이 없습니다.")
        for col_idx in range(cols):
            try:
                shader(0, col_idx, fill)
            except Exception as exc:
                raise HwpxError(f"HWPX 헤더 배경을 칠할 수 없습니다: {exc}") from exc

    return table


def apply_paragraph_align(
    document: Any,
    alignment: str,
    *,
    paragraph_index: int | None = None,
) -> Any:
    """문단 가로 정렬. ``styles.apply_paragraph_format`` 래퍼."""

    require_hwpx()
    key = (alignment or "").strip().upper()
    if key not in {"LEFT", "CENTER", "RIGHT", "JUSTIFY"}:
        raise UsageError(
            "문단 정렬은 left/center/right/justify 중 하나여야 합니다."
        )
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
    try:
        return apply(paragraph_index=idx, alignment=key)
    except Exception as exc:
        raise HwpxError(f"HWPX 문단 정렬을 적용할 수 없습니다: {exc}") from exc
