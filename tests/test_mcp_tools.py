from __future__ import annotations

import threading

import anyio

from hwpctl.errors import UsageError
from hwpctl.mcp_server import READ_COMMANDS, _DispatchGate, _call, _call_hwpx, build_mcp
from hwpctl.tools import tool_names


def test_mcp_registers_engine_tools() -> None:
    mcp = build_mcp()
    tools = anyio.run(mcp.list_tools)  # 공개 API (#25)
    names = [t.name for t in tools]
    for name in tool_names():
        assert name in names
    assert "set_cell_margin" in names
    assert "insert_chart" in names
    assert "exit_table" in names
    assert "set_table_properties" in names
    assert "set_table_position" in names
    assert "recreate_inline_table_before_paragraph" in names
    assert "trim_blank_paragraphs_before_body" in names
    assert "close_all" in names
    assert "insert_text_box" in names
    assert "set_cell_fill" in names
    assert "write_cell" in names
    assert "set_page_number" in names
    assert "set_page_visibility" in names
    assert "restart_page_number" in names
    assert "hwpx_status" in names
    assert "hwpx_inspect" in names
    assert "list_documents" in names
    assert "list_tools" in names


def test_visual_format_tools_match_catalog_and_publish_full_mcp_schema() -> None:
    """CLI/MCP에 새 이름만 추가하고 실제 인자를 빼먹는 회귀를 막는다."""
    mcp = build_mcp()
    tools = {tool.name: tool for tool in anyio.run(mcp.list_tools)}
    catalog = {name for name in tool_names()}
    assert {
        "insert_text_box",
        "set_cell_fill",
        "list_documents",
        "exit_table",
        "write_cell",
        "set_page_number",
        "set_table_properties",
        "set_table_position",
        "recreate_inline_table_before_paragraph",
        "trim_blank_paragraphs_before_body",
        "close_all",
        "set_page_visibility",
        "restart_page_number",
    } <= catalog <= set(tools)

    structured_paragraph = tools["insert_paragraph"].inputSchema
    assert {"text", "runs", "paragraph", "page_break_before"} == set(
        structured_paragraph["properties"]
    )
    assert structured_paragraph["properties"]["text"]["default"] == ""

    write_cell = tools["write_cell"].inputSchema
    assert set(write_cell["required"]) == {"table", "cell", "paragraphs"}
    assert set(write_cell["properties"]) == {"table", "cell", "paragraphs"}

    assert tools["exit_table"].inputSchema["properties"] == {}
    assert tools["list_documents"].inputSchema["properties"] == {}

    text_box = tools["insert_text_box"].inputSchema
    assert set(text_box["required"]) == {"text", "width_mm", "height_mm"}
    assert {
        "fill",
        "line",
        "shadow",
        "text_shadow",
        "margin",
        "align",
        "position",
        "bold",
        "italic",
        "font",
        "size",
        "color",
    } <= set(text_box["properties"])
    assert text_box["properties"]["margin"]["default"] is None

    cell_fill = tools["set_cell_fill"].inputSchema
    assert cell_fill["required"] == ["fill"]
    assert {"fill", "table", "cell_range"} == set(cell_fill["properties"])

    text_format = tools["set_format"].inputSchema
    assert "text_shadow" in text_format["properties"]

    page_number = tools["set_page_number"].inputSchema
    assert page_number["properties"]["position"]["default"] == "bottom_center"
    assert page_number["properties"]["separator"]["default"] == "-"

    table_properties = tools["set_table_properties"].inputSchema
    assert table_properties["required"] == ["table"]
    assert set(table_properties["properties"]) == {
        "table",
        "page_break",
        "repeat_header",
        "cell_spacing_mm",
    }
    assert table_properties["properties"]["page_break"]["default"] == "cell"
    assert table_properties["properties"]["repeat_header"]["default"] is True
    assert table_properties["properties"]["cell_spacing_mm"]["default"] == 0.0

    table_position = tools["set_table_position"].inputSchema
    assert set(table_position["required"]) == {"table", "position"}
    assert set(table_position["properties"]) == {"table", "position"}
    assert table_position["properties"]["position"]["type"] == "object"

    recreate = tools["recreate_inline_table_before_paragraph"].inputSchema
    assert set(recreate["required"]) == {
        "old_table",
        "expected_table_text",
        "before_text",
        "table_spec",
        "blank_paragraph",
    }
    assert set(recreate["properties"]) == {
        "old_table",
        "expected_table_text",
        "before_text",
        "table_spec",
        "blank_paragraph",
        "dry_run",
    }
    assert recreate["properties"]["dry_run"]["default"] is False

    trim_blank = tools["trim_blank_paragraphs_before_body"].inputSchema
    assert trim_blank["required"] == ["text"]
    assert set(trim_blank["properties"]) == {"text", "keep", "dry_run"}
    assert trim_blank["properties"]["keep"]["default"] == 1
    assert trim_blank["properties"]["dry_run"]["default"] is False

    close_all = tools["close_all"].inputSchema
    assert close_all.get("required", []) == []
    assert set(close_all["properties"]) == {"force"}
    assert close_all["properties"]["force"]["default"] is False

    page_visibility = tools["set_page_visibility"].inputSchema
    assert set(page_visibility["properties"]) == {
        "hide_header",
        "hide_footer",
        "hide_master_page",
        "hide_border",
        "hide_fill",
        "hide_page_num",
    }
    assert all(
        page_visibility["properties"][name]["default"] is False
        for name in page_visibility["properties"]
    )

    restart = tools["restart_page_number"].inputSchema
    assert restart.get("required", []) == []
    assert restart["properties"]["number"]["default"] == 1


def test_list_documents_is_treated_as_bounded_read() -> None:
    assert "list_documents" in READ_COMMANDS


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
