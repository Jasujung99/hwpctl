"""글맵시 실측 사실과 한/글 없는 리더를 합성 테스트 자료로 고정한다(Linux CI에서도 실행)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpctl.errors import UsageError
from hwpctl.textart import (
    ALIGNS,
    FONT_STYLES,
    SHAPES,
    align_name,
    font_style_key,
    read_text_arts,
    shape_index,
    shape_name,
    text_from_file,
    text_to_com,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "textart"


def test_shape_table_matches_hangul_2022_measurement() -> None:
    assert len(SHAPES) == 55 and len(set(SHAPES)) == 55
    assert (SHAPES[0], SHAPES[17], SHAPES[42], SHAPES[54]) == (
        "PARALLELOGRAM", "WAVE2", "RECTANGLE", "DOUBLE_LINE_CIRCLE")
    assert shape_index("rectangle") == 42 and shape_index(" Wave2 ") == 17
    assert shape_name(42) == "rectangle" and shape_name("17") == "wave2" and shape_name("WAVE2") == "wave2"
    for bad in ("square", "", None, 55, "55"):
        with pytest.raises(UsageError):
            shape_index(bad) if not isinstance(bad, int) else shape_name(bad)


def test_align_style_and_newline_mappings() -> None:
    assert ALIGNS == ("left", "right", "center", "full")
    assert [align_name(index) for index in range(4)] == list(ALIGNS)
    assert align_name("FULL") == "full" and align_name("Center") == "center"
    assert [font_style_key(name) for name in FONT_STYLES.values()] == list(FONT_STYLES)
    assert text_from_file("첫째 줄␍␊둘째 줄") == "첫째 줄\n둘째 줄"
    assert text_to_com("a\nb\r\nc") == "a\r\nb\r\nc"
    with pytest.raises(UsageError):
        align_name(4)
    with pytest.raises(UsageError):
        font_style_key("heavy")


@pytest.mark.parametrize("name", ["ui-wave2-linear", "com-two-text-arts", "variants"])
def test_hwpx_and_hwpml_exports_agree(name: str) -> None:
    hwpx = read_text_arts(FIXTURES / f"{name}.hwpx")
    hwpml = read_text_arts(FIXTURES / f"{name}.hwpml")
    assert hwpx and hwpx == hwpml


def test_ui_created_gradient_text_art() -> None:
    (art,) = read_text_arts(FIXTURES / "ui-wave2-linear.hwpx")
    assert art["text"] == "그라데이션 샘플"
    assert (art["font_name"], art["font_style"], art["font_type"]) == ("함초롬바탕", "regular", "ttf")
    assert (art["shape"], art["align"], art["line_spacing_percent"], art["char_spacing_percent"]) == (
        "wave2", "left", 120, 100)
    assert (art["width_hu"], art["height_hu"]) == (16500, 5000)
    assert art["treat_as_char"] is False and (art["vert_rel_to"], art["horz_rel_to"]) == ("para", "column")
    assert art["fill"] == {"type": "linear_gradient", "angle": 0, "center_x": 0, "center_y": 0,
                           "step": 255, "step_center": 50, "alpha": 0, "colors": ["#FF0000", "#0000FF"]}
    assert art["line_style"] == "none" and art["comment"] == "글맵시입니다."


def test_com_created_text_art_records_paper_anchor_and_z_order() -> None:
    ui, com = read_text_arts(FIXTURES / "com-two-text-arts.hwpx")
    assert ui["z_order"] == 0 and com["z_order"] == 1
    assert (com["text"], com["font_name"], com["shape"]) == ("COM 글맵시 그라데이션", "함초롬돋움", "parallelogram")
    assert com["fill"]["angle"] == 90 and com["fill"]["colors"] == ["#FFA500", "#800080"]
    # COM으로 만든 글맵시의 기본 위치는 UI와 다르다(종이 기준, 글과 함께 이동 안 함).
    assert (com["vert_rel_to"], com["flow_with_text"]) == ("paper", False)


def test_variants_cover_alignment_styles_hft_and_multiline() -> None:
    arts = {art["text"]: art for art in read_text_arts(FIXTURES / "variants.hwpx")}
    assert [arts[f"A{index}"]["align"] for index in range(4)] == list(ALIGNS)
    assert [arts["F" + localized]["font_style"] for localized in FONT_STYLES.values()] == list(FONT_STYLES)
    # FontType=2(HFT)를 줘도 한/글 2022는 TTF로 저장한다.
    assert (arts["HFT"]["font_name"], arts["HFT"]["font_type"]) == ("한양견고딕", "ttf")
    assert "첫째 줄\n둘째 줄" in arts
    assert all(art["shape"] == "rectangle" for art in arts.values())
    # COM TextArtCreate의 기본 채우기는 파란 단색이다.
    assert arts["A0"]["fill"] == {"type": "solid", "color": "#0000FF", "alpha": 0}


def test_reader_rejects_other_formats(tmp_path: Path) -> None:
    other = tmp_path / "a.hwp"
    other.write_bytes(b"")
    with pytest.raises(UsageError):
        read_text_arts(other)
