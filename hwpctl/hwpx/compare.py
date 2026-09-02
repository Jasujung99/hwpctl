"""결정적인 PPM(P6) 페이지 이미지 비교.

이 모듈은 PDF를 직접 해석하지 않는다. 한/글 또는 Poppler가 같은 해상도로
렌더한 ``pdftoppm`` PPM 결과를 받아, 외부 이미지 라이브러리 없이 쪽별 픽셀
차이를 계산한다. 원본·결과물을 같은 렌더러와 DPI로 만든 뒤 이 함수를 쓰는
것이 전제다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
import re
from typing import Any


_WHITESPACE = b" \t\r\n\v\f"
_DIGIT_PARTS = re.compile(r"(\d+)")


@dataclass(frozen=True)
class _PpmImage:
    """8-bit RGB로 정규화한 PPM 한 장."""

    path: Path
    width: int
    height: int
    rgb: bytes


def compare_page_images(
    reference: str | PathLike[str] | Sequence[str | PathLike[str]],
    candidate: str | PathLike[str] | Sequence[str | PathLike[str]],
    *,
    output_dir: str | PathLike[str] | None = None,
    emit_diff: bool = False,
    emit_overlay: bool = False,
) -> dict[str, Any]:
    """Render-first PPM(P6) 페이지 비교 결과를 돌려준다.

    ``reference``와 ``candidate``는 각각 한 PPM 파일, PPM 파일이 든 디렉터리,
    또는 페이지 순서를 명시한 경로 목록이다. 디렉터리의 ``.ppm`` 파일은
    자연 순서(예: ``page-2`` 앞에 ``page-10``)로 정렬한다.

    ``emit_diff``는 절대 RGB 차이를, ``emit_overlay``는 두 장의 50:50 합성을
    PPM으로 쓴다. 아티팩트를 요청하면 ``output_dir``가 필요하다. 크기가 다른
    쪽이나 한쪽에만 있는 쪽은 아티팩트를 만들지 않고 상태로만 보고한다.
    """

    if (emit_diff or emit_overlay) and output_dir is None:
        raise ValueError("차이 또는 오버레이 이미지를 만들려면 output_dir가 필요합니다.")

    reference_pages = _resolve_page_paths(reference, "원본")
    candidate_pages = _resolve_page_paths(candidate, "결과")
    artifact_dir = Path(output_dir) if output_dir is not None else None
    if artifact_dir is not None and (emit_diff or emit_overlay):
        artifact_dir.mkdir(parents=True, exist_ok=True)

    pages: list[dict[str, Any]] = []
    changed_pixels_total = 0
    comparable_pixels_total = 0
    absolute_error_total = 0
    max_delta = 0
    dimension_mismatch_pages: list[int] = []

    page_count = max(len(reference_pages), len(candidate_pages))
    for page_number in range(1, page_count + 1):
        reference_path = (
            reference_pages[page_number - 1]
            if page_number <= len(reference_pages)
            else None
        )
        candidate_path = (
            candidate_pages[page_number - 1]
            if page_number <= len(candidate_pages)
            else None
        )
        page_result: dict[str, Any] = {
            "page": page_number,
            "reference_path": str(reference_path) if reference_path is not None else None,
            "candidate_path": str(candidate_path) if candidate_path is not None else None,
            "reference_dimensions": None,
            "candidate_dimensions": None,
            "changed_pixels": None,
            "total_pixels": None,
            "mean_absolute_error": None,
            "max_delta": None,
            "diff_path": None,
            "overlay_path": None,
        }

        if reference_path is None:
            page_result["status"] = "missing_reference"
            pages.append(page_result)
            continue
        if candidate_path is None:
            page_result["status"] = "missing_candidate"
            pages.append(page_result)
            continue

        reference_image = _read_ppm(reference_path)
        candidate_image = _read_ppm(candidate_path)
        reference_dimensions = _dimensions(reference_image)
        candidate_dimensions = _dimensions(candidate_image)
        page_result["reference_dimensions"] = reference_dimensions
        page_result["candidate_dimensions"] = candidate_dimensions

        if reference_dimensions != candidate_dimensions:
            page_result["status"] = "dimension_mismatch"
            dimension_mismatch_pages.append(page_number)
            pages.append(page_result)
            continue

        metrics = _compare_rgb(reference_image.rgb, candidate_image.rgb)
        page_result.update(metrics)
        page_result["total_pixels"] = reference_image.width * reference_image.height
        page_result["status"] = "identical" if metrics["changed_pixels"] == 0 else "different"

        changed_pixels_total += metrics["changed_pixels"]
        comparable_pixels_total += page_result["total_pixels"]
        absolute_error_total += metrics["_absolute_error_total"]
        max_delta = max(max_delta, metrics["max_delta"])

        if artifact_dir is not None:
            artifact_base = f"page-{page_number:03d}"
            if emit_diff:
                diff_path = artifact_dir / f"{artifact_base}-diff.ppm"
                _write_ppm(diff_path, reference_image.width, reference_image.height, metrics["_diff_rgb"])
                page_result["diff_path"] = str(diff_path)
            if emit_overlay:
                overlay_path = artifact_dir / f"{artifact_base}-overlay.ppm"
                overlay = _overlay_rgb(reference_image.rgb, candidate_image.rgb)
                _write_ppm(overlay_path, reference_image.width, reference_image.height, overlay)
                page_result["overlay_path"] = str(overlay_path)

        page_result.pop("_absolute_error_total")
        page_result.pop("_diff_rgb")
        pages.append(page_result)

    page_count_match = len(reference_pages) == len(candidate_pages)
    dimensions_match = not dimension_mismatch_pages
    pixel_match = all(page["status"] == "identical" for page in pages)
    return {
        "ok": page_count_match and dimensions_match and pixel_match,
        "reference_page_count": len(reference_pages),
        "candidate_page_count": len(candidate_pages),
        "page_count_match": page_count_match,
        "dimensions_match": dimensions_match,
        "dimension_mismatch_pages": dimension_mismatch_pages,
        "comparable_page_count": sum(
            page["status"] in {"identical", "different"} for page in pages
        ),
        "changed_pixels": changed_pixels_total,
        "mean_absolute_error": (
            absolute_error_total / (comparable_pixels_total * 3)
            if comparable_pixels_total
            else None
        ),
        "max_delta": max_delta if comparable_pixels_total else None,
        "pages": pages,
    }


def _resolve_page_paths(
    source: str | PathLike[str] | Sequence[str | PathLike[str]],
    label: str,
) -> list[Path]:
    """한 파일·디렉터리·명시 목록을 비교할 PPM 페이지 목록으로 바꾼다."""

    if isinstance(source, (str, PathLike)):
        path = Path(source)
        if path.is_dir():
            pages = sorted(
                (
                    child
                    for child in path.iterdir()
                    if child.is_file() and child.suffix.casefold() == ".ppm"
                ),
                key=_page_sort_key,
            )
            if not pages:
                raise ValueError(f"{label} 페이지 디렉터리에 .ppm 파일이 없습니다: {path}")
            return pages
        if not path.is_file():
            raise FileNotFoundError(f"{label} 페이지 파일을 찾을 수 없습니다: {path}")
        return [path]

    if not isinstance(source, Sequence):
        raise TypeError(f"{label} 페이지는 경로 또는 경로 목록이어야 합니다.")

    pages = [Path(path) for path in source]
    if not pages:
        raise ValueError(f"{label} 페이지 목록이 비어 있습니다.")
    missing = next((path for path in pages if not path.is_file()), None)
    if missing is not None:
        raise FileNotFoundError(f"{label} 페이지 파일을 찾을 수 없습니다: {missing}")
    return pages


def _page_sort_key(path: Path) -> tuple[tuple[int, int | str], ...]:
    """``pdftoppm`` 출력에 맞춰 숫자 부분을 자연 순서로 정렬한다."""

    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in _DIGIT_PARTS.split(path.name)
    )


def _read_ppm(path: Path) -> _PpmImage:
    """P6 PPM을 읽어 최대값에 무관하게 8-bit RGB로 정규화한다."""

    data = path.read_bytes()
    cursor = 0
    magic, cursor = _read_ppm_token(data, cursor, path)
    if magic != b"P6":
        raise ValueError(f"P6 PPM 파일이 아닙니다: {path}")

    width_token, cursor = _read_ppm_token(data, cursor, path)
    height_token, cursor = _read_ppm_token(data, cursor, path)
    max_value_token, cursor = _read_ppm_token(data, cursor, path)
    try:
        width = int(width_token)
        height = int(height_token)
        max_value = int(max_value_token)
    except ValueError as exc:
        raise ValueError(f"PPM 헤더 숫자를 읽을 수 없습니다: {path}") from exc
    if width <= 0 or height <= 0 or not 1 <= max_value <= 65535:
        raise ValueError(f"PPM 크기 또는 최대값이 올바르지 않습니다: {path}")
    if cursor >= len(data) or data[cursor] not in _WHITESPACE:
        raise ValueError(f"PPM 헤더와 픽셀 데이터 사이의 공백이 없습니다: {path}")
    cursor += 2 if data[cursor : cursor + 2] == b"\r\n" else 1

    sample_bytes = 1 if max_value < 256 else 2
    sample_count = width * height * 3
    expected_size = sample_count * sample_bytes
    raster = data[cursor:]
    if len(raster) != expected_size:
        raise ValueError(
            f"PPM 픽셀 데이터 길이가 맞지 않습니다: {path} "
            f"(기대 {expected_size}바이트, 실제 {len(raster)}바이트)"
        )

    if max_value == 255:
        rgb = raster
    elif sample_bytes == 1:
        if any(value > max_value for value in raster):
            raise ValueError(f"PPM 픽셀 값이 최대값을 넘습니다: {path}")
        rgb = bytes((value * 255 + max_value // 2) // max_value for value in raster)
    else:
        normalized = bytearray(sample_count)
        for index in range(sample_count):
            raw_value = (raster[index * 2] << 8) | raster[index * 2 + 1]
            if raw_value > max_value:
                raise ValueError(f"PPM 픽셀 값이 최대값을 넘습니다: {path}")
            normalized[index] = (raw_value * 255 + max_value // 2) // max_value
        rgb = bytes(normalized)
    return _PpmImage(path=path, width=width, height=height, rgb=rgb)


def _read_ppm_token(data: bytes, cursor: int, path: Path) -> tuple[bytes, int]:
    """공백·주석을 건너뛰고 PPM 헤더 토큰 하나를 읽는다."""

    cursor = _skip_ppm_header_space(data, cursor)
    start = cursor
    while cursor < len(data) and data[cursor] not in _WHITESPACE:
        cursor += 1
    if start == cursor:
        raise ValueError(f"PPM 헤더가 불완전합니다: {path}")
    return data[start:cursor], cursor


def _skip_ppm_header_space(data: bytes, cursor: int) -> int:
    while cursor < len(data):
        while cursor < len(data) and data[cursor] in _WHITESPACE:
            cursor += 1
        if cursor < len(data) and data[cursor] == ord("#"):
            newline = data.find(b"\n", cursor)
            cursor = len(data) if newline == -1 else newline + 1
            continue
        break
    return cursor


def _dimensions(image: _PpmImage) -> dict[str, int]:
    return {"width": image.width, "height": image.height}


def _compare_rgb(reference: bytes, candidate: bytes) -> dict[str, Any]:
    changed_pixels = 0
    absolute_error_total = 0
    max_delta = 0
    diff = bytearray(len(reference))
    for index in range(0, len(reference), 3):
        red_delta = abs(reference[index] - candidate[index])
        green_delta = abs(reference[index + 1] - candidate[index + 1])
        blue_delta = abs(reference[index + 2] - candidate[index + 2])
        diff[index] = red_delta
        diff[index + 1] = green_delta
        diff[index + 2] = blue_delta
        pixel_error = red_delta + green_delta + blue_delta
        if pixel_error:
            changed_pixels += 1
        absolute_error_total += pixel_error
        max_delta = max(max_delta, red_delta, green_delta, blue_delta)
    return {
        "changed_pixels": changed_pixels,
        "mean_absolute_error": absolute_error_total / len(reference),
        "max_delta": max_delta,
        "_absolute_error_total": absolute_error_total,
        "_diff_rgb": bytes(diff),
    }


def _overlay_rgb(reference: bytes, candidate: bytes) -> bytes:
    return bytes((left + right) // 2 for left, right in zip(reference, candidate))


def _write_ppm(path: Path, width: int, height: int, rgb: bytes) -> None:
    path.write_bytes(f"P6\n{width} {height}\n255\n".encode("ascii") + rgb)
