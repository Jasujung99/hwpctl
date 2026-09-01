from __future__ import annotations

import threading

import anyio

from hwpctl.errors import UsageError
from hwpctl.mcp_server import _DispatchGate, _call, _call_hwpx, build_mcp
from hwpctl.tools import tool_names


def test_mcp_registers_engine_tools() -> None:
    mcp = build_mcp()
    tools = anyio.run(mcp.list_tools)  # 공개 API (#25)
    names = [t.name for t in tools]
    for name in tool_names():
        assert name in names
    assert "set_cell_margin" in names
    assert "insert_chart" in names
    assert "hwpx_status" in names
    assert "hwpx_inspect" in names
    assert "list_tools" in names


def test_call_wraps_unexpected_exception_in_korean() -> None:
    """(#14) com_error 등 예상 못한 예외도 스택 대신 한국어 한 줄로."""

    class Boom:
        def dispatch(self, name, **kwargs):
            raise ValueError("raw english com failure")

    async def go():
        return await _call(Boom(), "status")

    out = anyio.run(go)
    assert out["ok"] is False
    assert "오류" in out["error"]
    assert "Traceback" not in out["error"]


def test_call_passes_hwpctl_error_message() -> None:
    class Guard:
        def dispatch(self, name, **kwargs):
            raise UsageError("적용할 서식이 없습니다.")

    async def go():
        return await _call(Guard(), "set_format")

    out = anyio.run(go)
    assert out == {"ok": False, "command": "set_format", "error": "적용할 서식이 없습니다."}


def test_call_hwpx_passes_korean_error() -> None:
    async def go():
        return await _call_hwpx("hwpx_inspect", path="")

    out = anyio.run(go)
    assert out["ok"] is False
    assert out["command"] == "hwpx_inspect"
    assert "경로" in out["error"]


def test_call_hwpx_wraps_unexpected_exception(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("raw xml failure")

    monkeypatch.setattr("hwpctl.hwpx.commands.dispatch_hwpx", boom)

    async def go():
        return await _call_hwpx("hwpx_status")

    out = anyio.run(go)
    assert out["ok"] is False
    assert "오류" in out["error"]
    assert "Traceback" not in out["error"]


def test_read_timeout_keeps_gate_until_background_worker_finishes() -> None:
    release = threading.Event()
    started = threading.Event()
    finished = threading.Event()

    class SlowEngine:
        def __init__(self) -> None:
            self._mcp_dispatch_gate = _DispatchGate()
            self._mcp_read_timeout_sec = 0.1

        def dispatch(self, name, **kwargs):
            started.set()
            try:
                release.wait(1)
            finally:
                finished.set()
            return {"ok": True, "command": name}

    engine = SlowEngine()

    async def first_and_second():
        outcomes = {}

        async def first() -> None:
            outcomes["first"] = await _call(engine, "status")

        async with anyio.create_task_group() as group:
            group.start_soon(first)
            with anyio.fail_after(0.5):
                while not started.is_set():
                    await anyio.sleep(0.001)
            outcomes["second"] = await _call(engine, "snapshot")
        return outcomes["first"], outcomes["second"]

    first, second = anyio.run(first_and_second)
    assert first["ok"] is False
    assert "응답하지" in first["error"]
    assert second["ok"] is False
    assert "이전 한/글 명령" in second["error"]

    release.set()
    assert finished.wait(1)

    async def retry_after_release():
        outcome = {}
        for _ in range(20):
            outcome = await _call(engine, "status")
            if outcome["ok"]:
                return outcome
            await anyio.sleep(0.01)
        return outcome

    assert anyio.run(retry_after_release)["ok"] is True
