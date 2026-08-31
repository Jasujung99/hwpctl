"""색 이름·#RRGGBB → (r, g, b)."""

from __future__ import annotations

from hwpctl.errors import UsageError

NAMED = {
    "gray": (217, 217, 217),
    "grey": (217, 217, 217),
    "lightgray": (217, 217, 217),
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "yellow": (255, 255, 0),
    "blue": (189, 215, 238),
    "lightblue": (189, 215, 238),
    "green": (198, 224, 180),
    "red": (255, 199, 206),
    "orange": (252, 213, 180),
}


def parse_color(value: str) -> tuple[int, int, int]:
    raw = (value or "").strip()
    if not raw:
        raise UsageError("색 값이 비어 있습니다.")
    key = raw.lower().replace(" ", "").replace("_", "")
    if key in NAMED:
        return NAMED[key]
    if raw.startswith("#") and len(raw) == 7:
        try:
            r = int(raw[1:3], 16)
            g = int(raw[3:5], 16)
            b = int(raw[5:7], 16)
        except ValueError as exc:
            raise UsageError(f"색 코드를 해석할 수 없습니다: {value}") from exc
        return (r, g, b)
    raise UsageError(
        f"알 수 없는 색입니다: {value}. gray / #D9D9D9 형식을 쓰세요."
    )


def rgb_to_bgr_int(rgb: tuple[int, int, int]) -> int:
    r, g, b = rgb
    return r | (g << 8) | (b << 16)