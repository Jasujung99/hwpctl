from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from hwpctl.errors import LockBusyError
from hwpctl.lock import SingleWriterLock, WriterState, load_state, save_state


def test_lock_exclusive(tmp_path: Path) -> None:
    lock_path = tmp_path / "hwpctl.lock"
    first = SingleWriterLock(lock_path, timeout=0.2)
    second = SingleWriterLock(lock_path, timeout=0.2)
    first.acquire()
    try:
        with pytest.raises(LockBusyError) as exc:
            second.acquire()
        assert "쓰고 있습니다" in exc.value.message
    finally:
        first.release()


def test_lock_released_allows_next(tmp_path: Path) -> None:
    lock_path = tmp_path / "hwpctl.lock"
    a = SingleWriterLock(lock_path, timeout=1)
    b = SingleWriterLock(lock_path, timeout=1)
    a.acquire()
    a.release()
    b.acquire()
    b.release()


def test_lock_context_manager(tmp_path: Path) -> None:
    lock_path = tmp_path / "hwpctl.lock"
    with SingleWriterLock(lock_path, timeout=1):
        with pytest.raises(LockBusyError):
            SingleWriterLock(lock_path, timeout=0.1).acquire()


def test_lock_busy_message_is_korean(tmp_path: Path) -> None:
    lock_path = tmp_path / "hwpctl.lock"
    holder = SingleWriterLock(lock_path, timeout=1)
    holder.acquire()
    try:
        with pytest.raises(LockBusyError) as exc:
            SingleWriterLock(lock_path, timeout=0.05).acquire()
        msg = exc.value.message
        assert "클라이언트" in msg or "쓰고 있습니다" in msg
        assert "Traceback" not in msg
    finally:
        holder.release()


def test_lock_from_other_thread(tmp_path: Path) -> None:
    lock_path = tmp_path / "hwpctl.lock"
    ready = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with SingleWriterLock(lock_path, timeout=2):
            ready.set()
            release.wait(2)

    t = threading.Thread(target=hold)
    t.start()
    assert ready.wait(2)
    with pytest.raises(LockBusyError):
        SingleWriterLock(lock_path, timeout=0.15).acquire()
    release.set()
    t.join(2)


def test_state_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    state = WriterState(
        undo_stack=[2, 8],
        last_command="fill_cells",
        original_path="a.hwp",
        target_hwnd=70668,
    )
    save_state(state, path)
    loaded = load_state(path)
    assert loaded.undo_stack == [2, 8]
    assert loaded.last_command == "fill_cells"
    assert loaded.original_path == "a.hwp"
    assert loaded.target_hwnd == 70668


def test_state_without_target_hwnd_defaults_zero(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"undo_stack": [1], "last_command": "x"}', encoding="utf-8")
    assert load_state(path).target_hwnd == 0


def test_lock_waits_then_acquires(tmp_path: Path) -> None:
    lock_path = tmp_path / "hwpctl.lock"
    holder = SingleWriterLock(lock_path, timeout=2)
    holder.acquire()

    def unlock_soon() -> None:
        time.sleep(0.15)
        holder.release()

    threading.Thread(target=unlock_soon).start()
    waiter = SingleWriterLock(lock_path, timeout=2)
    waiter.acquire()
    waiter.release()