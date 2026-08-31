from __future__ import annotations

from hwpctl.mcp_server import build_mcp
from hwpctl.tools import tool_names


def test_mcp_registers_engine_tools() -> None:
    mcp = build_mcp()
    registered = [t.name for t in mcp._tool_manager.list_tools()]
    for name in tool_names():
        assert name in registered
    assert "list_tools" in registered