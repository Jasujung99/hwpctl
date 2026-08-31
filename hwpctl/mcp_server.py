"""동일 엔진을 MCP 로 노출. stdio 또는 localhost streamable HTTP + 토큰."""

from __future__ import annotations

import os
import sys
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from hwpctl.errors import HwpctlError
from hwpctl.tools import tool_catalog

INSTRUCTIONS = (
    "한/글 2022 창을 직접 고친다. 키 입력은 쓰지 말고 이 도구만 호출하라. "
    "원본 파일은 덮어쓰지 말고 save_as 로 새 경로에 저장하라. "
    "자동저장은 없다. save/close 는 각각 overwrite/force 가 필요하다. "
    "예: 사업계획서 제목 + 4열 8행 표 + 첫 행 회색 → "
    "insert_title, create_table(rows=8, cols=4, header_fill=gray)."
)


def _engine(lock_timeout: float):
    from hwpctl.engine import Engine

    return Engine(lock_timeout=lock_timeout)


def _call(engine, name: str, **kwargs: Any) -> dict[str, Any]:
    try:
        return engine.dispatch(name, **kwargs)
    except HwpctlError as exc:
        return {"ok": False, "command": name, "error": exc.message}


def build_mcp(lock_timeout: float = 8.0):
    from mcp.server.fastmcp import FastMCP

    engine = _engine(lock_timeout)
    mcp = FastMCP("hwpctl", instructions=INSTRUCTIONS)

    @mcp.tool()
    def status() -> dict[str, Any]:
        """열린 한/글 창의 경로, 수정 여부, 쪽, 버전."""
        return _call(engine, "status")

    @mcp.tool()
    def open(path: str = "", new: bool = False, discard: bool = False) -> dict[str, Any]:
        """새 문서 또는 경로로 연다. 수정본이 있으면 discard=true 필요."""
        return _call(engine, "open", path=path or None, new=new, discard=discard)

    @mcp.tool()
    def snapshot() -> dict[str, Any]:
        """제목, 본문, 표, 선택 영역을 읽는다."""
        return _call(engine, "snapshot")

    @mcp.tool()
    def insert_title(text: str, size: float = 20.0) -> dict[str, Any]:
        """제목 문단을 가운데·굵게·큰 글씨로 삽입한다. Undo 한 단위."""
        return _call(engine, "insert_title", text=text, size=size)

    @mcp.tool()
    def insert_paragraph(text: str) -> dict[str, Any]:
        """본문 문단을 삽입한다. Undo 한 단위."""
        return _call(engine, "insert_paragraph", text=text)

    @mcp.tool()
    def create_table(
        rows: int,
        cols: int,
        header_fill: str = "",
        header: bool = True,
    ) -> dict[str, Any]:
        """표를 만든다. header_fill 예: gray. Undo 한 단위."""
        return _call(engine, "create_table", rows=rows, cols=cols, header_fill=header_fill, header=header)

    @mcp.tool()
    def fill_cells(
        table: int = 0,
        cells: Any = None,
        assignments: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """표 셀을 채운다. cells 는 2차원 배열 또는 {\"A1\":\"값\"}."""
        return _call(engine, "fill_cells", table=table, cells=cells, assignments=assignments)

    @mcp.tool()
    def set_format(
        bold: bool | None = None,
        italic: bool | None = None,
        font: str = "",
        size: float | None = None,
        align: str = "",
        color: str = "",
        fill: str = "",
        table: int | None = None,
        row: int | None = None,
        cell_range: str = "",
    ) -> dict[str, Any]:
        """선택·문단·행 서식. fill 은 셀 배경."""
        return _call(
            engine,
            "set_format",
            bold=bold,
            italic=italic,
            font=font,
            size=size,
            align=align,
            color=color,
            fill=fill,
            table=table,
            row=row,
            cell_range=cell_range,
        )

    @mcp.tool()
    def replace_selection(text: str) -> dict[str, Any]:
        """선택 영역을 텍스트로 교체한다."""
        return _call(engine, "replace_selection", text=text)

    @mcp.tool()
    def undo() -> dict[str, Any]:
        """직전 명령을 한/글 Undo 한 덩어리로 되돌린다."""
        return _call(engine, "undo")

    @mcp.tool()
    def page(goto: int | None = None) -> dict[str, Any]:
        """현재 쪽을 읽거나 goto(1부터)로 이동한다."""
        return _call(engine, "page", goto=goto)

    @mcp.tool()
    def save_as(path: str, format: str = "") -> dict[str, Any]:
        """새 경로로 저장한다. 원본은 덮어쓰지 않는다. 자동저장 없음."""
        return _call(engine, "save_as", path=path, format=format)

    @mcp.tool()
    def save(overwrite: bool = False) -> dict[str, Any]:
        """원본 경로에 저장. overwrite=true 필수."""
        return _call(engine, "save", overwrite=overwrite)

    @mcp.tool()
    def close(force: bool = False) -> dict[str, Any]:
        """문서를 닫는다. force=true 필수."""
        return _call(engine, "close", force=force)

    @mcp.tool()
    def list_tools() -> dict[str, Any]:
        """이 서버가 제공하는 고수준 도구 목록."""
        return {"ok": True, "tools": tool_catalog()}

    return mcp


class TokenAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str) -> None:
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in {"/health", "/"}:
            return await call_next(request)
        provided = _extract_token(request)
        if provided != self.token:
            return JSONResponse(
                {"ok": False, "error": "토큰이 없거나 올바르지 않습니다."},
                status_code=401,
            )
        return await call_next(request)


def _extract_token(request: Request) -> str:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.headers.get("x-hwpctl-token") or "").strip()


def run_mcp(
    *,
    http: bool,
    host: str,
    port: int,
    token: str,
    lock_timeout: float,
) -> None:
    mcp = build_mcp(lock_timeout=lock_timeout)
    if not http:
        mcp.run(transport="stdio")
        return

    secret = token or os.environ.get("HWPCTL_TOKEN") or ""
    if not secret:
        print(
            "HTTP 모드에는 --token 또는 환경 변수 HWPCTL_TOKEN 이 필요합니다.",
            file=sys.stderr,
        )
        raise SystemExit(5)
    if host not in {"127.0.0.1", "localhost", "::1"}:
        print(
            "보안상 HTTP 는 localhost 에만 바인드하세요. "
            "원격(Grok Bot)은 사용자가 터널로 노출해야 합니다.",
            file=sys.stderr,
        )
        raise SystemExit(5)

    import uvicorn
    from starlette.responses import JSONResponse as StarletteJSON
    from starlette.routing import Route

    app = mcp.streamable_http_app()

    async def health(_request: Request) -> StarletteJSON:
        return StarletteJSON({"ok": True, "service": "hwpctl", "transport": "streamable-http"})

    app.router.routes.insert(0, Route("/health", health))
    app.router.routes.insert(0, Route("/", health))
    app.add_middleware(TokenAuthMiddleware, token=secret)

    print(
        f"hwpctl MCP HTTP  http://{host}:{port}/mcp  (토큰 필요, localhost 전용)",
        file=sys.stderr,
    )
    uvicorn.run(app, host=host, port=port, log_level="info")