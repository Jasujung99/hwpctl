"""AlignType 맵·그룹화·쪽 이미지 경로. 한/글 없이 동작해야 한다."""

from __future__ import annotations

from pathlib import Path

from hwpctl.format_inspect import (
    ALIGN_TYPE_MAP,
    convert_bmp_with_pillow,
    group_format_rows,
    map_align_type,
    page_image_write_plan,
    resolve_page_image_path,
)
from hwpctl.lock import default_runtime_dir


def test_align_type_map_matches_hangul_2022() -> None:
    assert ALIGN_TYPE_MAP == {
        0: "justify",
        1: "left",
        2: "right",
        3: "center",
        4: "distribute",
    }
    assert map_align_type(0) == "justify"
    assert map_align_type(1) == "left"
    assert map_align_type(2) == "right"
    assert map_align_type(3) == "center"
    assert map_align_type(4) == "distribute"
    assert map_align_type("3") == "center"
    assert map_align_type("Center") == "center"
    assert map_align_type(None) == "left"
    assert map_align_type(9) == "unknown:9"


def test_group_consecutive_same_format() -> None:
    rows = [
        {
            "align": "center",
            "font": "함초롬돋움",
            "size_pt": 20,
            "bold": True,
            "color": 0,
            "snippet": "제목",
            "in_table": False,
        },
        {
            "align": "center",
            "font": "함초롬돋움",
            "size_pt": 20.0,
            "bold": True,
            "color": 0,
            "snippet": "부제",
            "in_table": False,
        },
        {
            "align": "left",
            "font": "함초롬바탕",
            "size_pt": 10,
            "bold": False,
            "color": 255,
            "snippet": "본문",
            "in_table": False,
        },
        {
            "align": "left",
            "font": "함초롬바탕",
            "size_pt": 10,
            "bold": False,
            "color": 255,
            "snippet": "표 안",
            "in_table": True,
        },
        {
            "align": "center",
            "font": "함초롬돋움",
            "size_pt": 20,
            "bold": True,
            "color": 0,
            "snippet": "다시 제목",
            "in_table": False,
        },
    ]
    groups = group_format_rows(rows)
    assert len(groups) == 3
    assert groups[0]["count"] == 2
    assert groups[0]["samples"] == ["제목", "부제"]
    assert groups[0]["key"] == {
        "align": "center",
        "font": "함초롬돋움",
        "size_pt": 20,
        "bold": True,
        "color": 0,
    }
    assert groups[0]["in_table"] is False
    assert groups[1]["count"] == 2
    assert groups[1]["samples"] == ["본문", "표 안"]
    assert groups[1]["in_table"] is True
    assert groups[2]["count"] == 1
    assert groups[2]["samples"] == ["다시 제목"]


def test_group_empty_and_single() -> None:
    assert group_format_rows([]) == []
    one = group_format_rows(
        [{"align": "left", "font": "굴림", "size_pt": 13, "bold": False, "color": 0, "snippet": ""}]
    )
    assert one[0]["count"] == 1
    assert one[0]["samples"] == []


def test_page_image_write_plan_converts_png_jpg() -> None:
    dest = Path("C:/tmp/now.png")
    bmp, convert = page_image_write_plan(dest)
    assert bmp.suffix.lower() == ".bmp"
    assert convert == dest
    dest_jpg = Path("/tmp/a.JPG")
    bmp2, convert2 = page_image_write_plan(dest_jpg)
    assert bmp2.suffix.lower() == ".bmp"
    assert convert2 == dest_jpg
    dest_bmp = Path("/tmp/page-1.bmp")
    bmp3, convert3 = page_image_write_plan(dest_bmp)
    assert bmp3 == dest_bmp
    assert convert3 is None


def test_resolve_page_image_default_uses_runtime_dir() -> None:
    path = resolve_page_image_path("", 3)
    assert path == default_runtime_dir() / "page-3.bmp"
    assert resolve_page_image_path("C:/out/a.png", 1) == Path("C:/out/a.png")


def test_convert_bmp_without_pillow_korean(monkeypatch, tmp_path: Path) -> None:
    import builtins

    import pytest

    from hwpctl.errors import HangulCommandError

    bmp = tmp_path / "page.bmp"
    bmp.write_bytes(b"BM" + b"\x00" * 32)
    dest = tmp_path / "page.png"
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("no pillow")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(HangulCommandError) as exc:
        convert_bmp_with_pillow(bmp, dest)
    assert "Pillow" in exc.value.message
