from __future__ import annotations

import struct
from pathlib import Path

import pytest

from hwpctl.visual import Bitmap, compare_regions, ink_lines, read_bitmap, write_ppm

WHITE = (255, 255, 255)
INK = (20, 40, 90)


def _canvas(width: int, height: int, color=WHITE) -> bytearray:
    return bytearray(bytes(color) * (width * height))


def _fill(buf: bytearray, width: int, box, color=INK) -> None:
    x0, y0, x1, y1 = box
    for y in range(y0, y1):
        for x in range(x0, x1):
            i = (y * width + x) * 3
            buf[i : i + 3] = bytes(color)


def _write_bmp(path: Path, width: int, height: int, rgb: bytes, bpp: int = 24) -> None:
    step = bpp // 8
    stride = ((bpp * width + 31) // 32) * 4
    rows = []
    for y in range(height - 1, -1, -1):  # bottom-up
        row = bytearray()
        for x in range(width):
            i = (y * width + x) * 3
            r, g, b = rgb[i : i + 3]
            row += bytes((b, g, r)) + (b"\xff" if step == 4 else b"")
        rows.append(bytes(row) + b"\x00" * (stride - len(row)))
    pixels = b"".join(rows)
    header = b"BM" + struct.pack("<IHHI", 54 + len(pixels), 0, 0, 54)
    dib = struct.pack("<IiiHHIIiiII", 40, width, height, 1, bpp, 0, len(pixels), 2835, 2835, 0, 0)
    path.write_bytes(header + dib + pixels)


@pytest.mark.parametrize("bpp", [24, 32])
def test_bmp_and_ppm_round_trip(tmp_path: Path, bpp: int) -> None:
    buf = _canvas(7, 5)
    _fill(buf, 7, (1, 1, 3, 4))
    _write_bmp(tmp_path / "a.bmp", 7, 5, bytes(buf), bpp)
    bmp = read_bitmap(tmp_path / "a.bmp")
    assert (bmp.width, bmp.height) == (7, 5)
    assert bmp.rgb == bytes(buf)  # 위→아래 RGB로 정규화
    write_ppm(tmp_path / "a.ppm", bmp)
    assert read_bitmap(tmp_path / "a.ppm") == bmp


def test_ink_lines_splits_lines_by_gap_and_uses_background() -> None:
    width, height = 60, 40
    background = _canvas(width, height, (250, 240, 200))
    image = bytearray(background)
    _fill(image, width, (5, 5, 30, 10))   # 첫 줄
    _fill(image, width, (8, 20, 50, 26))  # 둘째 줄
    lines = ink_lines(Bitmap(width, height, bytes(image)), Bitmap(width, height, bytes(background)),
                      (0, 0, width, height), min_gap_px=3)
    assert lines == [(5, 5, 29, 9), (8, 20, 49, 25)]
    # 배경이 없으면 모서리 단색을 배경으로 본다.
    assert ink_lines(Bitmap(width, height, bytes(image)), None, (0, 0, width, height), min_gap_px=3) == lines


def test_compare_regions_reports_mm_offsets_across_resolutions() -> None:
    # 100 x 50 mm 종이: 원본 2 px/mm, 결과 1 px/mm
    ref = _canvas(200, 100)
    _fill(ref, 200, (20, 20, 100, 30))  # (10,10)~(50,15) mm
    cand = _canvas(100, 50)
    _fill(cand, 100, (11, 12, 51, 17))  # (11,12)~(51,17) mm
    result = compare_regions(
        Bitmap(200, 100, bytes(ref)),
        Bitmap(100, 50, bytes(cand)),
        [{"name": "title", "x_mm": 0, "y_mm": 0, "w_mm": 100, "h_mm": 50}],
        paper_mm=[100, 50],
    )
    line = result["regions"][0]["lines"][0]
    assert line["dx"] == 1.0 and line["dy"] == 2.0
    assert result["max_offset_mm"] == 2.0
    assert result["line_count_mismatches"] == []


def test_read_bitmap_rejects_unknown_format(tmp_path: Path) -> None:
    (tmp_path / "x.png").write_bytes(b"\x89PNG....")
    with pytest.raises(ValueError):
        read_bitmap(tmp_path / "x.png")
