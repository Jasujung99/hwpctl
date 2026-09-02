"""합성 HWPML만으로 참조 구조 비교기의 안전 계약을 고정한다."""

from __future__ import annotations

from hwpctl.reference import canonical_json, compare_hwpml, normalize_hwpml


def _border_fill(
    border_id: int,
    *,
    left: str | None = None,
    right: str | None = None,
    top: str | None = None,
    bottom: str | None = None,
    fill: str | None = None,
) -> str:
    def side(tag: str, value: str | None) -> str:
        return "" if value is None else f'<{tag} Type="{value}" Width="7" Color="1"/>'

    brush = "" if fill is None else f'<FILLBRUSH><WINDOWBRUSH FaceColor="{fill}"/></FILLBRUSH>'
    return (
        f'<BORDERFILL Id="{border_id}">'
        f'{side("LEFTBORDER", left)}{side("RIGHTBORDER", right)}'
        f'{side("TOPBORDER", top)}{side("BOTTOMBORDER", bottom)}{brush}'
        "</BORDERFILL>"
    )


def _document(
    paragraphs: str,
    *,
    char_id: int = 1,
    font_id: int = 1,
    para_id: int = 1,
    font_name: str = "Test Sans",
    borders: str = "",
    drawing: bool = False,
) -> str:
    drawing_xml = "<DRAWINGOBJECT/>" if drawing else ""
    return f"""<HWPML>
  <HEAD><MAPPINGTABLE>
    <FACENAMELIST><FONTFACE Lang="Hangul"><FONT Id="{font_id}" Name="{font_name}" Type="TTF"/></FONTFACE></FACENAMELIST>
    <CHARSHAPELIST><CHARSHAPE Id="{char_id}" Height="1000" TextColor="0"><FONTID Hangul="{font_id}"/><BOLD/></CHARSHAPE></CHARSHAPELIST>
    <PARASHAPELIST><PARASHAPE Id="{para_id}" Align="Justify"><PARAMARGIN Left="0" Right="0" Indent="0" Prev="0" Next="0" LineSpacing="160"/></PARASHAPE></PARASHAPELIST>
    <BORDERFILLLIST>{borders}</BORDERFILLLIST>
  </MAPPINGTABLE></HEAD>
  <BODY><SECTION><PAGEDEF Width="59528" Height="84188"><PAGEMARGIN Left="7200" Right="7200" Top="7200" Bottom="7200"/></PAGEDEF>{paragraphs}{drawing_xml}</SECTION></BODY>
</HWPML>"""


def _paragraph(text: str = "", *, char_id: int = 1, para_id: int = 1, page_break: str = "") -> str:
    page = f' PageBreak="{page_break}"' if page_break else ""
    return f'<P ParaShape="{para_id}"{page}><TEXT CharShape="{char_id}">{text}</TEXT></P>'


def _table(cells: str, *, rows: int = 1, columns: int = 1) -> str:
    return f'<P ParaShape="1"><TEXT CharShape="1"><TABLE RowCount="{rows}" ColCount="{columns}"><ROW>{cells}</ROW></TABLE></TEXT></P>'


def _cell(
    row: int,
    column: int,
    text: str,
    *,
    border: int = 0,
    width: int = 7200,
    height: int = 3600,
    row_span: int = 1,
    column_span: int = 1,
    nested_table: str = "",
) -> str:
    content = nested_table or f'<P ParaShape="1"><TEXT CharShape="1">{text}</TEXT></P>'
    return (
        f'<CELL RowAddr="{row}" ColAddr="{column}" RowSpan="{row_span}" ColSpan="{column_span}" '
        f'Width="{width}" Height="{height}" BorderFill="{border}"><PARALIST VertAlign="Center">'
        f"{content}</PARALIST></CELL>"
    )


def test_style_and_font_ids_do_not_change_a_semantic_match() -> None:
    reference = _document(_paragraph("same"), char_id=1, font_id=1, para_id=1)
    candidate = _document(_paragraph("same", char_id=77, para_id=45), char_id=77, font_id=9, para_id=45)

    report = compare_hwpml(reference, candidate)

    assert report["status"] == "pass"
    assert report["differences"] == []
    assert report["summary"]["reference_visible_text"] == report["summary"]["candidate_visible_text"]


def test_inserted_blank_paragraphs_do_not_shift_the_final_table() -> None:
    borders = _border_fill(1, top="Solid", bottom="Solid")
    final_table = _table(_cell(0, 0, "last cell", border=1))
    reference = _document(_paragraph("intro") + final_table, borders=borders)
    candidate = _document(_paragraph("intro") + _paragraph() + _paragraph() + final_table, borders=borders)

    report = compare_hwpml(reference, candidate)

    assert report["status"] == "different"
    kinds = [item["kind"] for item in report["differences"]]
    assert kinds == ["extra_blank_paragraph", "extra_blank_paragraph"]
    assert "missing_block" not in kinds
    assert "extra_block" not in kinds


def test_shared_border_is_equal_when_saved_on_opposite_cell() -> None:
    reference_borders = _border_fill(1, right="Solid") + _border_fill(2)
    candidate_borders = _border_fill(1) + _border_fill(2, left="Solid")
    cells_reference = _cell(0, 0, "A", border=1) + _cell(0, 1, "B", border=2)
    cells_candidate = _cell(0, 0, "A", border=1) + _cell(0, 1, "B", border=2)
    reference = _document(_table(cells_reference, columns=2), borders=reference_borders)
    candidate = _document(_table(cells_candidate, columns=2), borders=candidate_borders)

    report = compare_hwpml(reference, candidate)

    assert report["status"] == "pass"
    assert report["differences"] == []


def test_conflicting_shared_border_is_reported() -> None:
    reference_borders = _border_fill(1, right="Solid") + _border_fill(2)
    candidate_borders = _border_fill(1, right="Solid") + _border_fill(2, left="Dotted")
    cells = _cell(0, 0, "A", border=1) + _cell(0, 1, "B", border=2)
    reference = _document(_table(cells, columns=2), borders=reference_borders)
    candidate = _document(_table(cells, columns=2), borders=candidate_borders)

    report = compare_hwpml(reference, candidate)

    assert report["status"] == "different"
    assert "candidate_border_conflict" in {item["kind"] for item in report["differences"]}


def test_cell_geometry_compares_raw_hwp_units_without_mm_rounding() -> None:
    borders = _border_fill(1)
    reference = _document(_table(_cell(0, 0, "cell", border=1, width=7200)), borders=borders)
    candidate = _document(_table(_cell(0, 0, "cell", border=1, width=7201)), borders=borders)

    report = compare_hwpml(reference, candidate)

    assert report["status"] == "different"
    assert "cell_geometry" in {item["kind"] for item in report["differences"]}


def test_unsupported_drawing_makes_an_otherwise_equal_result_inconclusive() -> None:
    reference = _document(_paragraph("same"), drawing=True)
    candidate = _document(_paragraph("same"), drawing=True)

    report = compare_hwpml(reference, candidate)

    assert report["status"] == "inconclusive"
    assert report["coverage"]["drawings"] == "unsupported"
    assert report["complete"] is False


def test_report_is_deterministic_and_does_not_expose_visible_text() -> None:
    secret = "private document phrase"
    reference = _document(_paragraph(secret))
    candidate = _document(_paragraph(secret) + _paragraph())

    first = compare_hwpml(reference, candidate)
    second = compare_hwpml(reference, candidate)
    encoded = canonical_json(first)

    assert encoded == canonical_json(second)
    assert secret not in encoded
    assert "reference_path" not in encoded


def test_repeated_nonblank_blocks_are_inconclusive_not_arbitrarily_paired() -> None:
    reference = _document(_paragraph("repeat") + _paragraph("repeat"))
    candidate = _document(_paragraph("repeat") + _paragraph("repeat"))

    report = compare_hwpml(reference, candidate)

    assert report["status"] == "inconclusive"
    assert {item["kind"] for item in report["differences"]} == {"ambiguous_block_alignment"}


def test_nested_tables_and_columns_beyond_z_use_numeric_grid_coordinates() -> None:
    inner_cell = _cell(0, 0, "inside", border=0)
    nested = _table(inner_cell)
    outer_cell = _cell(0, 27, "", border=0, nested_table=nested)
    document = _document(_table(outer_cell, columns=28))

    normalized = normalize_hwpml(document)
    cell = normalized.blocks[0].table.cells[0]  # type: ignore[union-attr]

    assert cell.key == (0, 27, 1, 1)
    assert cell.paragraphs[0].table is not None
    assert compare_hwpml(document, document)["status"] == "pass"


def test_run_segmentation_is_reported_separately_from_visible_text() -> None:
    reference = _document(_paragraph("ABC"))
    candidate = _document('<P ParaShape="1"><TEXT CharShape="1">A</TEXT><TEXT CharShape="1">BC</TEXT></P>')

    report = compare_hwpml(reference, candidate)

    kinds = {item["kind"] for item in report["differences"]}
    assert report["status"] == "different"
    assert "run_formatting" in kinds
    assert "visible_text" not in kinds
