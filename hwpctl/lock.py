"""프로세스 간 단일 작성기 잠금.

한/글 COM 은 STA 이고, 두 클라이언트가 동시에 쓰면 문서가 깨진다.
잠금은 명령 단위로 잡았다 풀며, MCP 서버가 켜져 있어도 CLI 를 막지 않는다.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from hwpctl.errors import LockBusyError

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


LOCK_FILENAME = "hwpctl.lock"
STATE_FILENAME = "state.json"


def default_runtime_dir() -> Path:
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or "."
        return Path(root) / "hwpctl"
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg) / "hwpctl"
    return Path("/tmp") / "hwpctl"


def default_lock_path() -> Path:
    override = os.environ.get("HWPCTL_LOCK")
    if override:
        return Path(override)
    return default_runtime_dir() / LOCK_FILENAME


def default_state_path() -> Path:
    override = os.environ.get("HWPCTL_STATE")
    if override:
        return Path(override)
    return default_runtime_dir() / STATE_FILENAME


def client_name() -> str:
    return os.environ.get("HWPCTL_CLIENT") or f"pid:{os.getpid()}"


@dataclass
class LockInfo:
    pid: int
    client: str
    acquired_at: float


@dataclass
class WriterState:
    """명령이 만든 한/글 Undo 횟수 스택 + 고정된 대상 창 핸들.

    ``hwpctl undo`` 가 스택 항목 하나를 한 덩어리로 되돌리고,
    ``target_hwnd`` 로 명령이 항상 같은 한/글 창을 향하는지 검증한다.
    """

    undo_stack: list[int] = field(default_factory=list)
    last_command: str = ""
    original_path: str = ""
    target_hwnd: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "undo_stack": list(self.undo_stack),
            "last_command": self.last_command,
            "original_path": self.original_path,
            "target_hwnd": int(self.target_hwnd),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WriterState:
        stack = data.get("undo_stack") or []
        try:
            hwnd = int(data.get("target_hwnd") or 0)
        except (TypeError, ValueError):
            hwnd = 0
        return cls(
            undo_stack=[int(x) for x in stack],
            last_command=str(data.get("last_command") or ""),
            original_path=str(data.get("original_path") or ""),
            target_hwnd=hwnd,
        )


def load_state(path: Path | None = None) -> WriterState:
    path = path or default_state_path()
    if not path.is_file():
        return WriterState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return WriterState()
    if not isinstance(data, dict):
        return WriterState()
    return WriterState.from_dict(data)


def save_state(state: WriterState, path: Path | None = None) -> None:
    path = path or default_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


class SingleWriterLock:
    """교차 플랫폼 배타 파일 잠금.

    Unix 는 ``fcntl.flock``, Windows 는 ``msvcrt.locking``.
    잠금 파일에 pid/클라이언트를 적어 오류 메시지에 쓴다.
    """

    def __init__(self, path: Path | None = None, timeout: float = 8.0) -> None:
        self.path = path or default_lock_path()
        self.timeout = timeout
        self._fh: TextIO | None = None

    def __enter__(self) -> SingleWriterLock:
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.release()

    def acquire(self, timeout: float | None = None) -> None:
        if self._fh is not None:
            return
        wait = self.timeout if timeout is None else timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + max(0.0, wait)
        holder: LockInfo | None = None
        while True:
            try:
                fh = open(self.path, "a+", encoding="utf-8")
                self._lock_fd(fh, blocking=False)
                fh.seek(0)
                fh.truncate()
                payload = {
                    "pid": os.getpid(),
                    "client": client_name(),
                    "acquired_at": time.time(),
                }
                fh.write(json.dumps(payload, ensure_ascii=False))
                fh.flush()
                self._fh = fh
                return
            except (BlockingIOError, OSError, PermissionError):
                if "fh" in locals() and fh is not None:
                    holder = _read_holder(fh)
                    try:
                        fh.close()
                    except OSError:
                        pass
                if time.monotonic() >= deadline:
                    raise LockBusyError(_busy_message(holder)) from None
                time.sleep(0.05)

    def release(self) -> None:
        fh = self._fh
        self._fh = None
        if fh is None:
            return
        try:
            self._unlock_fd(fh)
        finally:
            try:
                fh.close()
            except OSError:
                pass

    @staticmethod
    def _lock_fd(fh: TextIO, blocking: bool) -> None:
        if sys.platform == "win32":
            fh.seek(0)
            if fh.read(1) == "":
                fh.write(" ")
                fh.flush()
            fh.seek(0)
            mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
            try:
                msvcrt.locking(fh.fileno(), mode, 1)
            except OSError as exc:
                raise BlockingIOError from exc
            return
        flags = fcntl.LOCK_EX
        if not blocking:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.flock(fh.fileno(), flags)
        except BlockingIOError:
            raise
        except OSError as exc:
            raise BlockingIOError from exc

    @staticmethod
    def _unlock_fd(fh: TextIO) -> None:
        try:
            if sys.platform == "win32":
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


def _read_holder(fh: TextIO) -> LockInfo | None:
    try:
        fh.seek(0)
        raw = fh.read()
        data = json.loads(raw)
        return LockInfo(
            pid=int(data.get("pid") or 0),
            client=str(data.get("client") or "unknown"),
            acquired_at=float(data.get("acquired_at") or 0.0),
        )
    except Exception:
        return None


def _busy_message(holder: LockInfo | None) -> str:
    if holder is None:
        return (
            "다른 클라이언트가 한/글 문서를 쓰고 있습니다. "
            "잠시 후 다시 시도하세요. 한 번에 하나의 작성기만 허용됩니다."
        )
    return (
        f"다른 클라이언트가 한/글 문서를 쓰고 있습니다 "
        f"(클라이언트={holder.client}, pid={holder.pid}). "
        "잠시 후 다시 시도하세요. 한 번에 하나의 작성기만 허용됩니다."
    )