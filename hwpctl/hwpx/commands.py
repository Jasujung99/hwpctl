"""한글·COM·작성 잠금 없이 동작하는 HWPX 읽기 명령."""

from __future__ import annotations

from typing import Any

from hwpctl.errors import UsageError
from hwpctl.hwpx.document import hwpx_available, hwpx_version
from hwpctl.hwpx.inspect import inspect_hwpx


def hwpx_status(path: str | None = None) -> dict[str, Any]:
    """라이브러리 설치 여부와 선택적 파일 요약."""

    payload: dict[str, Any] = {
        "ok": True,
        "command": "hwpx_status",
        "backend": "python-hwpx",
        "hangul_required": False,
        "lock_required": False,
        "autosave": False,
        "python_hwpx": {
            "available": hwpx_available(),
            "version": hwpx_version(),
            "extra": "hwpx",
            "install": 'pip install -e ".[hwpx]"',
        },
        "inspect": "owpml-xml",
    }
    if path:
        inspected = inspect_hwpx(path)
        payload["path"] = inspected["path"]
        payload["paragraph_count"] = inspected["paragraph_count"]
        payload["table_count"] = inspected["table_count"]
        payload["paragraph_groups"] = len(inspected["paragraph_groups"])
        payload["run_groups"] = len(inspected["run_groups"])
        payload["cell_fill_groups"] = len(inspected["cell_fill_groups"])
    return payload


def dispatch_hwpx(command: str, *, path: str | None = None) -> dict[str, Any]:
    if command == "hwpx_status":
        return hwpx_status(path)
    if command == "hwpx_inspect":
        if not path:
            raise UsageError("hwpx_inspect 에는 .hwpx 경로가 필요합니다.")
        return inspect_hwpx(path)
    raise UsageError(f"알 수 없는 HWPX 명령입니다: {command}")
