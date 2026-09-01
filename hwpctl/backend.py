"""한 개의 CLI 에 두 백엔드: ``hwpx``(기본, 한글 불필요) / ``hancom``(Windows COM).

``auto`` 는 Windows 가 아니면 ``hwpx`` 로 고른다. 한/글 COM 경로는
``hangul.py`` 를 그대로 두고, 이 모듈은 선택만 한다.
"""

from __future__ import annotations

import os
import sys
from typing import Literal

from hwpctl.errors import UsageError

BackendName = Literal["auto", "hwpx", "hancom"]
ResolvedBackend = Literal["hwpx", "hancom"]

BACKEND_CHOICES: tuple[str, ...] = ("auto", "hwpx", "hancom")
ENV_BACKEND = "HWPCTL_BACKEND"


def normalize_backend(value: str | None) -> BackendName:
    raw = (value if value is not None else os.environ.get(ENV_BACKEND) or "auto").strip().lower()
    if raw not in BACKEND_CHOICES:
        raise UsageError(
            f"알 수 없는 백엔드입니다: {value}. auto / hwpx / hancom 중 하나를 쓰세요."
        )
    return raw  # type: ignore[return-value]


def resolve_backend(value: str | None = None) -> ResolvedBackend:
    """``auto`` 를 실제 백엔드로 접는다. Linux·macOS·한/글 없음 → ``hwpx``."""

    requested = normalize_backend(value)
    if requested == "hwpx":
        return "hwpx"
    if requested == "hancom":
        return "hancom"
    if sys.platform != "win32":
        return "hwpx"
    return "hancom"


def backend_status(value: str | None = None) -> dict[str, str | bool]:
    requested = normalize_backend(value)
    resolved = resolve_backend(requested)
    return {
        "requested": requested,
        "resolved": resolved,
        "auto_is_hwpx": requested == "auto" and resolved == "hwpx",
        "hangul_required": resolved == "hancom",
        "platform": sys.platform,
    }
