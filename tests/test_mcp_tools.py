from __future__ import annotations

import anyio

from hwpctl.errors import UsageError
from hwpctl.mcp_server import _call, _call_hwpx, build_mcp
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
