"""``.hwpx`` 열기·저장. ``python-hwpx`` 6.x 얇은 래퍼.

저장은 라이브러리 Safe Write Contract 를 그대로 넘긴다.
``mode="patch"`` 이면 손대지 않은 파트 바이트 보존을 요구한다.
한/글 COM 과 작성 잠금은 쓰지 않는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hwpctl.errors import HwpxError, HwpxMissingError, UsageError

MISSING_KO = (
    "python-hwpx가 설치되어 있지 않습니다. "
    "한/글은 필요 없습니다. "
    'Linux·macOS·Windows에서 pip install -e ".[hwpx]" 로 설치하세요.'
)


def hwpx_available() -> bool:
    try:
        import hwpx  # noqa: F401
    except ImportError:
        return False
    return True


def hwpx_version() -> str | None:
    try:
        import hwpx
    except ImportError:
        return None
    return str(getattr(hwpx, "__version__", "unknown"))


def require_hwpx() -> None:
    if not hwpx_available():
        raise HwpxMissingError(MISSING_KO)


def _resolve_hwpx_path(path: str | Path, *, must_exist: bool) -> Path:
    raw = str(path or "").strip()
    if not raw:
        raise UsageError("HWPX 파일 경로가 비어 있습니다.")
    target = Path(raw).expanduser()
    suffix = target.suffix.lower()
    if suffix == ".hwp":
        raise HwpxError(
            "바이너리 .hwp 는 이 경로에서 열 수 없습니다. "
            "한글에서 .hwpx 로 저장한 뒤 다시 시도하세요."
        )
    if suffix and suffix != ".hwpx":
        raise HwpxError(
            f"HWPX(.hwpx) 파일이 아닙니다: {target.name}. "
            "확장자를 확인하세요."
        )
    if must_exist and not target.is_file():
        raise HwpxError(f"HWPX 파일을 찾을 수 없습니다: {target}")
    return target


def open_document(path: str | Path) -> Any:
    """``HwpxDocument.open``. 호출자가 ``close()`` 해야 한다."""

    require_hwpx()
    from hwpx import HwpxDocument

    target = _resolve_hwpx_path(path, must_exist=True)
    try:
        return HwpxDocument.open(str(target))
    except HwpxError:
        raise
    except Exception as exc:
        raise HwpxError(
            f"HWPX 파일을 열 수 없습니다 ({target.name}): {exc}"
        ) from exc


def new_document() -> Any:
    """빈 ``HwpxDocument`` (라이브러리 기본 스켈레톤)."""

    require_hwpx()
    from hwpx import HwpxDocument

    try:
        return HwpxDocument.new()
    except Exception as exc:
        raise HwpxError(f"빈 HWPX 문서를 만들 수 없습니다: {exc}") from exc


def save_document(
    document: Any,
    path: str | Path,
    *,
    mode: str = "auto",
    fallback: str = "error",
    return_report: bool = False,
) -> Any:
    """``save_to_path``. 기본은 라이브러리 ``auto`` 모드.

    기존 문서를 고칠 때는 ``mode="patch"`` 로 바이트 보존을 요구한다.
    보존 등급을 지키지 못하면 라이브러리가 파일을 쓰지 않고 실패한다.
    """

    require_hwpx()
    target = _resolve_hwpx_path(path, must_exist=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        return document.save_to_path(
            str(target),
            mode=mode,
            fallback=fallback,
            return_report=return_report,
        )
    except Exception as exc:
        raise HwpxError(f"HWPX 파일을 저장할 수 없습니다 ({target.name}): {exc}") from exc


def close_document(document: Any) -> None:
    closer = getattr(document, "close", None)
    if callable(closer):
        closer()
