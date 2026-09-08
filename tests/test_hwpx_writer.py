"""Generic HWPX regressions extracted from fixtures/gongo-doc1; no notice assets."""
from pathlib import Path
import pytest
from hwpctl.hwpx.document import hwpx_available
from hwpctl.hwpx.inspect import inspect_hwpx
pytestmark = pytest.mark.skipif(not hwpx_available(), reason="python-hwpx extra required")


def test_run_replacement_preserves_section_and_native_table(tmp_path):
    from hwpctl.hwpx import new_document, save_document, create_table_and_fill, set_paragraph_runs
    doc = new_document()
    try:
        title = doc.paragraphs[0]
        set_paragraph_runs(doc, [{"text": "앞", "bold": True}, {"text": "뒤"}], paragraph=title)
        table = create_table_and_fill(doc, 1, 1, [["셀 보존"]])
        anchor = next(p for p in doc.paragraphs if any(e.tag.rsplit("}", 1)[-1] == "tbl" for e in p.element.iter()))
        set_paragraph_runs(doc, [{"text": "교체"}], paragraph=anchor)
        output = tmp_path / "controls.hwpx"
        save_document(doc, output)
    finally:
        doc.close()
    report = inspect_hwpx(output)
    assert report["table_count"] == 1
    assert report["section_page_properties"][0]["sec_pr_count"] == 1
    assert any(r["text"] == "셀 보존" for r in report["runs"])


def test_cell_paragraph_format_leaves_no_temporary_body_paragraph():
    from hwpctl.hwpx import new_document, create_table_and_fill, apply_paragraph_format
    doc = new_document()
    try:
        table = create_table_and_fill(doc, 1, 1, [["내용"]])
        before = len(doc.paragraphs)
        apply_paragraph_format(doc, paragraph=table.cell(0, 0).paragraphs[0], alignment="CENTER", line_spacing_percent=140)
        assert len(doc.paragraphs) == before
        assert table.cell(0, 0).text == "내용"
    finally:
        doc.close()


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, 0, True])
def test_invalid_table_geometry_is_rejected_before_insertion(bad):
    from hwpctl.errors import UsageError
    from hwpctl.hwpx import new_document, create_table_and_fill
    doc = new_document()
    try:
        before = len(doc.paragraphs)
        with pytest.raises(UsageError):
            create_table_and_fill(doc, 1, 1, column_widths_mm=[bad])
        assert len(doc.paragraphs) == before
        assert not any(e.tag.rsplit("}", 1)[-1] == "tbl" for p in doc.paragraphs for e in p.element.iter())
    finally:
        doc.close()


def test_bad_later_run_does_not_erase_original_text():
    from hwpctl.errors import UsageError
    from hwpctl.hwpx import new_document, insert_paragraph, set_paragraph_runs
    doc = new_document()
    try:
        paragraph = insert_paragraph(doc, "원문 보존")
        with pytest.raises(UsageError):
            set_paragraph_runs(doc, [{"text": "첫째"}, {"text": "둘째", "size": float("nan")}], paragraph=paragraph)
        assert paragraph.text == "원문 보존"
    finally:
        doc.close()

def test_writer_round_trip_keeps_rich_run_paragraph_and_table_styles(tmp_path: Path) -> None:
    from hwpctl.hwpx.document import (
        close_document,
        new_document,
        open_document,
        save_document,
    )
    from hwpctl.hwpx.write import (
        append_run,
        apply_paragraph_format,
        create_table_and_fill,
        insert_paragraph,
        set_run_props,
    )

    doc = new_document()
    try:
        paragraph = insert_paragraph(doc, "일반 본문", inherit_style=False)
        set_run_props(
            doc,
            paragraph=paragraph,
            font="휴먼명조",
            size=11.5,
            color="#202020",
        )
        append_run(
            doc,
            " 마감 시각",
            paragraph=paragraph,
            font="휴먼명조",
            size=11.5,
            color="#FF0000",
            underline=True,
            underline_shape="SOLID",
            underline_color="#FF0000",
        )
        base = insert_paragraph(doc, "원본 서식", inherit_style=False)
        base_style = set_run_props(
            doc,
            paragraph=base,
            font="휴먼명조",
            size=11.5,
            bold=True,
            underline=True,
        )
        inherited = insert_paragraph(doc, "상속 런", inherit_style=False)
        set_run_props(
            doc,
            paragraph=inherited,
            base_char_pr_id=base_style["char_pr_id"],
            color="#002060",
        )
        apply_paragraph_format(
            doc,
            paragraph=paragraph,
            alignment="JUSTIFY",
            line_spacing_percent=160,
        )
        create_table_and_fill(
            doc,
            2,
            2,
            [["항목", "값"], ["A", "1"]],
            header_fill="#FCF5E7",
            width_mm=168,
            height_mm=20,
            column_widths_mm=(136, 32),
            border_color="#777777",
            border_width="0.12 mm",
        )
        out = tmp_path / "rich-round-trip.hwpx"
        save_document(doc, out)
    finally:
        close_document(doc)

    round_tripped = tmp_path / "rich-round-tripped.hwpx"
    reopened = open_document(out)
    try:
        save_document(reopened, round_tripped)
    finally:
        close_document(reopened)

    inspected = inspect_hwpx(round_tripped)
    assert "휴먼명조" in inspected["definitions"]["fonts"].values()
    body_group = next(
        group
        for group in inspected["paragraph_groups"]
        if "일반 본문" in group["sample_text"]
    )
    assert body_group["align"] == "JUSTIFY"
    assert body_group["line_spacing_percent"] == 160

    deadline_group = next(
        group for group in inspected["run_groups"] if "마감 시각" in group["sample_text"]
    )
    assert deadline_group["font"] == "휴먼명조"
    assert deadline_group["size_pt"] == 11.5
    assert deadline_group["color"] == "#FF0000"
    assert deadline_group["underline"] is True
    assert deadline_group["underline_color"] == "#FF0000"
    inherited_run = next(
        run for run in inspected["runs"] if run["text"] == "상속 런"
    )
    assert inherited_run["font"] == "휴먼명조"
    assert inherited_run["size_pt"] == 11.5
    assert inherited_run["bold"] is True
    assert inherited_run["color"] == "#002060"
    assert inherited_run["underline"] is True

    cream_cells = next(
        group
        for group in inspected["cell_fill_groups"]
        if group["fill"] == "#FCF5E7"
    )
    assert cream_cells["borders"]["left"] == {
        "type": "SOLID",
        "width": "0.12 mm",
        "color": "#777777",
    }
    table = next(table for table in inspected["tables"] if table["width_mm"] == 168.0)
    assert table["cell_widths_hwpunit"][:2] == [38551, 9071]



def test_page_setup_writes_hangul_portrait_orientation_token(tmp_path: Path) -> None:
    from hwpctl.hwpx.document import (
        close_document,
        new_document,
        open_document,
        save_document,
    )
    from hwpctl.hwpx.write import HWPX_PORTRAIT, set_page_setup

    doc = new_document()
    try:
        set_page_setup(
            doc,
            paper_size="A4",
            orientation="PORTRAIT",
            margin_left_mm=20,
            margin_right_mm=20,
        )
        out = tmp_path / "a4-portrait.hwpx"
        save_document(doc, out)
    finally:
        close_document(doc)

    reopened = open_document(out)
    round_tripped = tmp_path / "a4-portrait-round-tripped.hwpx"
    try:
        save_document(reopened, round_tripped)
    finally:
        close_document(reopened)

    inspected = inspect_hwpx(round_tripped)
    section = inspected["section_page_properties"][0]
    assert section["sec_pr_count"] == 1
    assert section["page_pr_count"] == 1
    page = section["pages"][0]
    # Hangul's OWPML flag is WIDELY for 세로; PORTRAIT is not a legal
    # `pagePr/@landscape` value even though it looks more intuitive.
    assert page["landscape_attr"] == HWPX_PORTRAIT == "WIDELY"
    assert page["width_hwpunit"] == 59528
    assert page["height_hwpunit"] == 84189
    assert page["width_hwpunit"] < page["height_hwpunit"]



def test_page_setup_writes_hangul_landscape_orientation_token(tmp_path: Path) -> None:
    from hwpctl.hwpx.document import close_document, new_document, save_document
    from hwpctl.hwpx.write import HWPX_LANDSCAPE, set_page_setup

    doc = new_document()
    try:
        set_page_setup(doc, paper_size="A4", orientation="LANDSCAPE")
        out = tmp_path / "a4-landscape.hwpx"
        save_document(doc, out)
    finally:
        close_document(doc)

    page = inspect_hwpx(out)["section_page_properties"][0]["pages"][0]
    # HWPX keeps A4's physical dimensions; Hangul rotates it from this
    # NARROWLY token rather than from a width/height swap.
    assert page["landscape_attr"] == HWPX_LANDSCAPE == "NARROWLY"
    assert page["width_hwpunit"] == 59528
    assert page["height_hwpunit"] == 84189
    assert page["width_hwpunit"] < page["height_hwpunit"]
