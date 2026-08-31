"""고수준 한/글 명령. CLI 와 MCP 가 동일 함수를 호출한다.

각 쓰기 명령은 한/글 Undo 를 스택에 기록해 ``undo`` 한 번이 한 덩어리가 되게 한다.
자동저장은 없다. 원본 덮어쓰기는 ``save --overwrite`` 만 허용한다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from hwpctl.errors import DestructiveGuardError, HangulCommandError, UsageError
from hwpctl.hangul import HangulCanvas, a1, expand_range, parse_a1
from hwpctl.lock import SingleWriterLock, WriterState, load_state, save_state
from hwpctl.tools import tool_catalog

BODY_LIMIT = 8000


class Engine:
    def __init__(self, lock_timeout: float = 8.0, canvas_factory=HangulCanvas.connect) -> None:
        self.lock_timeout = lock_timeout
        self.canvas_factory = canvas_factory

    def _connect(
        self,
        *,
        new: bool = False,
        allow_launch: bool = False,
        pin: bool = False,
    ) -> HangulCanvas:
        """캔버스 연결 + 대상 창 고정 검증.

        open(pin=True) 이 창을 고정하고, 나머지 명령은 같은 창인지 검증한다.
        (pyhwpx 는 '마지막 접근 창'에 붙으므로, 여러 창이 열려 있으면 검증 없이는
        엉뚱한 문서를 편집할 수 있다.)
        """
        canvas = self.canvas_factory(new=new, allow_launch=allow_launch)
        hwnd = canvas.window_handle()
        if not hwnd:
            return canvas  # 핸들을 못 읽는 백엔드에서는 고정 기능을 끈다
        state = load_state()
        if pin or new:
            if state.target_hwnd != hwnd:
                state.target_hwnd = hwnd
                save_state(state)
            return canvas
        if state.target_hwnd and hwnd != state.target_hwnd:
            raise HangulCommandError(
                f"고정된 한/글 창(핸들 {state.target_hwnd})이 아닌 "
                f"다른 창(핸들 {hwnd})에 연결되었습니다. "
                "대상 창을 클릭해 활성화한 뒤 다시 시도하거나, "
                "hwpctl open 으로 작업 창을 다시 지정하세요."
            )
        if not state.target_hwnd:
            state.target_hwnd = hwnd
            save_state(state)
        return canvas

    def dispatch(self, command: str, **kwargs: Any) -> dict[str, Any]:
        handlers = {
            "status": self.status,
            "open": self.open,
            "snapshot": self.snapshot,
            "insert_title": self.insert_title,
            "insert_paragraph": self.insert_paragraph,
            "create_table": self.create_table,
            "fill_cells": self.fill_cells,
            "set_format": self.set_format,
            "replace_selection": self.replace_selection,
            "undo": self.undo,
            "page": self.page,
            "save_as": self.save_as,
            "save": self.save,
            "close": self.close,
        }
        if command not in handlers:
            raise UsageError(f"알 수 없는 명령입니다: {command}")
        return handlers[command](**kwargs)

    def status(self) -> dict[str, Any]:
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            info = canvas.doc_info()
            return {
                "ok": True,
                "command": "status",
                "window_title": info.window_title,
                "path": info.path,
                "modified": info.modified,
                "page": info.page,
                "page_count": info.page_count,
                "version": info.version,
                "backend": info.backend,
                "autosave": False,
                "tools": [t["name"] for t in tool_catalog()],
            }

    def snapshot(self) -> dict[str, Any]:
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            info = canvas.doc_info()
            body = canvas.get_body_text()
            truncated = len(body) > BODY_LIMIT
            if truncated:
                body = body[:BODY_LIMIT]
            # 선택이 없으면 get_selected_text 가 '현재 단어'를 리턴하므로 실제 블록일 때만 보고
            selection = canvas.get_selected_text() if canvas.has_selection() else ""
            tables = canvas.list_tables()
            title = _first_line(body) or info.window_title
            return {
                "ok": True,
                "command": "snapshot",
                "window_title": info.window_title,
                "title": title,
                "path": info.path,
                "modified": info.modified,
                "page": info.page,
                "page_count": info.page_count,
                "selection": selection,
                "body": body,
                "body_truncated": truncated,
                "tables": tables,
            }

    def open(
        self,
        path: str | None = None,
        new: bool = False,
        discard: bool = False,
    ) -> dict[str, Any]:
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect(new=new, allow_launch=True, pin=True)
            info = canvas.doc_info()
            if info.modified and not discard:
                raise DestructiveGuardError(
                    "저장하지 않은 수정본이 있습니다. "
                    "버리려면 --discard 를 주고, 지키려면 먼저 save_as 로 새 파일에 저장하세요. "
                    "자동저장은 하지 않습니다."
                )
            if path:
                canvas.open_path(str(Path(path).expanduser()))
            else:
                canvas.new_document()
            after = canvas.doc_info()
            state = load_state()
            state.original_path = after.path
            state.undo_stack = []
            state.last_command = "open"
            hwnd = canvas.window_handle()
            if hwnd:
                state.target_hwnd = hwnd
            save_state(state)
            return {
                "ok": True,
                "command": "open",
                "path": after.path,
                "window_title": after.window_title,
                "new": new,
            }

    def insert_title(self, text: str, size: float = 20.0) -> dict[str, Any]:
        if not text.strip():
            raise UsageError("제목 텍스트가 비어 있습니다.")
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            # 제목 서식(굵게·크게·가운데)이 다음 문단으로 새지 않도록,
            # 삽입 전 글자/문단 모양을 저장했다가 제목 뒤 새 문단에서 복원한다.
            saved_char = canvas.get_charshape()
            saved_para = canvas.get_parashape()
            steps = 0
            canvas.set_font(bold=True, height_pt=size)
            steps += 1
            canvas.set_align("center")
            steps += 1
            canvas.insert_text(_as_paragraph(text))
            steps += 1
            if canvas.set_charshape(saved_char):
                steps += 1
            if canvas.set_parashape(saved_para):
                steps += 1
            # 실제 실행된 한/글 액션 수를 그대로 기록해야 undo 가 한 덩어리로 돌아간다
            self._record_undo("insert_title", steps)
            return {
                "ok": True,
                "command": "insert_title",
                "text": text,
                "undo_units": 1,
                "hangul_actions": steps,
            }

    def insert_paragraph(self, text: str) -> dict[str, Any]:
        if text is None:
            raise UsageError("문단 텍스트가 없습니다.")
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            canvas.insert_text(_as_paragraph(text))
            self._record_undo("insert_paragraph", 1)
            return {"ok": True, "command": "insert_paragraph", "text": text, "undo_units": 1}

    def create_table(
        self,
        rows: int,
        cols: int,
        header_fill: str = "",
        header: bool = True,
    ) -> dict[str, Any]:
        if rows < 1 or cols < 1:
            raise UsageError("행과 열은 1 이상이어야 합니다.")
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            canvas.create_table(rows=rows, cols=cols, header=header)
            steps = 1
            if header_fill:
                if not canvas.is_cell():
                    canvas.get_into_nth_table(0)
                canvas.goto_addr("A1")
                canvas.select_row()
                canvas.cell_fill(header_fill)
                steps = 2
            self._record_undo("create_table", steps)
            return {
                "ok": True,
                "command": "create_table",
                "rows": rows,
                "cols": cols,
                "header_fill": header_fill,
                "undo_units": 1,
            }

    def fill_cells(
        self,
        table: int = 0,
        cells: Any = None,
        assignments: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        mapping = _normalize_cells(cells, assignments)
        if not mapping:
            raise UsageError("채울 셀이 없습니다. --cells JSON 또는 --cell A1=값 을 주세요.")
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            canvas.get_into_nth_table(table)
            written = 0
            # 셀마다 InsertText 가 Undo 를 만들 수 있어, 횟수를 기록한 뒤
            # hwpctl undo 가 한 번에 되돌린다.
            for addr, value in mapping.items():
                parse_a1(addr)
                canvas.goto_addr(addr)
                canvas.select_cell_text()
                canvas.insert_text(value)
                written += 1
            self._record_undo("fill_cells", max(1, written))
            return {
                "ok": True,
                "command": "fill_cells",
                "table": table,
                "written": written,
                "undo_units": 1,
            }

    def set_format(
        self,
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
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            steps = 0
            if table is not None:
                canvas.get_into_nth_table(table)
            if cell_range:
                addrs = expand_range(cell_range)
                canvas.goto_addr(addrs[0])
                if len(addrs) > 1 and _same_row(addrs):
                    canvas.select_row()
                elif row is not None:
                    canvas.goto_addr(a1(row - 1, 0))
                    canvas.select_row()
            elif row is not None:
                if table is None:
                    raise UsageError("--row 는 --table 과 함께 쓰세요.")
                canvas.goto_addr(a1(row - 1, 0))
                canvas.select_row()
            if fill:
                canvas.cell_fill(fill)
                steps += 1
            canvas.set_font(bold=bold, italic=italic, face=font, height_pt=size, text_color=color)
            if any(x is not None for x in (bold, italic, size)) or font or color:
                steps += 1
            if align:
                canvas.set_align(align)
                steps += 1
            if steps == 0:
                raise UsageError("적용할 서식이 없습니다.")
            self._record_undo("set_format", steps)
            return {"ok": True, "command": "set_format", "undo_units": 1}

    def replace_selection(self, text: str) -> dict[str, Any]:
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            # get_selected_text 는 선택이 없어도 '현재 단어'를 리턴하므로
            # 블록 선택 여부는 반드시 has_selection(GetSelectedPos is_block)으로 판정한다.
            if not canvas.has_selection():
                raise HangulCommandError(
                    "선택 영역이 없습니다. 한/글에서 바꿀 구간을 블록으로 선택한 뒤 "
                    "다시 호출하세요."
                )
            replaced_text = canvas.get_selected_text()
            canvas.insert_text(text)
            self._record_undo("replace_selection", 1)
            return {
                "ok": True,
                "command": "replace_selection",
                "replaced": True,
                "replaced_text": replaced_text,
                "undo_units": 1,
            }

    def undo(self) -> dict[str, Any]:
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            state = load_state()
            steps = state.undo_stack.pop() if state.undo_stack else 1
            steps = max(1, int(steps))
            for _ in range(steps):
                canvas.undo_once()
            state.last_command = "undo"
            save_state(state)
            return {"ok": True, "command": "undo", "hangul_undo_steps": steps}

    def page(self, goto: int | None = None) -> dict[str, Any]:
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            if goto is not None:
                canvas.goto_page(goto)
            info = canvas.doc_info()
            page = goto if goto is not None else info.page
            text = canvas.get_page_text(page)
            return {
                "ok": True,
                "command": "page",
                "page": page,
                "page_count": info.page_count,
                "text": text,
            }

    def save_as(self, path: str, format: str = "") -> dict[str, Any]:
        dest = Path(path).expanduser()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            info = canvas.doc_info()
            if info.path and _same_file(info.path, dest) and dest.exists():
                raise DestructiveGuardError(
                    "save_as 는 원본을 덮어쓰지 않습니다. "
                    "같은 경로에 저장하려면 save --overwrite 를 쓰세요."
                )
            canvas.save_as(str(dest), fmt=format)
            return {
                "ok": True,
                "command": "save_as",
                "path": str(dest),
                "original_path": info.path,
                "autosave": False,
            }

    def save(self, overwrite: bool = False) -> dict[str, Any]:
        if not overwrite:
            raise DestructiveGuardError(
                "원본 파일을 덮어쓰려면 --overwrite 가 필요합니다. "
                "기본은 save_as 로 새 경로에 저장하는 것입니다. 자동저장은 없습니다."
            )
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            info = canvas.doc_info()
            if not info.path:
                raise HangulCommandError(
                    "아직 파일 경로가 없습니다. save_as 로 새 경로를 지정하세요."
                )
            canvas.save_overwrite()
            return {
                "ok": True,
                "command": "save",
                "path": info.path,
                "overwritten": True,
            }

    def close(self, force: bool = False) -> dict[str, Any]:
        if not force:
            raise DestructiveGuardError(
                "문서를 닫으려면 --force 가 필요합니다. "
                "저장하지 않은 내용은 사라집니다. 먼저 save_as 를 권장합니다."
            )
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            canvas.close_discard()
            state = load_state()
            state.undo_stack = []
            state.last_command = "close"
            state.target_hwnd = 0  # 창이 닫혔으니 고정 해제
            save_state(state)
            return {"ok": True, "command": "close", "closed": True}

    def _record_undo(self, command: str, hangul_steps: int) -> None:
        state = load_state()
        state.undo_stack.append(max(1, hangul_steps))
        state.last_command = command
        save_state(state)


def suggested_save_as_path(original: str) -> str:
    if not original:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return str(Path.home() / "Documents" / f"hwpctl-{stamp}.hwpx")
    src = Path(original)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return str(src.with_name(f"{src.stem}-edited-{stamp}{src.suffix or '.hwpx'}"))


def _as_paragraph(text: str) -> str:
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    if not body.endswith("\n"):
        body += "\n"
    return body.replace("\n", "\r\n")


def _first_line(text: str) -> str:
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.strip():
            return line.strip()
    return ""


def _same_file(a: str, b: Path) -> bool:
    try:
        return Path(a).expanduser().resolve() == b.expanduser().resolve()
    except OSError:
        return Path(a).as_posix().lower() == b.as_posix().lower()


def _same_row(addrs: list[str]) -> bool:
    rows = {parse_a1(a)[0] for a in addrs}
    return len(rows) == 1


def _normalize_cells(cells: Any, assignments: dict[str, str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if assignments:
        out.update({k.upper(): v for k, v in assignments.items()})
    if cells is None:
        return out
    if isinstance(cells, dict):
        for key, value in cells.items():
            out[str(key).upper()] = "" if value is None else str(value)
        return out
    if isinstance(cells, list):
        for r, row in enumerate(cells):
            if isinstance(row, dict):
                for key, value in row.items():
                    out[str(key).upper()] = "" if value is None else str(value)
                continue
            if not isinstance(row, (list, tuple)):
                out[a1(r, 0)] = str(row)
                continue
            for c, value in enumerate(row):
                out[a1(r, c)] = "" if value is None else str(value)
        return out
    raise UsageError("cells 는 JSON 배열 또는 객체여야 합니다.")