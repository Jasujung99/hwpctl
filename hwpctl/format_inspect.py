"""한/글 없이 테스트 가능한 서식 검사·쪽 이미지 경로 헬퍼.

AlignType 숫자는 한글 2022 ParaShape 열거값을 그대로 쓴다.
InitScan/GetText 경로는 쓰지 않는다 (라이브에서 가짜 기본 서식을 돌려준다).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from hwpctl.errors import HangulCommandError
from hwpctl.lock import default_runtime_dir

# ParaShape AlignType (한글 2022 / HAlign)
ALIGN_TYPE_MAP: dict[int, str] = {
    0: "justify",
    1: "left",
    2: "right",
    3: "center",
    4: "distribute",
}

_ALIGN_NAME_ALIASES: dict[str, str] = {
    "justify": "justify",
    "left": "left",
    "right": "right",
    "center": "center",
    "distribute": "distribute",
    "distributespace": "distribute",
    "distribute_space": "distribute",
}

CONVERT_EXTS = frozenset({".png", ".jpg", ".jpeg"})
SNIPPET_LEN = 80


def map_align_type(value: Any) -> str:
    """AlignType 0=justify 1=left 2=right 3=center 4=distribute."""
    if value is None:
        return "left"
    if isinstance(value, str):
        raw = value.strip()
        alias = _ALIGN_NAME_ALIASES.get(raw.lower().replace(" ", ""))
        if alias:
            return alias
        if raw.lstrip("-").isdigit():
            return map_align_type(int(raw))
        return raw.lower() or "left"
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    return ALIGN_TYPE_MAP.get(number, f"unknown:{number}")


def normalize_size_pt(value: Any) -> float | int:
    try:
        size = round(float(value), 2)
    except (TypeError, ValueError):
        return value
    if size.is_integer():
        return int(size)
    return size


def format_group_key(row: Mapping[str, Any]) -> dict[str, Any]:
    color = row.get("color", 0)
    try:
        color = int(color)
    except (TypeError, ValueError):
        pass
    return {
        "align": row.get("align"),
        "font": row.get("font"),
        "size_pt": normalize_size_pt(row.get("size_pt")),
        "bold": bool(row.get("bold")),
        "color": color,
    }


def group_format_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """같은 (align, font, size_pt, bold, color) 가 이어지면 한 그룹으로 묶는다."""
    groups: list[dict[str, Any]] = []
    for row in rows:
        key = format_group_key(row)
        snippet = str(row.get("snippet") or "")
        in_table = bool(row.get("in_table"))
        if groups and groups[-1]["key"] == key:
            groups[-1]["count"] += 1
            if snippet:
                groups[-1]["samples"].append(snippet)
            if in_table:
                groups[-1]["in_table"] = True
            continue
        groups.append(
            {
                "key": key,
                "count": 1,
                "samples": [snippet] if snippet else [],
                "in_table": in_table,
            }
        )
    return groups


def resolve_page_image_path(out: str, page_1: int) -> Path:
    if out and str(out).strip():
        return Path(out).expanduser()
    return default_runtime_dir() / f"page-{page_1}.bmp"


def page_image_write_plan(dest: Path) -> tuple[Path, Path | None]:
    """CreatePageImage 는 항상 bmp. png/jpg 는 그 다음 Pillow 변환.

    Returns:
        (bmp_path, convert_dest_or_None)
    """
    dest = dest.expanduser()
    suffix = dest.suffix.lower()
    if suffix in CONVERT_EXTS:
        return dest.with_suffix(".bmp"), dest
    if suffix == "":
        dest = dest.with_suffix(".bmp")
    return dest, None


def convert_bmp_with_pillow(bmp_path: Path, dest: Path) -> None:
    """pyhwpx.create_page_image 과 같이 bmp 를 연 뒤 dest 확장자로 저장한다."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise HangulCommandError(
            "PNG/JPG로 바꾸려면 Pillow가 필요합니다. "
            'pip install "hwpctl[windows]" 또는 pip install pillow 후 다시 시도하세요.'
        ) from exc
    try:
        with Image.open(bmp_path) as img:
            img.save(dest)
    except Exception as exc:
        raise HangulCommandError(f"쪽 이미지를 변환하지 못했습니다: {exc}") from exc
    try:
        if dest.resolve() != bmp_path.resolve():
            bmp_path.unlink(missing_ok=True)
    except OSError:
        pass
