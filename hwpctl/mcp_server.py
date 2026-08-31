"""동일 엔진을 MCP 로 노출. stdio 또는 localhost streamable HTTP + 토큰.

도구는 async 로 선언하고 실제 한/글 호출은 anyio 워커 스레드에서 실행한다.
동기 함수로 두면 FastMCP(mcp 1.x)가 이벤트 루프 스레드에서 직접 호출해
COM 작업 + 잠금 대기(최대 lock_timeout) 동안 서버 전체가 멈추기 때문이다.
Windows COM(STA)은 스레드마다 CoInitialize 가 필요하며, 캔버스 객체는
한 호출(=한 스레드) 안에서 생성·사용·폐기되므로 아파트 규칙을 깨지 않는다.
"""

from __future__ import annotations

import functools
import hmac
import os
import sys
from typing import Any

import anyio
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from hwpctl.errors import HwpctlError
from hwpctl.tools import tool_catalog

INSTRUCTIONS = (
    "한/글 2022 창을 직접 고친다. 키 입력은 쓰지 말고 이 도구만 호출하라. "
    "원본 파일은 덮어쓰지 말고 save_as 로 새 경로에 저장하라. "
    "자동저장은 없다. save/close 는 각각 overwrite/force 가 필요하다. "
    "새 표에는 기본 칸 안여백(좌우 3.5mm, 상하 2.0mm)이 적용된다. "
    "create_table/fill_cells 등으로 표를 편집한 뒤에는 항상 별도 layout_review를 호출한다. "
    "차트는 insert_chart 로 한/글 네이티브 차트를 넣는다 (그림 아님). "
    "예: 사업계획서 제목 + 4열 8행 표 + 첫 행 회색 → "
    "insert_title, create_table(rows=8, cols=4, header_fill=gray)."
)


def _engine(lock_timeout: float):
    from hwpctl.engine import Engine

    return Engine(lock_timeout=lock_timeout)


def _dispatch_in_thread(engine: Any, name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """워커 스레드 본체. Windows 에서는 스레드별 COM 초기화가 필수다."""
    co_initialized = False
    if sys.platform == "win32":
        try:
            import pythoncom  # type: ignore

            pythoncom.CoInitialize()
            co_initialized = True
        except Exception:
            pass
    try:
        return engine.dispatch(name, **kwargs)
    finally:
        if co_initialized:
            import pythoncom  # type: ignore

            pythoncom.CoUninitialize()


async def _call(engine: Any, name: str, **kwargs: Any) -> dict[str, Any]:
    try:
        return await anyio.to_thread.run_sync(
            functools.partial(_dispatch_in_thread, engine, name, kwargs)
        )
    except HwpctlError as exc:
        return {"ok": False, "command": name, "error": exc.message}
    except Exception as exc:  # com_error 등 — 스택 대신 한국어 한 줄 (#14)
        return {
            "ok": False,
            "command": name,
            "error": f"한/글 명령 처리 중 예상치 못한 오류가 발생했습니다: {exc}",
        }


def build_mcp(lock_timeout: float = 8.0):
    from mcp.server.fastmcp import FastMCP

    engine = _engine(lock_timeout)
    mcp = FastMCP("hwpctl", instructions=INSTRUCTIONS)

    @mcp.tool()
    async def status() -> dict[str, Any]:
        """열린 한/글 창의 경로, 수정 여부, 쪽, 버전."""
        return await _call(engine, "status")

    @mcp.tool()
    async def open(path: str = "", new: bool = False, discard: bool = False) -> dict[str, Any]:
        """새 문서 또는 경로로 연다. 수정본이 있으면 discard=true 필요."""
        return await _call(engine, "open", path=path or None, new=new, discard=discard)

    @mcp.tool()
    async def snapshot() -> dict[str, Any]:
        """제목, 본문, 표, 선택 영역을 읽는다. 캐럿·선택은 원래대로 복원."""
        return await _call(engine, "snapshot")

    @mcp.tool()
    async def insert_title(text: str, size: float = 20.0) -> dict[str, Any]:
        """제목 문단을 가운데·굵게·큰 글씨로 삽입. 서식은 제목에만 적용. Undo 한 단위."""
        return await _call(engine, "insert_title", text=text, size=size)

    @mcp.tool()
    async def insert_paragraph(text: str) -> dict[str, Any]:
        """본문 문단을 삽입한다. Undo 한 단위."""
        return await _call(engine, "insert_paragraph", text=text)

    @mcp.tool()
    async def create_table(
        rows: int,
        cols: int,
        header_fill: str = "",
        header: bool = True,
        cell_padding: str = "3.5,2.0",
    ) -> dict[str, Any]:
        """표를 만든다. 완료 뒤 반드시 별도 layout_review를 호출한다.
        header_fill 예: gray. cell_padding 은 새 표 모든 칸의 안쪽 여백
        (mm, '좌우,상하' 또는 '좌,우,상,하', 'none' 이면 미적용)."""
        return await _call(
            engine,
            "create_table",
            rows=rows,
            cols=cols,
            header_fill=header_fill,
            header=header,
            cell_margin=cell_padding,
        )

    @mcp.tool()
    async def set_cell_margin(
        table: int | None = None,
        cell_range: str = "",
        left: float = 3.5,
        right: float = 3.5,
        top: float = 2.0,
        bottom: float = 2.0,
    ) -> dict[str, Any]:
        """표 칸 안쪽 여백(mm). table 만 주면 그 표 전체 칸, cell_range 는 해당 칸만,
        둘 다 없으면 캐럿이 있는 셀."""
        return await _call(
            engine,
            "set_cell_margin",
            table=table,
            cell_range=cell_range,
            left=left,
            right=right,
            top=top,
            bottom=bottom,
        )

    @mcp.tool()
    async def set_col_width(
        widths: list[float],
        table: int | None = None,
        column: int | None = None,
        unit: str = "mm",
    ) -> dict[str, Any]:
        """열 너비를 지정한다. unit=mm 또는 표 전체 widths 비율인 ratio."""
        return await _call(
            engine,
            "set_col_width",
            widths=widths,
            table=table,
            column=column,
            unit=unit,
        )

    @mcp.tool()
    async def get_col_width(
        table: int | None = None,
        column: int | None = None,
    ) -> dict[str, Any]:
        """현재 열 또는 table의 column(1부터) 너비를 mm로 읽는다."""
        return await _call(engine, "get_col_width", table=table, column=column)

    @mcp.tool()
    async def set_row_height(
        height: float,
        table: int | None = None,
        row: int | None = None,
    ) -> dict[str, Any]:
        """현재 행 또는 table의 row(1부터) 높이를 mm로 지정한다."""
        return await _call(
            engine,
            "set_row_height",
            height=height,
            table=table,
            row=row,
        )

    @mcp.tool()
    async def get_row_height(
        table: int | None = None,
        row: int | None = None,
    ) -> dict[str, Any]:
        """현재 행 또는 table의 row(1부터) 높이를 mm로 읽는다."""
        return await _call(engine, "get_row_height", table=table, row=row)

    @mcp.tool()
    async def merge_cells(
        cell_range: str,
        table: int | None = None,
    ) -> dict[str, Any]:
        """cell_range(예: A1:B2)를 셀블록으로 선택해 합친다."""
        return await _call(
            engine,
            "merge_cells",
            cell_range=cell_range,
            table=table,
        )

    @mcp.tool()
    async def set_valign(
        align: str,
        table: int | None = None,
        cell_range: str = "",
    ) -> dict[str, Any]:
        """셀 세로 정렬. align은 top, center, bottom."""
        return await _call(
            engine,
            "set_valign",
            align=align,
            table=table,
            cell_range=cell_range,
        )

    @mcp.tool()
    async def set_cell_border(
        sides: str = "all",
        line_type: str = "Solid",
        width: str = "0.12mm",
        color: str = "#000000",
        table: int | None = None,
        cell_range: str = "",
    ) -> dict[str, Any]:
        """셀 테두리. sides는 all 또는 left,right,top,bottom; TypeHorz는 미지원."""
        return await _call(
            engine,
            "set_cell_border",
            sides=sides,
            line_type=line_type,
            width=width,
            color=color,
            table=table,
            cell_range=cell_range,
        )

    @mcp.tool()
    async def fill_cells(
        table: int = 0,
        cells: Any = None,
        assignments: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """표 셀을 채운다. cells는 2차원 배열 또는 {"A1":"값"}.
        완료 뒤 반드시 별도 layout_review를 호출한다."""
        return await _call(engine, "fill_cells", table=table, cells=cells, assignments=assignments)

    @mcp.tool()
    async def layout_review(
        table: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """표 편집 뒤 항상 호출한다. 셀 줄바꿈·행 높이·본문 폭·쪽 수를 읽고 고친다.
        table이 없으면 모든 표. 기본은 수정하며 dry_run=true면 계획만 반환한다."""
        return await _call(engine, "layout_review", table=table, dry_run=dry_run)

    @mcp.tool()
    async def insert_chart(
        table: int | None = None,
        cell_range: str = "",
        chart_type: str = "line",
        chart_index: int = 0,
        no_dialog: bool = True,
    ) -> dict[str, Any]:
        """데이터 표(또는 범위)를 선택해 한/글 네이티브 차트를 삽입한다 (그림 아님).
        chart_type: line(꺾은선)/column(세로막대)/bar(가로막대)/pie(원형).
        한글 2022 이상에서만 데이터 대화상자 없이 동작하며, 대화상자가 뜨면 실패다."""
        return await _call(
            engine,
            "insert_chart",
            table=table,
            cell_range=cell_range,
            chart_type=chart_type,
            chart_index=chart_index,
            no_dialog=no_dialog,
        )

    @mcp.tool()
    async def set_format(
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
        """선택·문단·행·셀범위 서식. fill 은 셀 배경. cell_range 는 요청 칸에만 적용."""
        return await _call(
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
    async def replace_selection(text: str) -> dict[str, Any]:
        """블록 선택 영역을 텍스트로 교체한다. 선택이 없으면 거부."""
        return await _call(engine, "replace_selection", text=text)

    @mcp.tool()
    async def set_style(style: str) -> dict[str, Any]:
        """현재 문단에 문서 스타일을 적용한다. 예: '개요 1'."""
        return await _call(engine, "set_style", style=style)

    @mcp.tool()
    async def undo() -> dict[str, Any]:
        """직전 hwpctl 명령을 한/글 Undo 한 덩어리로 되돌린다. 기록이 없으면 거부."""
        return await _call(engine, "undo")

    @mcp.tool()
    async def page(
        goto: int | None = None,
        break_page: bool = False,
    ) -> dict[str, Any]:
        """현재 쪽/PageCount를 읽고, goto로 이동하거나 break_page로 쪽을 나눈다."""
        return await _call(engine, "page", goto=goto, break_page=break_page)

    @mcp.tool()
    async def page_image(
        page: int = 0,
        out: str = "",
        resolution: int = 150,
    ) -> dict[str, Any]:
        """고정된 한/글 창의 쪽을 이미지로 저장한다.
        page는 1부터, 0은 현재 쪽. out이 비면 %LOCALAPPDATA%/hwpctl/page-N.bmp.
        CreatePageImage는 bmp로 쓰고, 경로가 .png/.jpg면 Pillow로 변환한다."""
        return await _call(engine, "page_image", page=page, out=out, resolution=resolution)

    @mcp.tool()
    async def inspect_format(limit: int = 40) -> dict[str, Any]:
        """문서 처음부터 문단을 순회해 정렬·글꼴·크기·굵게·색을 디자인 그룹으로 묶는다.
        InitScan/GetText는 쓰지 않고 캐럿을 문단에 둔 뒤 CharShape/ParaShape를 읽는다."""
        return await _call(engine, "inspect_format", limit=limit)

    @mcp.tool()
    async def set_pagedef(
        paper_width: float | None = None,
        paper_height: float | None = None,
        left: float | None = None,
        right: float | None = None,
        top: float | None = None,
        bottom: float | None = None,
        header: float | None = None,
        footer: float | None = None,
        gutter: float | None = None,
        landscape: bool | None = None,
        apply: str = "current",
    ) -> dict[str, Any]:
        """용지 크기와 여백(mm), 가로/세로 방향을 지정한다."""
        return await _call(
            engine,
            "set_pagedef",
            paper_width=paper_width,
            paper_height=paper_height,
            left=left,
            right=right,
            top=top,
            bottom=bottom,
            header=header,
            footer=footer,
            gutter=gutter,
            landscape=landscape,
            apply=apply,
        )

    @mcp.tool()
    async def save_as(path: str, format: str = "") -> dict[str, Any]:
        """새 경로로 저장한다. 원본은 덮어쓰지 않는다. 자동저장 없음."""
        return await _call(engine, "save_as", path=path, format=format)

    @mcp.tool()
    async def save(overwrite: bool = False) -> dict[str, Any]:
        """원본 경로에 저장. overwrite=true 필수."""
        return await _call(engine, "save", overwrite=overwrite)

    @mcp.tool()
    async def close(force: bool = False) -> dict[str, Any]:
        """문서를 닫는다. force=true 필수."""
        return await _call(engine, "close", force=force)

    @mcp.tool()
    async def list_tools() -> dict[str, Any]:
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
        if not hmac.compare_digest(provided.encode(), self.token.encode()):
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
        raise SystemExit(6)
    if host not in {"127.0.0.1", "localhost", "::1"}:
        print(
            "보안상 HTTP 는 localhost 에만 바인드하세요. "
            "원격(Grok Bot)은 사용자가 터널로 노출해야 합니다.",
            file=sys.stderr,
        )
        raise SystemExit(6)

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