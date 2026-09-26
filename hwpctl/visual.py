"""쪽 렌더 결과와 원본 이미지의 글자 줄 위치를 mm로 비교한다(외부 라이브러리 없음).

원본(예: PowerPoint 슬라이드 내보내기)과 결과(한/글 ``CreatePageImage``)는
렌더러가 달라 픽셀 단위 전체 비교가 의미 없다. 대신 같은 "배경"(글자를 뺀
렌더)과의 차이로 글자 잉크를 찾아 영역별 줄 경계 상자를 mm로 구하고, 원본과
결과의 줄을 순서대로 짝지어 위치·크기 차이를 돌려준다. 이 값으로 개체 위치를
보정하면 눈대중 없이 몇 번 만에 맞출 수 있다.

지원 형식: 24/32비트 BMP(BI_RGB·BI_BITFIELDS), 8비트 PPM(P6).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any, Iterable, Sequence


@dataclass(frozen=True)
class Bitmap:
    width: int
    height: int
    rgb: bytes  # 위→아래, 행마다 width*3 바이트

    def row(self, y: int) -> bytes:
        start = y * self.width * 3
        return self.rgb[start : start + self.width * 3]


def read_bitmap(path: str | PathLike[str]) -> Bitmap:
    data = Path(path).read_bytes()
    if data[:2] == b"BM":
        return _read_bmp(data, str(path))
    if data[:2] == b"P6":
        return _read_ppm(data, str(path))
    raise ValueError(f"지원하지 않는 이미지 형식입니다(BMP/PPM만 지원): {path}")


def write_ppm(path: str | PathLike[str], bitmap: Bitmap) -> None:
    header = f"P6\n{bitmap.width} {bitmap.height}\n255\n".encode("ascii")
    Path(path).write_bytes(header + bitmap.rgb)


def _read_bmp(data: bytes, label: str) -> Bitmap:
    offset = struct.unpack_from("<I", data, 10)[0]
    width, height = struct.unpack_from("<ii", data, 18)
    bpp = struct.unpack_from("<H", data, 28)[0]
    compression = struct.unpack_from("<I", data, 30)[0]
    if bpp not in (24, 32) or compression not in (0, 3):
        raise ValueError(f"24/32비트 비압축 BMP만 지원합니다: {label} (bpp={bpp}, compression={compression})")
    top_down = height < 0
    height = abs(height)
    step = bpp // 8
    stride = ((bpp * width + 31) // 32) * 4
    out = bytearray(width * height * 3)
    for y in range(height):
        src_y = y if top_down else height - 1 - y
        start = offset + src_y * stride
        row = data[start : start + width * step]
        dst = y * width * 3
        # BGR(A) → RGB
        out[dst : dst + width * 3 : 3] = row[2::step]
        out[dst + 1 : dst + width * 3 : 3] = row[1::step]
        out[dst + 2 : dst + width * 3 : 3] = row[0::step]
    return Bitmap(width, height, bytes(out))


def _read_ppm(data: bytes, label: str) -> Bitmap:
    tokens: list[bytes] = []
    cursor = 2
    while len(tokens) < 3:
        while data[cursor : cursor + 1].isspace():
            cursor += 1
        if data[cursor : cursor + 1] == b"#":
            cursor = data.index(b"\n", cursor) + 1
            continue
        end = cursor
        while not data[end : end + 1].isspace():
            end += 1
        tokens.append(data[cursor:end])
        cursor = end
    width, height, maxval = (int(t) for t in tokens)
    if maxval != 255:
        raise ValueError(f"8비트 PPM만 지원합니다: {label}")
    cursor += 1
    return Bitmap(width, height, data[cursor : cursor + width * height * 3])


def ink_lines(
    image: Bitmap,
    background: Bitmap | None,
    box_px: tuple[int, int, int, int],
    *,
    threshold: int = 60,
    min_gap_px: int = 4,
    min_pixels: int = 3,
) -> list[tuple[int, int, int, int]]:
    """영역 안 글자 줄 경계 상자(px, 끝 포함)를 위에서부터 돌려준다.

    ``background`` 가 있으면 같은 크기의 배경과 RGB 절대차 합이 ``threshold``를
    넘는 픽셀을 잉크로 본다. 없으면 영역 네 모서리 색의 평균을 단색 배경으로 쓴다.
    """

    x0, y0, x1, y1 = _clip(box_px, image.width, image.height)
    if background is not None and (background.width, background.height) != (image.width, image.height):
        raise ValueError("배경과 이미지의 픽셀 크기가 같아야 합니다.")
    flat = None if background is not None else _corner_color(image, (x0, y0, x1, y1))
    rows: list[tuple[int, int, int]] = []
    for y in range(y0, y1):
        row = image.row(y)[x0 * 3 : x1 * 3]
        base = background.row(y)[x0 * 3 : x1 * 3] if background is not None else None
        if base is not None and row == base:
            continue
        first = last = -1
        count = 0
        for i in range(0, len(row), 3):
            if base is not None:
                diff = abs(row[i] - base[i]) + abs(row[i + 1] - base[i + 1]) + abs(row[i + 2] - base[i + 2])
            else:
                diff = abs(row[i] - flat[0]) + abs(row[i + 1] - flat[1]) + abs(row[i + 2] - flat[2])
            if diff > threshold:
                count += 1
                if first < 0:
                    first = i // 3
                last = i // 3
        if count >= min_pixels:
            rows.append((y, x0 + first, x0 + last))
    lines: list[tuple[int, int, int, int]] = []
    for y, left, right in rows:
        if lines and y - lines[-1][3] <= min_gap_px:
            lx0, ly0, lx1, _ = lines[-1]
            lines[-1] = (min(lx0, left), ly0, max(lx1, right), y)
        else:
            lines.append((left, y, right, y))
    return lines


def compare_regions(
    reference: str | PathLike[str] | Bitmap,
    candidate: str | PathLike[str] | Bitmap,
    regions: Sequence[dict[str, Any]],
    *,
    paper_mm: Sequence[float],
    reference_background: str | PathLike[str] | Bitmap | None = None,
    candidate_background: str | PathLike[str] | Bitmap | None = None,
    threshold: int = 60,
    candidate_threshold: int | None = None,
    min_gap_mm: float = 0.8,
) -> dict[str, Any]:
    """영역별 원본·결과 글자 줄 상자(mm)와 차이를 돌려준다.

    ``regions`` 원소: ``{"name", "x_mm", "y_mm", "w_mm", "h_mm"}`` (종이 기준).
    두 이미지는 같은 종이(``paper_mm``)를 렌더한 것이어야 하며 해상도는 달라도 된다.
    """

    ref = _as_bitmap(reference)
    cand = _as_bitmap(candidate)
    ref_bg = _as_bitmap(reference_background) if reference_background is not None else None
    cand_bg = _as_bitmap(candidate_background) if candidate_background is not None else None
    if cand_bg is None and ref_bg is not None and (ref_bg.width, ref_bg.height) == (cand.width, cand.height):
        cand_bg = ref_bg
    paper_w, paper_h = float(paper_mm[0]), float(paper_mm[1])
    if paper_w <= 0 or paper_h <= 0:
        raise ValueError("paper_mm은 양수 [가로, 세로]여야 합니다.")

    results = []
    worst = 0.0
    for region in regions:
        name = str(region.get("name", f"region{len(results) + 1}"))
        box = [float(region[k]) for k in ("x_mm", "y_mm", "w_mm", "h_mm")]
        ref_lines = _lines_mm(ref, ref_bg, box, paper_w, paper_h, threshold, min_gap_mm)
        cand_lines = _lines_mm(cand, cand_bg, box, paper_w, paper_h,
                               candidate_threshold if candidate_threshold is not None else threshold, min_gap_mm)
        pairs = []
        for index in range(max(len(ref_lines), len(cand_lines))):
            r = ref_lines[index] if index < len(ref_lines) else None
            c = cand_lines[index] if index < len(cand_lines) else None
            entry: dict[str, Any] = {"reference": r, "candidate": c}
            if r and c:
                entry.update(
                    dx=round(c[0] - r[0], 2),
                    dy=round(c[1] - r[1], 2),
                    dw=round((c[2] - c[0]) - (r[2] - r[0]), 2),
                    dh=round((c[3] - c[1]) - (r[3] - r[1]), 2),
                )
                worst = max(worst, abs(entry["dx"]), abs(entry["dy"]))
            pairs.append(entry)
        results.append(
            {
                "name": name,
                "reference_lines": len(ref_lines),
                "candidate_lines": len(cand_lines),
                "line_count_matches": len(ref_lines) == len(cand_lines),
                "lines": pairs,
            }
        )
    mismatched = [r["name"] for r in results if not r["line_count_matches"]]
    return {
        "ok": True,
        "command": "compare_render",
        "paper_mm": [paper_w, paper_h],
        "max_offset_mm": round(worst, 2),
        "line_count_mismatches": mismatched,
        "regions": results,
    }


def _lines_mm(image: Bitmap, background: Bitmap | None, box_mm: list[float], paper_w: float, paper_h: float,
              threshold: int, min_gap_mm: float) -> list[list[float]]:
    sx = image.width / paper_w
    sy = image.height / paper_h
    x, y, w, h = box_mm
    box_px = (round(x * sx), round(y * sy), round((x + w) * sx), round((y + h) * sy))
    lines = ink_lines(image, background, box_px, threshold=threshold, min_gap_px=max(1, round(min_gap_mm * sy)))
    return [[round(l / sx, 2), round(t / sy, 2), round((r + 1) / sx, 2), round((b + 1) / sy, 2)]
            for l, t, r, b in lines]


def _as_bitmap(value: str | PathLike[str] | Bitmap) -> Bitmap:
    return value if isinstance(value, Bitmap) else read_bitmap(value)


def _clip(box: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    return max(0, x0), max(0, y0), min(width, x1), min(height, y1)


def _corner_color(image: Bitmap, box: tuple[int, int, int, int]) -> tuple[int, int, int]:
    x0, y0, x1, y1 = box
    corners: Iterable[tuple[int, int]] = ((x0, y0), (x1 - 1, y0), (x0, y1 - 1), (x1 - 1, y1 - 1))
    samples = []
    for x, y in corners:
        i = (y * image.width + x) * 3
        samples.append(image.rgb[i : i + 3])
    return tuple(sum(s[k] for s in samples) // len(samples) for k in range(3))  # type: ignore[return-value]
