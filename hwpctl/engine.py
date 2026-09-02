"""고수준 한/글 명령. CLI 와 MCP 가 동일 함수를 호출한다.

각 쓰기 명령은 한/글 Undo 를 스택에 기록해 ``undo`` 한 번이 한 덩어리가 되게 한다.
자동저장은 없다. 원본 덮어쓰기는 ``save --overwrite`` 만 허용한다.
"""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Any

from hwpctl.colors import parse_color
from hwpctl.errors import DestructiveGuardError, HangulCommandError, UsageError
from hwpctl.hangul import (
    HangulCanvas,
    a1,
    close_all_open_documents_discard,
    expand_range,
    parse_a1,
)
from hwpctl.layout import plan_table_layout
from hwpctl.lock import SingleWriterLock, WriterState, load_state, save_state
from hwpctl.tools import tool_catalog

BODY_LIMIT = 8000

# 이력서 등 문서에서 글자가 테두리에 붙지 않도록 새 표에 기본 적용하는 셀 안 여백(mm).
# 한/글 기본값(1.8/0.5)보다 넉넉하게. (좌, 우, 상, 하)
DEFAULT_CELL_MARGIN: tuple[float, float, float, float] = (3.5, 3.5, 2.0, 2.0)

# InsertChart 의 ChartGroup 매핑.
# 확인된 값: 0=가로막대, 1=세로막대(포럼 1649 예제), 3=원형(포럼 1529 답변).
# 2=꺾은선(line)은 0/1/3 확인값과 한/글 차트 종류 순서에서 추론 — 실기(한글 2022) 검증 필요.
CHART_GROUPS: dict[str, int] = {"bar": 0, "column": 1, "line": 2, "pie": 3}


class Engine:
    def __init__(
        self,
        lock_timeout: float = 8.0,
        canvas_factory=HangulCanvas.connect,
        document_lister=HangulCanvas.list_open_documents,
        document_closer=close_all_open_documents_discard,
    ) -> None:
        self.lock_timeout = lock_timeout
        self.canvas_factory = canvas_factory
        self.document_lister = document_lister
        self.document_closer = document_closer

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
        state = load_state()
        # 일반 명령은 고정된 WindowHandle 로 ROT 객체를 고른다 (라이브: 120.2).
        # open --new 는 이전 핸들을 넘기지 않는다. 만든 뒤 활성 창을 다시 고정한다.
        want_hwnd = 0 if new else int(state.target_hwnd or 0)
        canvas = self.canvas_factory(
            new=new, allow_launch=allow_launch, hwnd=want_hwnd
        )
        hwnd = canvas.window_handle()
        if not hwnd:
            return canvas  # 핸들을 못 읽는 백엔드에서는 고정 기능을 끈다
        state = load_state()
        if new:
            # connect(new=True)가 새 문서를 정확히 한 번 만든다. open()은
            # 그 활성 창을 확인한 뒤 아래에서 고정만 한다.
            return canvas
        if pin:
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
            "list_documents": self.list_documents,
            "open": self.open,
            "snapshot": self.snapshot,
            "format_paragraph_by_text": self.format_paragraph_by_text,
            "recreate_inline_table_before_paragraph": self.recreate_inline_table_before_paragraph,
            "trim_blank_paragraphs_before_body": self.trim_blank_paragraphs_before_body,
            "insert_title": self.insert_title,
            "insert_paragraph": self.insert_paragraph,
            "write_cell": self.write_cell,
            "create_table": self.create_table,
            "fill_cells": self.fill_cells,
            "exit_table": self.exit_table,
            "set_table_properties": self.set_table_properties,
            "set_table_position": self.set_table_position,
            "set_cell_margin": self.set_cell_margin,
            "set_col_width": self.set_col_width,
            "get_col_width": self.get_col_width,
            "set_row_height": self.set_row_height,
            "get_row_height": self.get_row_height,
            "merge_cells": self.merge_cells,
            "set_valign": self.set_valign,
            "set_cell_border": self.set_cell_border,
            "layout_review": self.layout_review,
            "insert_chart": self.insert_chart,
            "insert_image": self.insert_image,
            "insert_text_box": self.insert_text_box,
            "set_cell_fill": self.set_cell_fill,
            "set_format": self.set_format,
            "set_style": self.set_style,
            "replace_selection": self.replace_selection,
            "undo": self.undo,
            "page": self.page,
            "set_page_number": self.set_page_number,
            "set_page_visibility": self.set_page_visibility,
            "restart_page_number": self.restart_page_number,
            "set_pagedef": self.set_pagedef,
            "save_as": self.save_as,
            "save": self.save,
            "close": self.close,
            "close_all": self.close_all,
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

    def list_documents(self) -> dict[str, Any]:
        """모든 실행 중 한/글 문서를 활성화 없이 읽기 전용으로 열거한다."""
        with SingleWriterLock(timeout=self.lock_timeout):
            documents = self.document_lister()
        return {
            "ok": True,
            "command": "list_documents",
            "read_only": True,
            "count": len(documents),
            "documents": documents,
        }

    def snapshot(self) -> dict[str, Any]:
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            info = canvas.doc_info()
            # 읽기 명령이 사용자의 캐럿·선택을 파괴하지 않도록 저장 후 복원한다.
            saved_pos = canvas.get_pos()
            saved_sel = canvas.selection_range()
            body = canvas.get_body_text()
            truncated = len(body) > BODY_LIMIT
            if truncated:
                body = body[:BODY_LIMIT]
            # 선택이 없으면 get_selected_text 가 '현재 단어'를 리턴하므로 실제 블록일 때만 보고
            selection = canvas.get_selected_text() if saved_sel else ""
            try:
                tables = canvas.list_tables()
            finally:
                canvas.set_pos(saved_pos)
                if saved_sel:
                    canvas.restore_selection(saved_sel)
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
                "table_count": canvas.table_count(),
            }

    def format_paragraph_by_text(
        self,
        text: str,
        font: str = "",
        size: float | None = None,
        bold: bool | None = None,
        italic: bool | None = None,
        color: str = "",
        letter_spacing_percent: int | None = None,
        width_scale_percent: int | None = None,
        paragraph: Any = None,
        occurrence: int = 1,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """정확히 일치하는 일반 본문 문단 하나에만 글자·문단 서식을 적용한다.

        기존 ``set_format`` 은 사용자가 한/글에서 선택한 위치나 표 셀을 대상으로
        한다. 이 명령은 그 전제가 없는 자동화에서도 *한 문단 전체와 정확히 일치*
        할 때만 동작한다. 검색 결과가 셀/필드이거나 문단 일부면 실패하며, dry_run은
        찾기·검증만 하고 캐럿과 선택을 원래대로 되돌린다.
        """
        if not isinstance(text, str) or not text:
            raise UsageError("text 는 비어 있지 않은 한 문단 문자열이어야 합니다.")
        if "\r" in text or "\n" in text:
            raise UsageError("text 에 줄바꿈을 넣을 수 없습니다. 한 문단만 지정하세요.")
        if not isinstance(dry_run, bool):
            raise UsageError("dry_run 값은 true 또는 false여야 합니다.")
        if isinstance(occurrence, bool) or not isinstance(occurrence, int) or occurrence < 1:
            raise UsageError("occurrence 는 1 이상의 정수여야 합니다.")
        if font is None:
            font = ""
        if color is None:
            color = ""
        _validate_text_format(
            bold=bold,
            italic=italic,
            font=font,
            size=size,
            color=color,
        )
        normalized_font = font.strip() if isinstance(font, str) else font
        normalized_color = _normalize_optional_color(color)
        normalized_spacing = _normalize_character_percent(
            letter_spacing_percent,
            "letter_spacing_percent",
            minimum=-50,
            maximum=50,
        )
        normalized_width = _normalize_character_percent(
            width_scale_percent,
            "width_scale_percent",
            minimum=50,
            maximum=200,
        )
        normalized_paragraph = _normalize_paragraph_layout(paragraph)
        has_character_format = any(
            value is not None
            for value in (
                bold,
                italic,
                size,
                normalized_spacing,
                normalized_width,
            )
        ) or bool(normalized_font) or bool(normalized_color)
        if not dry_run and not (has_character_format or normalized_paragraph):
            raise UsageError("적용할 글자 또는 문단 서식이 없습니다.")

        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            saved_pos = canvas.get_pos()
            saved_sel = canvas.selection_range()
            actions = 0
            match: dict[str, Any] | None = None
            try:
                match = canvas.select_exact_body_paragraph(text, occurrence=occurrence)
                current_page = canvas.doc_info().page
                if dry_run:
                    return {
                        "ok": True,
                        "command": "format_paragraph_by_text",
                        "dry_run": True,
                        "matched": match["text"],
                        "page": current_page,
                        "occurrence": occurrence,
                        "in_cell": False,
                        "undo_units": 0,
                    }
                if has_character_format:
                    canvas.set_font(
                        bold=bold,
                        italic=italic,
                        face=normalized_font,
                        height_pt=size,
                        text_color=normalized_color,
                        letter_spacing_percent=normalized_spacing,
                        width_scale_percent=normalized_width,
                    )
                    actions += 1
                if normalized_paragraph:
                    canvas.set_paragraph_format(**normalized_paragraph)
                    actions += 1
                canvas.assert_no_dialog()
            except Exception:
                if actions:
                    self._record_undo("format_paragraph_by_text", actions)
                raise
            finally:
                canvas.set_pos(saved_pos)
                if saved_sel:
                    canvas.restore_selection(saved_sel)
            self._record_undo("format_paragraph_by_text", actions)
            assert match is not None
            return {
                "ok": True,
                "command": "format_paragraph_by_text",
                "dry_run": False,
                "matched": match["text"],
                "page": current_page,
                "occurrence": occurrence,
                "in_cell": False,
                "paragraph": normalized_paragraph,
                "undo_units": 1,
                "hangul_actions": actions,
            }

    def recreate_inline_table_before_paragraph(
        self,
        old_table: int,
        expected_table_text: str,
        before_text: str,
        table_spec: Any,
        blank_paragraph: Any,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """검증된 기존 표를 같은 열린 문서의 본문 문단 앞으로 다시 만든다.

        Cut/Paste·클립보드·HWPML 주입을 쓰지 않는다. 새 1×1 인라인 표가 완전히
        검증된 뒤에만 원래 표 컨트롤 하나를 ``DeleteCtrl``로 제거한다. 질문 표와
        답변 사이에는 source 사양의 빈 일반 문단 하나를 보장한다.
        """
        if isinstance(old_table, bool) or not isinstance(old_table, int) or old_table < 0:
            raise UsageError("old_table 은 0 이상의 표 번호여야 합니다.")
        if not isinstance(expected_table_text, str) or not expected_table_text:
            raise UsageError("expected_table_text 는 비어 있지 않은 표 A1 문자열이어야 합니다.")
        if not isinstance(before_text, str) or not before_text:
            raise UsageError("before_text 는 비어 있지 않은 한 문단 문자열이어야 합니다.")
        if "\r" in before_text or "\n" in before_text:
            raise UsageError("before_text 에 줄바꿈을 넣을 수 없습니다. 한 문단만 지정하세요.")
        if not isinstance(dry_run, bool):
            raise UsageError("dry_run 값은 true 또는 false여야 합니다.")

        table = _normalize_inline_single_cell_table(table_spec)
        blank = _normalize_blank_paragraph(blank_paragraph)
        expected = HangulCanvas._paragraph_text_for_compare(expected_table_text)

        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            saved_pos = canvas.get_pos()
            saved_sel = canvas.selection_range()
            actions = 0
            original_count = canvas.table_count()
            old_ctrl: Any | None = None
            new_table_created = False
            try:
                canvas.get_into_nth_table(old_table)
                canvas.goto_addr("A1")
                canvas.select_cell_text()
                actual = HangulCanvas._paragraph_text_for_compare(canvas.get_selected_text())
                if actual != expected:
                    raise HangulCommandError(
                        f"{old_table}번 표 A1이 지정한 질문과 정확히 일치하지 않아 수정을 중단했습니다."
                    )
                old_ctrl = canvas.table_control(old_table)
                canvas.run("Cancel")
                match = canvas.select_exact_body_paragraph(before_text)
                if dry_run:
                    return {
                        "ok": True,
                        "command": "recreate_inline_table_before_paragraph",
                        "dry_run": True,
                        "old_table": old_table,
                        "matched_table_text": actual,
                        "before_text": match["text"],
                        "page": canvas.doc_info().page,
                        "undo_units": 0,
                    }

                # 첫 빈 문단은 새 표의 앵커가 되고, 표를 빠져나온 뒤 한 번 더
                # 확보하는 빈 문단이 원본의 질문→Enter→답변 구조가 된다.
                if canvas.ensure_blank_paragraph_before_body(before_text):
                    actions += 1
                if canvas.is_cell():
                    raise HangulCommandError("새 질문 표의 앵커가 본문 밖에 있지 않습니다.")
                canvas.create_table(rows=1, cols=1, header=False)
                actions += 1
                new_table_created = True
                if not canvas.is_cell():
                    raise HangulCommandError("질문 표를 만들었지만 새 표 셀 안으로 이동하지 못했습니다.")
                canvas.goto_addr("A1")
                canvas.set_col_width_current(table["column_width_mm"])
                actions += 1
                canvas.goto_addr("A1")
                canvas.set_row_height_current(table["row_height_mm"])
                actions += 1
                canvas.goto_addr("A1")
                canvas.set_cell_margin_current(*table["margin_mm"])
                actions += 1
                canvas.goto_addr("A1")
                canvas.set_valign_current(table["valign"])
                actions += 1
                canvas.goto_addr("A1")
                actions += _action_count(canvas.set_cell_fill(fill=table["fill"]))
                for border in table["borders"]:
                    canvas.goto_addr("A1")
                    canvas.set_cell_border_current(**border)
                    actions += 1

                canvas.goto_addr("A1")
                canvas.select_cell_text()
                canvas.insert_text("")
                actions += 1
                paragraph_actions = [0]
                for index, paragraph_spec in enumerate(table["paragraphs"]):
                    self._write_paragraph_spec(
                        canvas,
                        paragraph_spec,
                        terminate=index < len(table["paragraphs"]) - 1,
                        actions=paragraph_actions,
                    )
                actions += paragraph_actions[0]

                canvas.goto_addr("A1")
                actions += canvas.set_current_table_properties(**table["properties"])
                canvas.goto_addr("A1")
                actions += canvas.set_current_inline_table_position(**table["position"])
                canvas.goto_addr("A1")
                canvas.select_cell_text()
                new_text = HangulCanvas._paragraph_text_for_compare(canvas.get_selected_text())
                if new_text != expected:
                    raise HangulCommandError("새 질문 표의 A1 텍스트 검증에 실패했습니다.")
                canvas.run("Cancel")
                canvas.goto_addr("A1")
                canvas.exit_table()
                if canvas.ensure_blank_paragraph_before_body(before_text):
                    actions += 1
                blank_actions = [0]
                _apply_empty_paragraph_spec(canvas, blank, blank_actions)
                actions += blank_actions[0]
                # answer가 표 셀/글상자에 들어가지 않았는지 마지막으로 다시 검증한다.
                canvas.select_exact_body_paragraph(before_text)
                canvas.run("Cancel")
                assert old_ctrl is not None
                canvas.delete_table_control(old_ctrl)
                actions += 1
                if canvas.table_count() != original_count:
                    raise HangulCommandError(
                        "질문 표 교체 뒤 표 개수가 원래와 달라 수정을 중단했습니다."
                    )
                canvas.assert_no_dialog()
            except Exception:
                if actions:
                    self._record_undo("recreate_inline_table_before_paragraph", actions)
                raise
            finally:
                if saved_pos is not None:
                    canvas.set_pos(saved_pos)
                if saved_sel:
                    canvas.restore_selection(saved_sel)
            self._record_undo("recreate_inline_table_before_paragraph", actions)
            return {
                "ok": True,
                "command": "recreate_inline_table_before_paragraph",
                "dry_run": False,
                "old_table": old_table,
                "new_table": "inline 1x1",
                "matched_table_text": expected,
                "before_text": before_text,
                "blank_paragraph": True,
                "table_count": original_count,
                "undo_units": 1,
                "hangul_actions": actions,
                "new_table_created": new_table_created,
            }

    def trim_blank_paragraphs_before_body(
        self,
        text: str,
        keep: int = 1,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """본문 바로 앞의 연속 빈 문단을 ``keep``개만 남긴다.

        표 아래의 여분 Enter만 대상으로 하며, 표/답변/다른 문단의 텍스트는
        선택하지 않는다. 사용자가 표 흐름을 보고 고친 뒤 같은 구조를 재현할 때
        쓰는 좁은 공개 명령이다.
        """
        if not isinstance(text, str) or not text or "\r" in text or "\n" in text:
            raise UsageError("text 는 비어 있지 않은 한 문단 문자열이어야 합니다.")
        if isinstance(keep, bool) or not isinstance(keep, int) or not 0 <= keep <= 8:
            raise UsageError("keep 은 0~8 정수여야 합니다.")
        if not isinstance(dry_run, bool):
            raise UsageError("dry_run 값은 true 또는 false여야 합니다.")
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            saved_pos = canvas.get_pos()
            saved_sel = canvas.selection_range()
            actions = 0
            try:
                before = canvas.count_blank_paragraphs_before_body(text)
                if before < keep:
                    raise HangulCommandError(
                        f"본문 앞 빈 문단이 {before}개라 {keep}개를 남길 수 없습니다."
                    )
                if dry_run:
                    return {
                        "ok": True,
                        "command": "trim_blank_paragraphs_before_body",
                        "dry_run": True,
                        "text": text,
                        "before": before,
                        "keep": keep,
                        "remove": before - keep,
                        "undo_units": 0,
                    }
                while before > keep:
                    canvas.remove_empty_paragraph_immediately_before_body(text)
                    actions += 1
                    remaining = canvas.count_blank_paragraphs_before_body(text)
                    if remaining != before - 1:
                        raise HangulCommandError(
                            "빈 문단 제거 뒤 문단 경계가 예상과 달라 수정을 중단했습니다."
                        )
                    before = remaining
                canvas.assert_no_dialog()
            except Exception:
                if actions:
                    self._record_undo("trim_blank_paragraphs_before_body", actions)
                raise
            finally:
                if saved_pos is not None:
                    canvas.set_pos(saved_pos)
                if saved_sel:
                    canvas.restore_selection(saved_sel)
            if actions:
                self._record_undo("trim_blank_paragraphs_before_body", actions)
            return {
                "ok": True,
                "command": "trim_blank_paragraphs_before_body",
                "dry_run": False,
                "text": text,
                "keep": keep,
                "removed": actions,
                "remaining": keep,
                "undo_units": 1 if actions else 0,
                "hangul_actions": actions,
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
                    "버리려면 --discard (MCP: discard=true) 를 주고, "
                    "지키려면 먼저 save_as 로 새 파일에 저장하세요. "
                    "자동저장은 하지 않습니다."
                )
            if path:
                canvas.open_path(str(Path(path).expanduser()))
            elif not new:
                # open --new 의 새 문서는 connect(new=True)가 이미 만들었다.
                canvas.new_document()
            after = canvas.doc_info()
            # 새 창/다른 문서를 연 뒤에는 고정을 그 창의 WindowHandle 로 옮긴다.
            # (과거: Item(0) 이 이전 창을 가리켜 pin 이 낡고 다음 명령이 거부됨)
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

    def insert_paragraph(
        self,
        text: str = "",
        runs: Any = None,
        paragraph: Any = None,
        page_break_before: bool = False,
    ) -> dict[str, Any]:
        """새 일반 문단을 쓴다.

        단순 ``text`` 호출은 기존 인터페이스와 같다. ``runs`` 를 주면 한 문단 안의
        서로 다른 글자 서식(글꼴·크기·자간·장평·그림자)을 명시할 수 있고,
        ``paragraph`` 는 해당 문단의 정렬·여백·들여쓰기·줄간격을 명시한다.
        HWPML을 주입하지 않고도 참조 문서의 문단 흐름을 재조립하기 위한 공개
        편집 단위다.
        """
        spec = _normalize_paragraph_spec(
            text=text,
            runs=runs,
            paragraph=paragraph,
            page_break_before=page_break_before,
        )
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            saved_char = canvas.get_charshape()
            saved_para = canvas.get_parashape()
            actions = [0]
            try:
                self._write_paragraph_spec(canvas, spec, terminate=True, actions=actions)
            except Exception:
                if actions[0]:
                    self._record_undo("insert_paragraph", actions[0])
                raise
            # 새 문단을 끝낸 뒤에만 복원한다. 그래야 작성한 문단이 아니라 다음
            # 빈 문단의 입력 서식만 원래 상태로 돌아간다.
            if canvas.set_charshape(saved_char):
                actions[0] += 1
            if canvas.set_parashape(saved_para):
                actions[0] += 1
            self._record_undo("insert_paragraph", max(1, actions[0]))
            return {
                "ok": True,
                "command": "insert_paragraph",
                "text": text,
                "runs": spec["runs"],
                "paragraph": spec["paragraph"],
                "page_break_before": spec["page_break_before"],
                "undo_units": 1,
                "hangul_actions": actions[0],
            }

    def write_cell(
        self,
        table: int,
        cell: str,
        paragraphs: Any,
    ) -> dict[str, Any]:
        """한 표 셀의 기존 내용을 지우고 구조화 문단 목록으로 교체한다.

        ``paragraphs`` 의 각 원소는 ``insert_paragraph`` 와 같은 ``text``/``runs``/
        ``paragraph`` 구조다. 표 안에서는 쪽 나누기가 유효하지 않으므로
        ``page_break_before`` 는 명확히 거부한다. 마지막 문단 뒤에 빈 문단을
        덧붙이지 않아 셀 높이와 조판이 불필요하게 바뀌지 않게 한다.
        """
        if isinstance(table, bool) or not isinstance(table, int) or table < 0:
            raise UsageError("table 은 0 이상의 표 번호여야 합니다.")
        address = _normalize_cell_address(cell)
        specs = _normalize_cell_paragraphs(paragraphs)
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            canvas.get_into_nth_table(table)
            canvas.goto_addr(address)
            canvas.select_cell_text()
            actions = [0]
            try:
                # InsertText는 선택된 셀 텍스트를 원자적으로 교체한다. 빈 문자열도
                # 기존 내용을 지우는 편집 액션이므로 Undo 계산에 포함한다.
                canvas.insert_text("")
                actions[0] += 1
                for index, spec in enumerate(specs):
                    self._write_paragraph_spec(
                        canvas,
                        spec,
                        terminate=index < len(specs) - 1,
                        actions=actions,
                    )
            except Exception:
                if actions[0]:
                    self._record_undo("write_cell", actions[0])
                raise
            # 마지막 문단의 문단 모양을 복원하면 현재 문단 자체가 덮일 수 있어
            # 복원하지 않는다. 다음 write_cell은 자체 paragraph 사양을 적용한다.
            self._record_undo("write_cell", max(1, actions[0]))
            return {
                "ok": True,
                "command": "write_cell",
                "table": table,
                "cell": address,
                "paragraph_count": len(specs),
                "replaced": True,
                "undo_units": 1,
                "hangul_actions": actions[0],
            }

    @staticmethod
    def _write_paragraph_spec(
        canvas: HangulCanvas,
        spec: dict[str, Any],
        *,
        terminate: bool,
        actions: list[int],
    ) -> None:
        if spec["page_break_before"]:
            canvas.break_page()
            actions[0] += 1
        if spec["paragraph"]:
            canvas.set_paragraph_format(**spec["paragraph"])
            actions[0] += 1
        for run in spec["runs"]:
            format_kwargs = _run_font_kwargs(run)
            if format_kwargs:
                canvas.set_font(**format_kwargs)
                actions[0] += 1
            if run["text"]:
                canvas.insert_text(run["text"])
                actions[0] += 1
        if terminate:
            canvas.break_paragraph()
            actions[0] += 1

    def create_table(
        self,
        rows: int,
        cols: int,
        header_fill: str = "",
        header: bool = True,
        cell_margin: Any = DEFAULT_CELL_MARGIN,
    ) -> dict[str, Any]:
        if rows < 1 or cols < 1:
            raise UsageError("행과 열은 1 이상이어야 합니다.")
        margins = _normalize_margin(cell_margin)
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            canvas.create_table(rows=rows, cols=cols, header=header)
            # 이후 여백·헤더색은 반드시 "방금 만든 표"에만 적용한다.
            # TableCreate 는 캐럿을 새 표 안에 남기므로, 셀 밖이면 문서의 다른 표를
            # 건드리지 말고(과거 버그: 0번 표에 칠함) 즉시 실패한다.
            steps = 1
            needs_cell = bool(margins or header_fill)
            if needs_cell and not canvas.is_cell():
                raise HangulCommandError(
                    "표는 만들었지만 캐럿이 새 표 안에 있지 않아 "
                    "안 여백/머리행 색을 적용하지 못했습니다. "
                    "set_cell_margin / set_format 으로 표 번호를 지정해 다시 적용하세요."
                )
            try:
                if margins:
                    for addr in canvas.table_cell_addresses():
                        canvas.goto_addr(addr)
                        canvas.set_cell_margin_current(*margins)
                        steps += 1
                if header_fill:
                    canvas.goto_addr("A1")
                    canvas.select_row()
                    canvas.cell_fill(header_fill)
                    steps += 1
            except Exception:
                self._record_undo("create_table", steps)
                raise
            self._record_undo("create_table", steps)
            return {
                "ok": True,
                "command": "create_table",
                "rows": rows,
                "cols": cols,
                "header_fill": header_fill,
                "cell_margin_mm": list(margins) if margins else None,
                "undo_units": 1,
            }

    def set_cell_margin(
        self,
        table: int | None = None,
        cell_range: str = "",
        left: float = 3.5,
        right: float = 3.5,
        top: float = 2.0,
        bottom: float = 2.0,
    ) -> dict[str, Any]:
        for value in (left, right, top, bottom):
            if value < 0 or value > 50:
                raise UsageError("셀 안 여백은 0~50mm 범위로 지정하세요.")
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            if table is not None:
                canvas.get_into_nth_table(table)
            if cell_range:
                if not canvas.is_cell():
                    raise UsageError(
                        "--range 는 캐럿이 표 안에 있거나 --table 과 함께 써야 합니다."
                    )
                addrs = expand_range(cell_range)
                steps = 0
                try:
                    for addr in addrs:
                        canvas.goto_addr(addr)
                        canvas.set_cell_margin_current(left, right, top, bottom)
                        steps += 1
                except Exception:
                    if steps:
                        self._record_undo("set_cell_margin", steps)
                    raise
                scope = f"cells:{cell_range.upper()}"
            elif table is not None:
                steps = 0
                try:
                    for addr in canvas.table_cell_addresses():
                        canvas.goto_addr(addr)
                        canvas.set_cell_margin_current(left, right, top, bottom)
                        steps += 1
                except Exception:
                    if steps:
                        self._record_undo("set_cell_margin", steps)
                    raise
                scope = f"table:{table}"
            else:
                canvas.set_cell_margin_current(left, right, top, bottom)
                steps = 1
                scope = "current-cell"
            self._record_undo("set_cell_margin", steps)
            return {
                "ok": True,
                "command": "set_cell_margin",
                "scope": scope,
                "margin_mm": [left, right, top, bottom],
                "undo_units": 1,
            }

    def set_col_width(
        self,
        widths: Any,
        table: int | None = None,
        column: int | None = None,
        unit: str = "mm",
    ) -> dict[str, Any]:
        values = _normalize_positive_numbers(widths, "열 너비")
        unit = (unit or "").strip().lower()
        if unit not in {"mm", "ratio"}:
            raise UsageError("열 너비 단위는 mm 또는 ratio 여야 합니다.")
        if column is not None and column < 1:
            raise UsageError("--column 은 1 이상의 열 번호여야 합니다.")
        if column is not None and len(values) != 1:
            raise UsageError("--column 과 함께 쓸 때는 열 너비를 하나만 지정하세요.")
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            if table is not None:
                if table < 0:
                    raise UsageError("--table 은 0 이상의 표 번호여야 합니다.")
                canvas.get_into_nth_table(table)
            if not canvas.is_cell():
                raise HangulCommandError("캐럿이 표 안에 있지 않아 열 너비를 바꿀 수 없습니다.")
            representatives = canvas.table_column_addresses()
            columns = sorted(representatives)
            existing = canvas.get_table_column_widths()
            if column is not None:
                requested_col = column - 1
                if requested_col not in representatives:
                    raise UsageError(f"{column}열은 병합 구조 때문에 조절할 셀을 찾지 못했습니다.")
                target_columns = [requested_col]
            else:
                target_columns = columns[: len(values)]
            if len(target_columns) != len(values):
                raise UsageError(
                    f"지정한 열 범위가 표의 {len(existing)}개 열을 벗어납니다."
                )
            if unit == "ratio":
                if column is not None:
                    raise UsageError("ratio는 --column 없이 표의 모든 열 비율을 지정하세요.")
                if len(values) != len(existing):
                    raise UsageError(
                        f"ratio 값은 표 열 수({len(existing)})와 같은 개수여야 합니다."
                    )
                total_width = sum(existing)
                total_ratio = sum(values)
                targets = [value / total_ratio * total_width for value in values]
            else:
                targets = values
            actions = 0
            try:
                for target_col, target in zip(target_columns, targets):
                    canvas.goto_addr(representatives[target_col])
                    canvas.set_col_width_current(target)
                    actions += 1
            except Exception:
                if actions:
                    self._record_undo("set_col_width", actions)
                raise
            self._record_undo("set_col_width", actions)
            return {
                "ok": True,
                "command": "set_col_width",
                "table": table,
                "column": column,
                "unit": unit,
                "requested": values,
                "widths_mm": targets,
                "undo_units": 1,
                "hangul_actions": actions,
            }

    def get_col_width(
        self,
        table: int | None = None,
        column: int | None = None,
    ) -> dict[str, Any]:
        if column is not None and column < 1:
            raise UsageError("--column 은 1 이상의 열 번호여야 합니다.")
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            if table is not None:
                if table < 0:
                    raise UsageError("--table 은 0 이상의 표 번호여야 합니다.")
                canvas.get_into_nth_table(table)
            if not canvas.is_cell():
                raise HangulCommandError("캐럿이 표 안에 있지 않아 열 너비를 읽을 수 없습니다.")
            saved = canvas.get_pos()
            try:
                if column is not None:
                    representatives = canvas.table_column_addresses()
                    if column - 1 not in representatives:
                        raise UsageError(
                            f"{column}열은 병합 구조 때문에 너비를 읽을 셀을 찾지 못했습니다."
                        )
                    canvas.goto_addr(representatives[column - 1])
                    widths = [canvas.get_col_width()]
                elif table is not None:
                    widths = canvas.get_table_column_widths()
                else:
                    widths = [canvas.get_col_width()]
            finally:
                canvas.set_pos(saved)
            return {
                "ok": True,
                "command": "get_col_width",
                "table": table,
                "column": column,
                "unit": "mm",
                "width_mm": widths[0] if len(widths) == 1 else None,
                "widths_mm": widths,
            }

    def set_row_height(
        self,
        height: float,
        table: int | None = None,
        row: int | None = None,
    ) -> dict[str, Any]:
        if height <= 0 or height > 500:
            raise UsageError("행 높이는 0보다 크고 500mm 이하여야 합니다.")
        if row is not None and row < 1:
            raise UsageError("--row 는 1 이상의 행 번호여야 합니다.")
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            if table is not None:
                if table < 0:
                    raise UsageError("--table 은 0 이상의 표 번호여야 합니다.")
                canvas.get_into_nth_table(table)
            if row is not None:
                representatives = canvas.table_row_addresses()
                if row - 1 not in representatives:
                    raise UsageError(
                        f"{row}행은 병합 구조 때문에 높이를 조절할 셀을 찾지 못했습니다."
                    )
                canvas.goto_addr(representatives[row - 1])
            canvas.set_row_height_current(height)
            self._record_undo("set_row_height", 1)
            return {
                "ok": True,
                "command": "set_row_height",
                "table": table,
                "row": row,
                "height_mm": height,
                "undo_units": 1,
                "hangul_actions": 1,
            }

    def get_row_height(
        self,
        table: int | None = None,
        row: int | None = None,
    ) -> dict[str, Any]:
        if row is not None and row < 1:
            raise UsageError("--row 는 1 이상의 행 번호여야 합니다.")
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            if table is not None:
                if table < 0:
                    raise UsageError("--table 은 0 이상의 표 번호여야 합니다.")
                canvas.get_into_nth_table(table)
            saved = canvas.get_pos()
            try:
                if row is not None:
                    representatives = canvas.table_row_addresses()
                    if row - 1 not in representatives:
                        raise UsageError(
                            f"{row}행은 병합 구조 때문에 높이를 읽을 셀을 찾지 못했습니다."
                        )
                    canvas.goto_addr(representatives[row - 1])
                height = canvas.get_row_height()
            finally:
                canvas.set_pos(saved)
            return {
                "ok": True,
                "command": "get_row_height",
                "table": table,
                "row": row,
                "unit": "mm",
                "height_mm": height,
            }

    def merge_cells(
        self,
        cell_range: str,
        table: int | None = None,
    ) -> dict[str, Any]:
        start, end = _range_bounds(cell_range)
        if start == end:
            raise UsageError("merge_cells에는 두 칸 이상의 범위를 지정하세요.")
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            if table is not None:
                if table < 0:
                    raise UsageError("--table 은 0 이상의 표 번호여야 합니다.")
                canvas.get_into_nth_table(table)
            canvas.merge_cells(start, end)
            self._record_undo("merge_cells", 1)
            return {
                "ok": True,
                "command": "merge_cells",
                "table": table,
                "range": cell_range.upper(),
                "undo_units": 1,
                "hangul_actions": 1,
            }

    def set_valign(
        self,
        align: str,
        table: int | None = None,
        cell_range: str = "",
    ) -> dict[str, Any]:
        key = (align or "").strip().lower()
        if key not in {"top", "center", "bottom"}:
            raise UsageError("세로 정렬은 top, center, bottom 중 하나여야 합니다.")
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            addresses = self._cell_targets(canvas, table, cell_range)
            actions = 0
            vert_align = {"top": 0, "center": 1, "bottom": 2}[key]
            try:
                if addresses is None:
                    canvas.set_valign_current(key)
                    actions = 1
                else:
                    for addr in addresses:
                        canvas.goto_addr(addr)
                        vert_align = canvas.set_valign_current(key)
                        actions += 1
            except Exception:
                if actions:
                    self._record_undo("set_valign", actions)
                raise
            self._record_undo("set_valign", actions)
            return {
                "ok": True,
                "command": "set_valign",
                "table": table,
                "range": cell_range.upper(),
                "align": key,
                "vert_align": vert_align,
                "undo_units": 1,
                "hangul_actions": actions,
            }

    def set_cell_border(
        self,
        sides: str = "all",
        line_type: str = "Solid",
        width: str = "0.12mm",
        color: str = "#000000",
        table: int | None = None,
        cell_range: str = "",
    ) -> dict[str, Any]:
        parsed_sides = _normalize_border_sides(sides)
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            addresses = self._cell_targets(canvas, table, cell_range)
            actions = 0
            try:
                if addresses is None:
                    canvas.set_cell_border_current(
                        sides=parsed_sides,
                        line_type=line_type,
                        width=width,
                        color=color,
                    )
                    actions = 1
                else:
                    for addr in addresses:
                        canvas.goto_addr(addr)
                        canvas.set_cell_border_current(
                            sides=parsed_sides,
                            line_type=line_type,
                            width=width,
                            color=color,
                        )
                        actions += 1
            except Exception:
                if actions:
                    self._record_undo("set_cell_border", actions)
                raise
            self._record_undo("set_cell_border", actions)
            return {
                "ok": True,
                "command": "set_cell_border",
                "table": table,
                "range": cell_range.upper(),
                "sides": parsed_sides,
                "line_type": line_type,
                "width": width,
                "color": color,
                "undo_units": 1,
                "hangul_actions": actions,
            }

    def insert_image(
        self,
        path: str = "",
        table: int | None = None,
        cell: str = "",
        size_option: int = 3,
        width_mm: float = 0.0,
        height_mm: float = 0.0,
    ) -> dict[str, Any]:
        """그림 파일을 본문이나 표 칸에 넣는다. 원본 그림 파일은 건드리지 않는다."""
        src = (path or "").strip().strip('"')
        if not src:
            raise UsageError("그림 파일 경로를 지정하세요.")
        target = Path(src).expanduser()
        if not target.is_file():
            raise UsageError(f"그림 파일을 찾을 수 없습니다: {target}")
        if size_option not in (0, 1, 2, 3):
            raise UsageError(
                "size_option 은 0(원본)/1(크기 지정)/2(셀 맞춤)/3(셀 맞춤·비율 유지) 중 하나입니다."
            )
        if size_option == 1 and not (width_mm > 0 and height_mm > 0):
            raise UsageError("size_option=1 이면 width_mm 과 height_mm 을 모두 지정해야 합니다.")
        full = str(target.resolve())
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            if table is not None:
                canvas.get_into_nth_table(table)
            if cell:
                canvas.goto_addr(cell)
            in_cell = canvas.is_cell()
            if size_option in (2, 3) and not in_cell:
                raise UsageError(
                    "size_option 2/3 은 표 칸 안에서만 쓸 수 있습니다. "
                    "--table 과 --cell 로 칸을 지정하거나 size_option 0/1 을 쓰세요."
                )
            canvas.insert_picture(
                full,
                size_option=size_option,
                width_mm=width_mm,
                height_mm=height_mm,
            )
            self._record_undo("insert_image", 1)
            return {
                "ok": True,
                "command": "insert_image",
                "path": full,
                "table": table,
                "cell": cell.strip().upper(),
                "in_cell": in_cell,
                "size_option": size_option,
                "width_mm": width_mm,
                "height_mm": height_mm,
                "embedded": True,
                "undo_units": 1,
            }

    def insert_text_box(
        self,
        text: str,
        width_mm: float,
        height_mm: float,
        fill: Any = None,
        line: Any = None,
        shadow: Any = None,
        text_shadow: Any = None,
        margin: Any = None,
        align: str = "center",
        position: Any = None,
        bold: bool | None = None,
        italic: bool | None = None,
        font: str = "",
        size: float | None = None,
        color: str = "",
    ) -> dict[str, Any]:
        """새 편집 가능한 글상자를 만든다.

        채우기·테두리·그림자는 COM 속성값이 아닌 이 모듈의 공개 구조화 사양으로
        받는다. 따라서 CLI와 MCP가 같은 검증·색상 정규화를 공유한다.
        """
        if not isinstance(text, str):
            raise UsageError("글상자 텍스트는 문자열이어야 합니다.")
        width = _normalize_dimension(width_mm, "width_mm")
        height = _normalize_dimension(height_mm, "height_mm")
        normalized_fill = _normalize_fill(fill, allow_empty=True)
        normalized_line = _normalize_line(line)
        normalized_shadow = _normalize_shadow(shadow, label="도형 그림자")
        normalized_text_shadow = _normalize_shadow(
            text_shadow, label="글자 그림자", supports_alpha=False
        )
        margins = _normalize_margin(margin)
        normalized_align = _normalize_align(align, default="center")
        normalized_position = _normalize_text_box_position(position)
        _validate_text_format(
            bold=bold,
            italic=italic,
            font=font,
            size=size,
            color=color,
        )
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            action_result = canvas.insert_text_box(
                text=text,
                width_mm=width,
                height_mm=height,
                fill=normalized_fill,
                line=normalized_line,
                shadow=normalized_shadow,
                text_shadow=normalized_text_shadow,
                margin=margins,
                align=normalized_align,
                position=normalized_position,
                bold=bold,
                italic=italic,
                font=font,
                size=size,
                color=_normalize_optional_color(color),
            )
            actions = _action_count(action_result)
            self._record_undo("insert_text_box", actions)
            return {
                "ok": True,
                "command": "insert_text_box",
                "text": text,
                "width_mm": width,
                "height_mm": height,
                "fill": normalized_fill,
                "line": normalized_line,
                "shadow": normalized_shadow,
                "text_shadow": normalized_text_shadow,
                "margin_mm": margins,
                "align": normalized_align,
                "position": normalized_position,
                "undo_units": 1,
                "hangul_actions": actions,
            }

    def set_cell_fill(
        self,
        fill: Any,
        table: int | None = None,
        cell_range: str = "",
    ) -> dict[str, Any]:
        """현재 셀·표 전체·명시 범위에 단색 또는 선형 그라데이션을 적용한다."""
        normalized_fill = _normalize_fill(fill, allow_empty=False)
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            addresses = self._cell_targets(canvas, table, cell_range)
            actions = 0
            try:
                if addresses is None:
                    action_result = canvas.set_cell_fill(fill=normalized_fill)
                    actions += _action_count(action_result)
                else:
                    for addr in addresses:
                        canvas.goto_addr(addr)
                        action_result = canvas.set_cell_fill(fill=normalized_fill)
                        actions += _action_count(action_result)
            except Exception:
                if actions:
                    self._record_undo("set_cell_fill", actions)
                raise
            self._record_undo("set_cell_fill", actions)
            return {
                "ok": True,
                "command": "set_cell_fill",
                "table": table,
                "range": cell_range.upper(),
                "fill": normalized_fill,
                "undo_units": 1,
                "hangul_actions": actions,
            }

    def insert_chart(
        self,
        table: int | None = None,
        cell_range: str = "",
        chart_type: str = "line",
        chart_index: int = 0,
        no_dialog: bool = True,
    ) -> dict[str, Any]:
        key = (chart_type or "").strip().lower()
        if key not in CHART_GROUPS:
            raise UsageError(
                f"차트 종류는 {'/'.join(CHART_GROUPS)} 중 하나여야 합니다: {chart_type}"
            )
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            if table is not None:
                canvas.get_into_nth_table(table)
            elif not canvas.is_cell():
                raise UsageError(
                    "차트 데이터 표를 지정하세요: --table N 을 주거나 "
                    "한/글에서 캐럿을 데이터 표 안에 두세요."
                )
            if cell_range:
                start, end = _range_bounds(cell_range)
                canvas.select_cell_range(start, end)
            else:
                canvas.select_all_cells()
            canvas.insert_chart(
                chart_group=CHART_GROUPS[key],
                chart_index=chart_index,
                dialog_disable=bool(no_dialog),
            )
            self._record_undo("insert_chart", 1)
            return {
                "ok": True,
                "command": "insert_chart",
                "chart_type": key,
                "chart_group": CHART_GROUPS[key],
                "chart_index": chart_index,
                "dialog_disabled": bool(no_dialog),
                "native": True,  # 한/글 입력>차트 개체이며 그림(PNG)이 아님
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
            # Undo 단위: 셀 하나 = SelectAll(기록 없음) + InsertText 로 보고 1로 센다.
            # 선택 교체가 삭제+삽입 2단위로 기록되는지는 실기(한글 2022) 미측정 —
            # 과대 기록하면 undo 가 사용자 편집까지 삼키므로 보수적으로(적게) 기록한다.
            # 실제가 2단위라면 undo 후 일부 셀이 남을 수 있다(안전한 방향의 오차).
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

    def exit_table(self) -> dict[str, Any]:
        """현재 표의 마지막 셀에서 일반 본문으로 커서를 이동한다.

        문서 내용을 바꾸지 않는 이동 명령이므로 Undo 이력은 기록하지 않는다.
        한/글 어댑터가 MoveRight 뒤의 셀 상태까지 검증한다.
        """
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            canvas.exit_table()
            return {
                "ok": True,
                "command": "exit_table",
                "left_table": True,
                "undo_units": 0,
            }

    def set_table_position(self, table: int, position: Any) -> dict[str, Any]:
        """표의 글자처럼 취급 여부·떠 있는 위치·본문 배치를 설정한다.

        표 내부 텍스트를 그림으로 바꾸지 않고 ``TablePropertyDialog``의 네이티브
        표 개체 속성을 사용한다. 떠 있는 표는 현재 커서를 보존하므로, 공개
        ``exit_table`` 뒤에 호출해도 다음 본문 흐름을 바꾸지 않는다.
        """
        if isinstance(table, bool) or not isinstance(table, int) or table < 0:
            raise UsageError("table 은 0 이상의 표 번호여야 합니다.")
        normalized = _normalize_table_position(position)
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            action_result = canvas.set_table_position(table=table, position=normalized)
            actions = _action_count(action_result)
            self._record_undo("set_table_position", actions)
            return {
                "ok": True,
                "command": "set_table_position",
                "table": table,
                "position": normalized,
                "undo_units": 1,
                "hangul_actions": actions,
            }

    def set_table_properties(
        self,
        table: int,
        page_break: str = "cell",
        repeat_header: bool = True,
        cell_spacing_mm: float = 0.0,
    ) -> dict[str, Any]:
        """표의 페이지 경계 나눔·제목 행 반복·셀 간격을 네이티브로 설정한다."""
        if isinstance(table, bool) or not isinstance(table, int) or table < 0:
            raise UsageError("table 은 0 이상의 표 번호여야 합니다.")
        normalized = _normalize_table_properties(
            page_break=page_break,
            repeat_header=repeat_header,
            cell_spacing_mm=cell_spacing_mm,
        )
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            action_result = canvas.set_table_properties(table=table, **normalized)
            actions = _action_count(action_result)
            self._record_undo("set_table_properties", actions)
            return {
                "ok": True,
                "command": "set_table_properties",
                "table": table,
                **normalized,
                "undo_units": 1,
                "hangul_actions": actions,
            }

    def layout_review(
        self,
        table: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """표 줄바꿈·행 높이·본문 폭·쪽 수를 검토하고 기본적으로 바로 고친다."""
        if table is not None and table < 0:
            raise UsageError("--table 은 0 이상의 표 번호여야 합니다.")
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            dialog_check = getattr(canvas, "assert_no_dialog", None)
            if dialog_check:
                dialog_check()
            count = canvas.table_count()
            if table is not None and table >= count:
                raise HangulCommandError(
                    f"{table}번 표를 찾지 못했습니다. 문서의 표는 {count}개입니다."
                )
            targets = [table] if table is not None else list(range(count))
            before_pages = canvas.doc_info().page_count
            saved_pos = canvas.get_pos()
            saved_sel = canvas.selection_range()
            table_results: list[dict[str, Any]] = []
            actions = 0
            try:
                for index in targets:
                    measured = canvas.inspect_table_layout(index)
                    plan = plan_table_layout(measured)
                    if not dry_run and plan["column_changes"]:
                        set_one_column = getattr(canvas, "set_table_column_width", None)
                        if set_one_column:
                            for change in plan["column_changes"]:
                                col = int(change["column_index"])
                                result = set_one_column(
                                    index,
                                    col,
                                    float(plan["target_column_widths_mm"][col]),
                                )
                                actions += int(result if result is not None else 1)
                        else:
                            result = canvas.set_table_column_widths(
                                index, plan["target_column_widths_mm"]
                            )
                            actions += int(
                                result
                                if result is not None
                                else len(plan["target_column_widths_mm"])
                            )
                        # 열 변경 뒤 실제 조판 줄 수로 행 높이를 다시 계산한다.
                        after_width = canvas.inspect_table_layout(index)
                        plan["width_after_mm"] = round(
                            float(after_width["table_width_mm"]), 2
                        )
                        actual_widths = after_width.get("column_widths_mm", [])
                        for change in plan["column_changes"]:
                            col = int(change["column_index"])
                            if col < len(actual_widths):
                                change["actual_to_mm"] = round(
                                    float(actual_widths[col]), 2
                                )
                        row_plan = plan_table_layout(after_width)
                        plan["row_changes"] = row_plan["row_changes"]
                        plan["warnings"].extend(row_plan["warnings"])
                    else:
                        plan["width_after_mm"] = plan["width_before_mm"]
                    if not dry_run:
                        for change in plan["row_changes"]:
                            result = canvas.set_table_row_height(
                                index,
                                int(change["row_index"]),
                                float(change["to_mm"]),
                            )
                            actions += int(result if result is not None else 1)
                    plan["applied"] = not dry_run
                    table_results.append(plan)
            except Exception:
                # 앞선 열/행 액션이 성공한 뒤 다음 액션이 실패해도 실제 편집분은
                # hwpctl undo 스택에서 잃지 않는다.
                if actions:
                    self._record_undo("layout_review", actions)
                raise
            finally:
                canvas.set_pos(saved_pos)
                if saved_sel:
                    canvas.restore_selection(saved_sel)

            after_pages = canvas.doc_info().page_count
            warnings = [
                warning
                for result in table_results
                for warning in result.get("warnings", [])
            ]
            if after_pages > before_pages:
                if before_pages == 1:
                    warnings.append(
                        f"레이아웃 검토 뒤 문서가 1쪽에서 {after_pages}쪽으로 늘었습니다. "
                        "내용은 자동으로 지우지 않았습니다."
                    )
                else:
                    warnings.append(
                        f"레이아웃 검토 뒤 문서가 {before_pages}쪽에서 "
                        f"{after_pages}쪽으로 늘었습니다. 내용은 자동으로 지우지 않았습니다."
                    )
            if actions:
                self._record_undo("layout_review", actions)
            return {
                "ok": True,
                "command": "layout_review",
                "table": table,
                "dry_run": bool(dry_run),
                "tables_reviewed": len(targets),
                "tables": table_results,
                "page_count": {
                    "before": before_pages,
                    "after": after_pages,
                    "changed": before_pages != after_pages,
                },
                "warnings": list(dict.fromkeys(warnings)),
                "undo_units": 1 if actions else 0,
                "hangul_actions": actions,
                "autosave": False,
            }

    def set_format(
        self,
        bold: bool | None = None,
        italic: bool | None = None,
        font: str = "",
        size: float | None = None,
        align: str = "",
        color: str = "",
        fill: Any = None,
        text_shadow: Any = None,
        table: int | None = None,
        row: int | None = None,
        cell_range: str = "",
    ) -> dict[str, Any]:
        has_text_shadow = text_shadow is not None and text_shadow != ""
        normalized_text_shadow = (
            _normalize_shadow(text_shadow, label="글자 그림자", supports_alpha=False)
            if has_text_shadow
            else None
        )
        has_font = (
            any(x is not None for x in (bold, italic, size))
            or bool(font)
            or bool(color)
            or has_text_shadow
        )
        has_fill = fill is not None and fill != ""
        normalized_fill = _normalize_fill(fill, allow_empty=True) if has_fill else None
        normalized_align = _normalize_align(align) if align else ""
        _validate_text_format(
            bold=bold,
            italic=italic,
            font=font,
            size=size,
            color=color,
        )
        if not (has_fill or has_font or normalized_align):
            raise UsageError("적용할 서식이 없습니다.")

        def apply_font() -> None:
            font_kwargs: dict[str, Any] = {
                "bold": bold,
                "italic": italic,
                "face": font,
                "height_pt": size,
                "text_color": _normalize_optional_color(color),
            }
            if has_text_shadow:
                font_kwargs["text_shadow"] = normalized_text_shadow
            canvas.set_font(**font_kwargs)

        def apply_fill() -> None:
            assert normalized_fill is not None
            # set_format 의 기존 단색 fill 경로는 이전 public API와 실제 한/글
            # 호출 방식을 유지한다. 그라데이션은 새 공개 set_cell_fill 경로를 쓴다.
            if normalized_fill["type"] == "solid":
                canvas.cell_fill(normalized_fill["color"])
            else:
                canvas.set_cell_fill(fill=normalized_fill)

        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            steps = 0
            if table is not None:
                canvas.get_into_nth_table(table)
            if cell_range:
                # 요청한 칸에만 적용한다. (과거: 한 행 범위는 행 전체로 확대,
                # 여러 행 범위는 첫 칸에만 조용히 적용되던 버그)
                if row is not None:
                    raise UsageError("--range 와 --row 는 함께 쓸 수 없습니다.")
                if not canvas.is_cell():
                    raise UsageError(
                        "--range 는 캐럿이 표 안에 있거나 --table 과 함께 써야 합니다."
                    )
                for addr in expand_range(cell_range):
                    canvas.goto_addr(addr)
                    if has_fill:
                        apply_fill()
                        steps += 1
                    if has_font:
                        canvas.select_cell_text()
                        apply_font()
                        steps += 1
                    if normalized_align:
                        canvas.set_align(normalized_align)
                        steps += 1
                self._record_undo("set_format", max(1, steps))
                return {"ok": True, "command": "set_format", "undo_units": 1}
            if row is not None:
                if table is None:
                    raise UsageError("--row 는 --table 과 함께 쓰세요.")
                canvas.goto_addr(a1(row - 1, 0))
                canvas.select_row()
            if has_fill:
                apply_fill()
                steps += 1
            if has_font:
                apply_font()
                steps += 1
            if normalized_align:
                canvas.set_align(normalized_align)
                steps += 1
            self._record_undo("set_format", max(1, steps))
            return {"ok": True, "command": "set_format", "undo_units": 1}

    def set_style(self, style: str | int) -> dict[str, Any]:
        if isinstance(style, str) and not style.strip():
            raise UsageError("적용할 스타일 이름이 비어 있습니다.")
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            canvas.set_style(style)
            self._record_undo("set_style", 1)
            return {
                "ok": True,
                "command": "set_style",
                "style": style,
                "undo_units": 1,
                "hangul_actions": 1,
            }

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
            # 스택이 비었는데 무조건 1회 undo 하면 사용자의 수동 편집을 삼킨다 — 거부.
            # (수동 편집 "감지"는 자동화 API 에 문서 리비전 카운터가 없어 신뢰성 있게
            # 구현할 수 없다. hwpctl 명령 사이에 사용자가 직접 편집했다면 이 undo 는
            # 그 편집부터 되돌린다는 한계를 README 에 명시한다.)
            if not state.undo_stack:
                raise HangulCommandError(
                    "hwpctl 이 기록한 편집이 없어 undo 를 실행하지 않습니다. "
                    "수동 편집을 되돌리려면 한/글에서 직접 Ctrl+Z 를 누르세요."
                )
            steps = max(1, int(state.undo_stack.pop()))
            for _ in range(steps):
                canvas.undo_once()
            state.last_command = "undo"
            save_state(state)
            return {"ok": True, "command": "undo", "hangul_undo_steps": steps}

    def page(
        self,
        goto: int | None = None,
        break_page: bool = False,
    ) -> dict[str, Any]:
        if goto is not None and break_page:
            raise UsageError("--goto 와 --break 는 함께 쓸 수 없습니다.")
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            if break_page:
                canvas.break_page()
                self._record_undo("page", 1)
            elif goto is not None:
                canvas.goto_page(goto)
            info = canvas.doc_info()
            page = info.page
            text = canvas.get_page_text(page)
            return {
                "ok": True,
                "command": "page",
                "page": page,
                "page_count": info.page_count,
                "text": text,
                "break": bool(break_page),
                "undo_units": 1 if break_page else 0,
            }

    def set_page_number(
        self,
        position: str = "bottom_center",
        separator: str = "-",
    ) -> dict[str, Any]:
        """현재 구역의 쪽 번호 위치와 양쪽 구분 문자를 설정한다.

        예를 들어 ``position='bottom_center', separator='-'`` 는 한/글의
        ``- 1 -`` 모양을 만든다. 쪽 번호 자체를 본문 문자열로 평면화하지 않고
        네이티브 PageNumPos 개체를 사용한다.
        """
        normalized_position = _normalize_page_number_position(position)
        normalized_separator = _normalize_page_number_separator(separator)
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            canvas.set_page_number(
                position=normalized_position,
                separator=normalized_separator,
            )
            self._record_undo("set_page_number", 1)
            return {
                "ok": True,
                "command": "set_page_number",
                "position": normalized_position,
                "separator": normalized_separator,
                "format": "digit",
                "undo_units": 1,
                "hangul_actions": 1,
            }

    def set_page_visibility(
        self,
        hide_header: bool = False,
        hide_footer: bool = False,
        hide_master_page: bool = False,
        hide_border: bool = False,
        hide_fill: bool = False,
        hide_page_num: bool = False,
    ) -> dict[str, Any]:
        """현재 쪽에서 머리말·꼬리말·쪽 번호 등 표시 요소를 감춘다.

        한/글의 ``PageHiding`` 네이티브 제어를 삽입한다. 각 인자는 명시적
        boolean 이며, 생략한 항목은 감추지 않는다. 따라서 표지만 쪽 번호를
        감추는 경우 ``hide_page_num=True`` 로 재현할 수 있다.
        """
        visibility = _normalize_page_visibility(
            hide_header=hide_header,
            hide_footer=hide_footer,
            hide_master_page=hide_master_page,
            hide_border=hide_border,
            hide_fill=hide_fill,
            hide_page_num=hide_page_num,
        )
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            canvas.set_page_visibility(**visibility)
            self._record_undo("set_page_visibility", 1)
            return {
                "ok": True,
                "command": "set_page_visibility",
                **visibility,
                "undo_units": 1,
                "hangul_actions": 1,
            }

    def restart_page_number(self, number: int = 1) -> dict[str, Any]:
        """현재 캐럿 위치부터 네이티브 쪽 번호를 ``number``로 다시 시작한다."""
        normalized_number = _normalize_page_number_restart(number)
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            canvas.restart_page_number(number=normalized_number)
            self._record_undo("restart_page_number", 1)
            return {
                "ok": True,
                "command": "restart_page_number",
                "number": normalized_number,
                "undo_units": 1,
                "hangul_actions": 1,
            }

    def set_pagedef(
        self,
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
        numeric = {
            "paper_width": paper_width,
            "paper_height": paper_height,
            "left": left,
            "right": right,
            "top": top,
            "bottom": bottom,
            "header": header,
            "footer": footer,
            "gutter": gutter,
        }
        if all(value is None for value in numeric.values()) and landscape is None:
            raise UsageError("바꿀 용지 크기, 여백 또는 가로/세로 방향을 지정하세요.")
        for name, value in numeric.items():
            if value is not None and value < 0:
                raise UsageError(f"{name} 값은 0 이상이어야 합니다.")
        for name in ("paper_width", "paper_height"):
            value = numeric[name]
            if value is not None and value <= 0:
                raise UsageError("용지 폭과 길이는 0보다 커야 합니다.")
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            canvas.set_pagedef(
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
            self._record_undo("set_pagedef", 1)
            return {
                "ok": True,
                "command": "set_pagedef",
                **numeric,
                "landscape": landscape,
                "apply": apply,
                "undo_units": 1,
                "hangul_actions": 1,
            }

    def save_as(
        self, path: str, format: str = "", overwrite: bool = False
    ) -> dict[str, Any]:
        dest = Path(path).expanduser()
        with SingleWriterLock(timeout=self.lock_timeout):
            canvas = self._connect()
            info = canvas.doc_info()
            # save_as 는 "새 경로" 계약을 지킨다. 원본 경로라면 --overwrite 를
            # 주더라도 save --overwrite 를 써야 한다. 그렇지 않으면 원본과 다른
            # 기존 파일도 SaveAs 대화상자 없이 조용히 덮어쓸 수 있다.
            if info.path and _same_file(info.path, dest):
                raise DestructiveGuardError(
                    "save_as 는 원본을 덮어쓰지 않습니다. "
                    "같은 경로에 저장하려면 save --overwrite 를 쓰세요."
                )
            existed = dest.exists()
            if existed and not overwrite:
                raise DestructiveGuardError(
                    "save_as 대상 파일이 이미 있습니다. 덮어쓰려면 "
                    "--overwrite (MCP: overwrite=true) 를 명시하세요."
                )
            # 파괴 가드를 모두 통과한 경우에만 디렉터리를 만든다. 거부된
            # save_as 요청이 빈 디렉터리를 남기지 않게 한다.
            dest.parent.mkdir(parents=True, exist_ok=True)
            canvas.save_as(str(dest), fmt=format)
            return {
                "ok": True,
                "command": "save_as",
                "path": str(dest),
                "original_path": info.path,
                "overwritten": existed,
                "autosave": False,
            }

    def save(self, overwrite: bool = False) -> dict[str, Any]:
        if not overwrite:
            raise DestructiveGuardError(
                "원본 파일을 덮어쓰려면 --overwrite (MCP: overwrite=true) 가 필요합니다. "
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
                "문서를 닫으려면 --force (MCP: force=true) 가 필요합니다. "
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

    def close_all(self, force: bool = False) -> dict[str, Any]:
        """모든 실행 중 한/글 문서를 문서 단위로 닫는다. force=true 필수."""
        if not force:
            raise DestructiveGuardError(
                "모든 한/글 문서를 닫으려면 --force (MCP: force=true) 가 필요합니다. "
                "저장하지 않은 다른 문서도 사라집니다."
            )
        with SingleWriterLock(timeout=self.lock_timeout):
            result = self.document_closer()
            remaining = self.document_lister()
            state = load_state()
            state.undo_stack = []
            state.last_command = "close_all"
            state.target_hwnd = 0
            save_state(state)
            failures = list(result.get("failures", []))
            return {
                "ok": not failures and not remaining,
                "command": "close_all",
                "closed": list(result.get("closed", [])),
                "closed_count": len(result.get("closed", [])),
                "closed_instances": list(result.get("closed_instances", [])),
                "failures": failures,
                "remaining": remaining,
                "remaining_count": len(remaining),
            }

    def _record_undo(self, command: str, hangul_steps: int) -> None:
        state = load_state()
        state.undo_stack.append(max(1, hangul_steps))
        state.last_command = command
        save_state(state)

    def _cell_targets(
        self,
        canvas: HangulCanvas,
        table: int | None,
        cell_range: str,
    ) -> list[str] | None:
        if table is not None:
            if table < 0:
                raise UsageError("--table 은 0 이상의 표 번호여야 합니다.")
            canvas.get_into_nth_table(table)
        if cell_range:
            if not canvas.is_cell():
                raise UsageError("--range 는 캐럿이 표 안에 있거나 --table 과 함께 쓰세요.")
            return expand_range(cell_range)
        if table is not None:
            return canvas.table_cell_addresses()
        if not canvas.is_cell():
            raise HangulCommandError("캐럿이 표 셀 안에 있지 않습니다.")
        return None


def suggested_save_as_path(original: str) -> str:
    if not original:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return str(Path.home() / "Documents" / f"hwpctl-{stamp}.hwpx")
    src = Path(original)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return str(src.with_name(f"{src.stem}-edited-{stamp}{src.suffix or '.hwpx'}"))


def _normalize_cell_address(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UsageError("cell 은 A1 형식의 표 셀 주소여야 합니다.")
    address = value.strip().upper()
    try:
        parse_a1(address)
    except Exception as exc:
        raise UsageError("cell 은 A1 형식의 표 셀 주소여야 합니다.") from exc
    return address


def _normalize_paragraph_spec(
    *,
    text: Any = "",
    runs: Any = None,
    paragraph: Any = None,
    page_break_before: Any = False,
) -> dict[str, Any]:
    if text is None or not isinstance(text, str):
        raise UsageError("문단 text는 문자열이어야 합니다.")
    if not isinstance(page_break_before, bool):
        raise UsageError("page_break_before 값은 true 또는 false여야 합니다.")
    return {
        "runs": _normalize_text_runs(text, runs),
        "paragraph": _normalize_paragraph_layout(paragraph),
        "page_break_before": page_break_before,
    }


def _normalize_cell_paragraphs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        raise UsageError("paragraphs 는 문단 객체의 배열이어야 합니다.")
    specs: list[dict[str, Any]] = []
    allowed = {"text", "runs", "paragraph", "page_break_before"}
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, dict):
            raise UsageError(f"paragraphs[{index}] 는 문단 객체여야 합니다.")
        unknown = set(raw) - allowed
        if unknown:
            raise UsageError(
                f"paragraphs[{index}] 에 지원하지 않는 필드가 있습니다: "
                f"{', '.join(sorted(str(key) for key in unknown))}"
            )
        spec = _normalize_paragraph_spec(
            text=raw.get("text", ""),
            runs=raw.get("runs"),
            paragraph=raw.get("paragraph"),
            page_break_before=raw.get("page_break_before", False),
        )
        if spec["page_break_before"]:
            raise UsageError("표 셀 문단에는 page_break_before 를 지정할 수 없습니다.")
        specs.append(spec)
    return specs


def _normalize_paragraph_layout(value: Any) -> dict[str, Any]:
    """공개 mm/% 문단 사양을 COM 독립 구조로 정규화한다."""
    if value is None or value == "":
        return {}
    if not isinstance(value, dict):
        raise UsageError("paragraph 는 문단 서식 객체여야 합니다.")
    allowed = {
        "align",
        "left_margin_mm",
        "right_margin_mm",
        "first_line_indent_mm",
        "before_spacing_mm",
        "after_spacing_mm",
        "line_spacing_percent",
        "break_latin_word",
        "break_non_latin_word",
    }
    unknown = set(value) - allowed
    if unknown:
        raise UsageError(
            "paragraph 에 지원하지 않는 필드가 있습니다: "
            + ", ".join(sorted(str(key) for key in unknown))
        )
    out: dict[str, Any] = {}
    if "align" in value:
        out["align"] = _normalize_align(value["align"])
    for key in (
        "left_margin_mm",
        "right_margin_mm",
        "before_spacing_mm",
        "after_spacing_mm",
    ):
        if key not in value:
            continue
        number = _finite_number(value[key], key)
        if not 0 <= number <= 500:
            raise UsageError(f"{key} 값은 0~500mm 범위여야 합니다.")
        out[key] = number
    if "first_line_indent_mm" in value:
        number = _finite_number(value["first_line_indent_mm"], "first_line_indent_mm")
        if not -500 <= number <= 500:
            raise UsageError("first_line_indent_mm 값은 -500~500mm 범위여야 합니다.")
        out["first_line_indent_mm"] = number
    if "line_spacing_percent" in value:
        number = _finite_number(value["line_spacing_percent"], "line_spacing_percent")
        if not 50 <= number <= 500:
            raise UsageError("line_spacing_percent 값은 50~500 범위여야 합니다.")
        out["line_spacing_percent"] = number
    for key in ("break_latin_word", "break_non_latin_word"):
        if key in value:
            out[key] = _normalize_word_break(value[key], key)
    return out


def _normalize_word_break(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise UsageError(f"{label} 값은 keep_word 또는 break_word여야 합니다.")
    normalized = value.strip().lower().replace("-", "_")
    if normalized not in {"keep_word", "break_word"}:
        raise UsageError(f"{label} 값은 keep_word 또는 break_word여야 합니다.")
    return normalized


def _normalize_text_runs(text: str, value: Any) -> list[dict[str, Any]]:
    if value is None:
        return [_normalize_text_run({"text": text}, 1)]
    if text:
        raise UsageError("text와 runs는 함께 지정할 수 없습니다.")
    if not isinstance(value, (list, tuple)):
        raise UsageError("runs 는 글자 서식 객체의 배열이어야 합니다.")
    return [_normalize_text_run(item, index) for index, item in enumerate(value, start=1)]


def _normalize_text_run(value: Any, index: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise UsageError(f"runs[{index}] 은 글자 서식 객체여야 합니다.")
    allowed = {
        "text",
        "bold",
        "italic",
        "superscript",
        "subscript",
        "underline",
        "strikeout",
        "kerning",
        "font",
        "size",
        "color",
        "text_shadow",
        "letter_spacing_percent",
        "width_scale_percent",
    }
    unknown = set(value) - allowed
    if unknown:
        raise UsageError(
            f"runs[{index}] 에 지원하지 않는 필드가 있습니다: "
            f"{', '.join(sorted(str(key) for key in unknown))}"
        )
    text = value.get("text", "")
    if not isinstance(text, str):
        raise UsageError(f"runs[{index}].text 는 문자열이어야 합니다.")
    bold = value.get("bold")
    italic = value.get("italic")
    superscript = _normalize_optional_bool(value.get("superscript"), f"runs[{index}].superscript")
    subscript = _normalize_optional_bool(value.get("subscript"), f"runs[{index}].subscript")
    if superscript and subscript:
        raise UsageError(f"runs[{index}]에서 superscript와 subscript를 함께 true로 지정할 수 없습니다.")
    underline = _normalize_text_decoration(value.get("underline"), f"runs[{index}].underline", kind="underline")
    strikeout = _normalize_text_decoration(value.get("strikeout"), f"runs[{index}].strikeout", kind="strikeout")
    kerning = _normalize_optional_bool(value.get("kerning"), f"runs[{index}].kerning")
    font = value.get("font", "")
    if font is None:
        font = ""
    size = value.get("size")
    color = value.get("color", "")
    _validate_text_format(
        bold=bold,
        italic=italic,
        font=font,
        size=size,
        color=color,
    )
    shadow_raw = value.get("text_shadow")
    text_shadow = (
        _normalize_shadow(shadow_raw, label="글자 그림자", supports_alpha=False)
        if shadow_raw is not None and shadow_raw != ""
        else None
    )
    return {
        "text": text,
        "bold": bold,
        "italic": italic,
        "superscript": superscript,
        "subscript": subscript,
        "underline": underline,
        "strikeout": strikeout,
        "kerning": kerning,
        "font": str(font).strip(),
        "size": float(size) if size is not None else None,
        "color": _normalize_optional_color(color),
        "text_shadow": text_shadow,
        "letter_spacing_percent": _normalize_character_percent(
            value.get("letter_spacing_percent"),
            "letter_spacing_percent",
            minimum=-50,
            maximum=50,
        ),
        "width_scale_percent": _normalize_character_percent(
            value.get("width_scale_percent"),
            "width_scale_percent",
            minimum=50,
            maximum=200,
        ),
    }


def _normalize_character_percent(
    value: Any,
    label: str,
    *,
    minimum: int,
    maximum: int,
) -> int | None:
    if value is None:
        return None
    number = _finite_number(value, label)
    if not number.is_integer():
        raise UsageError(f"{label} 값은 정수여야 합니다.")
    integer = int(number)
    if not minimum <= integer <= maximum:
        raise UsageError(f"{label} 값은 {minimum}~{maximum} 범위여야 합니다.")
    return integer


def _normalize_optional_bool(value: Any, label: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise UsageError(f"{label} 값은 true 또는 false여야 합니다.")
    return value


def _normalize_text_decoration(
    value: Any,
    label: str,
    *,
    kind: str,
) -> dict[str, Any] | None:
    """정확한 HCharShape 밑줄/취소선 사양을 보존할 공개 정규화기.

    기존 boolean 호출은 호환성을 위해 유지한다. 객체를 쓰면 source HWPML의
    위치/선 모양/색을 명시적으로 전달할 수 있어 엔진이 색을 조용히 버리지 않는다.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return {"enabled": value}
    if not isinstance(value, dict):
        raise UsageError(f"{label} 값은 true/false 또는 서식 객체여야 합니다.")
    allowed = {"enabled", "color", "type", "shape"}
    unknown = set(value) - allowed
    if unknown:
        raise UsageError(
            f"{label} 에 지원하지 않는 필드가 있습니다: "
            f"{', '.join(sorted(str(key) for key in unknown))}"
        )
    enabled = value.get("enabled", True)
    if not isinstance(enabled, bool):
        raise UsageError(f"{label}.enabled 값은 true 또는 false여야 합니다.")
    out: dict[str, Any] = {"enabled": enabled}
    if "color" in value:
        out["color"] = _canonical_color(value["color"], f"{label} 색")
    type_defaults = {"underline": "bottom", "strikeout": "continuous"}
    # 참조 문서에서 실제 관측된 한/글 2022 값만 먼저 공개한다. 미검증 변형을
    # 받아 default로 바꾸는 것보다 실행 전 거부하는 편이 재현 문서에 안전하다.
    allowed_types = {"underline": {"bottom"}, "strikeout": {"continuous"}}
    raw_type = value.get("type", type_defaults[kind])
    if not isinstance(raw_type, str):
        raise UsageError(f"{label}.type 값이 올바르지 않습니다.")
    normalized_type = raw_type.strip().lower().replace("-", "_")
    if normalized_type not in allowed_types[kind]:
        values = ", ".join(sorted(allowed_types[kind]))
        raise UsageError(f"{label}.type 은 {values} 중 하나여야 합니다.")
    out["type"] = normalized_type
    raw_shape = value.get("shape", "solid")
    if not isinstance(raw_shape, str):
        raise UsageError(f"{label}.shape 값이 올바르지 않습니다.")
    normalized_shape = raw_shape.strip().lower().replace("-", "_")
    allowed_shapes = {"solid"}
    if normalized_shape not in allowed_shapes:
        raise UsageError(
            f"{label}.shape 은 {', '.join(sorted(allowed_shapes))} 중 하나여야 합니다."
        )
    out["shape"] = normalized_shape
    return out


def _run_font_kwargs(run: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "bold",
        "italic",
        "superscript",
        "subscript",
        "underline",
        "strikeout",
        "kerning",
        "font",
        "size",
        "color",
        "text_shadow",
        "letter_spacing_percent",
        "width_scale_percent",
    )
    if not any(run.get(key) not in (None, "") for key in keys):
        return {}
    return {
        "bold": run["bold"],
        "italic": run["italic"],
        "superscript": run["superscript"],
        "subscript": run["subscript"],
        "underline": run["underline"],
        "strikeout": run["strikeout"],
        "kerning": run["kerning"],
        "face": run["font"],
        "height_pt": run["size"],
        "text_color": run["color"],
        "text_shadow": run["text_shadow"],
        "letter_spacing_percent": run["letter_spacing_percent"],
        "width_scale_percent": run["width_scale_percent"],
    }


def _normalize_page_number_position(value: Any) -> str:
    if not isinstance(value, str):
        raise UsageError("position 은 쪽 번호 위치 문자열이어야 합니다.")
    key = value.strip().lower().replace("-", "_")
    allowed = {
        "top_left",
        "top_center",
        "top_right",
        "bottom_left",
        "bottom_center",
        "bottom_right",
    }
    if key not in allowed:
        raise UsageError(
            "position 은 top_left, top_center, top_right, bottom_left, "
            "bottom_center, bottom_right 중 하나여야 합니다."
        )
    return key


def _normalize_page_number_separator(value: Any) -> str:
    if not isinstance(value, str):
        raise UsageError("separator 는 한 글자 또는 빈 문자열이어야 합니다.")
    if len(value) > 1:
        raise UsageError("separator 는 한 글자 또는 빈 문자열이어야 합니다.")
    return value


def _normalize_page_visibility(
    *,
    hide_header: Any,
    hide_footer: Any,
    hide_master_page: Any,
    hide_border: Any,
    hide_fill: Any,
    hide_page_num: Any,
) -> dict[str, bool]:
    values = {
        "hide_header": hide_header,
        "hide_footer": hide_footer,
        "hide_master_page": hide_master_page,
        "hide_border": hide_border,
        "hide_fill": hide_fill,
        "hide_page_num": hide_page_num,
    }
    for key, value in values.items():
        if not isinstance(value, bool):
            raise UsageError(f"{key} 값은 true 또는 false여야 합니다.")
    return values


def _normalize_page_number_restart(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise UsageError("number 는 1~999999 범위의 정수여야 합니다.")
    if not 1 <= value <= 999999:
        raise UsageError("number 는 1~999999 범위의 정수여야 합니다.")
    return value


def _normalize_table_properties(
    *,
    page_break: Any,
    repeat_header: Any,
    cell_spacing_mm: Any,
) -> dict[str, Any]:
    """표 속성의 공개 JSON 값을 한/글 독립 형식으로 엄격히 정규화한다.

    ``page_break``는 HWPML의 ``PageBreak``와 같은 의미지만 COM 열거형을
    노출하지 않는다. 셀 간격은 mm로 받고 실행 직전에만 HwpUnit으로 바꾼다.
    """
    if not isinstance(page_break, str):
        raise UsageError("page_break 는 none, table, cell 중 하나여야 합니다.")
    normalized_break = page_break.strip().lower().replace("-", "_")
    aliases = {
        "none": "none",
        "off": "none",
        "table": "table",
        "cell": "cell",
    }
    if normalized_break not in aliases:
        raise UsageError("page_break 는 none, table, cell 중 하나여야 합니다.")
    if not isinstance(repeat_header, bool):
        raise UsageError("repeat_header 값은 true 또는 false여야 합니다.")
    spacing = _finite_number(cell_spacing_mm, "cell_spacing_mm")
    if not 0 <= spacing <= 50:
        raise UsageError("cell_spacing_mm 값은 0~50mm 범위여야 합니다.")
    return {
        "page_break": aliases[normalized_break],
        "repeat_header": repeat_header,
        "cell_spacing_mm": spacing,
    }


def _normalize_table_position(value: Any) -> dict[str, Any]:
    """공개 표 위치 사양을 한/글 열거형과 독립된 JSON으로 정규화한다."""
    if not isinstance(value, dict):
        raise UsageError("position 은 표 위치 JSON 객체여야 합니다.")
    allowed = {
        "mode",
        "horizontal_relative_to",
        "vertical_relative_to",
        "horizontal_align",
        "vertical_align",
        "x_mm",
        "y_mm",
        "wrap",
        "flow_with_text",
        "allow_overlap",
        "outside_margin_mm",
        "affect_line_spacing",
    }
    unknown = set(value) - allowed
    if unknown:
        raise UsageError(
            "position 에 지원하지 않는 필드가 있습니다: "
            + ", ".join(sorted(str(key) for key in unknown))
        )
    raw_mode = value.get("mode", "inline")
    if not isinstance(raw_mode, str):
        raise UsageError("position.mode 는 inline 또는 floating 이어야 합니다.")
    mode = raw_mode.strip().lower()
    if mode not in {"inline", "floating"}:
        raise UsageError("position.mode 는 inline 또는 floating 이어야 합니다.")
    affect_line_spacing = value.get("affect_line_spacing", False)
    if not isinstance(affect_line_spacing, bool):
        raise UsageError("position.affect_line_spacing 값은 true 또는 false여야 합니다.")
    if mode == "inline":
        disallowed = set(value) - {"mode", "affect_line_spacing", "outside_margin_mm"}
        if disallowed:
            raise UsageError(
                "inline 표 위치에는 mode, affect_line_spacing, outside_margin_mm만 지정할 수 있습니다."
            )
        margins = _normalize_margin(value.get("outside_margin_mm", (0, 0, 0, 0)))
        assert margins is not None
        return {
            "mode": "inline",
            "affect_line_spacing": affect_line_spacing,
            "outside_margin_mm": list(margins),
        }

    required = ("x_mm", "y_mm", "wrap")
    missing = [key for key in required if key not in value]
    if missing:
        raise UsageError("floating 표 위치 필수값이 없습니다: " + ", ".join(missing))
    x_mm = _finite_number(value["x_mm"], "position.x_mm")
    y_mm = _finite_number(value["y_mm"], "position.y_mm")
    if not -500 <= x_mm <= 500 or not -500 <= y_mm <= 500:
        raise UsageError("position.x_mm/y_mm 값은 -500~500mm 범위여야 합니다.")
    horizontal_relative_to = _normalize_table_position_enum(
        value.get("horizontal_relative_to", "para"),
        "position.horizontal_relative_to",
        {"paper", "page", "column", "para"},
    )
    vertical_relative_to = _normalize_table_position_enum(
        value.get("vertical_relative_to", "para"),
        "position.vertical_relative_to",
        {"paper", "page", "para"},
    )
    horizontal_align = _normalize_table_position_enum(
        value.get("horizontal_align", "left"),
        "position.horizontal_align",
        {"left", "center", "right"},
    )
    vertical_align = _normalize_table_position_enum(
        value.get("vertical_align", "top"),
        "position.vertical_align",
        {"top", "center", "bottom"},
    )
    wrap = _normalize_table_position_enum(
        value["wrap"],
        "position.wrap",
        {"square", "top_and_bottom", "behind_text", "in_front_of_text"},
    )
    flow_with_text = value.get("flow_with_text", True)
    allow_overlap = value.get("allow_overlap", False)
    for key, bool_value in {
        "position.flow_with_text": flow_with_text,
        "position.allow_overlap": allow_overlap,
    }.items():
        if not isinstance(bool_value, bool):
            raise UsageError(f"{key} 값은 true 또는 false여야 합니다.")
    margins = _normalize_margin(value.get("outside_margin_mm", (0, 0, 0, 0)))
    assert margins is not None
    return {
        "mode": "floating",
        "horizontal_relative_to": horizontal_relative_to,
        "vertical_relative_to": vertical_relative_to,
        "horizontal_align": horizontal_align,
        "vertical_align": vertical_align,
        "x_mm": x_mm,
        "y_mm": y_mm,
        "wrap": wrap,
        "flow_with_text": flow_with_text,
        "allow_overlap": allow_overlap,
        "outside_margin_mm": list(margins),
    }


def _normalize_table_position_enum(value: Any, label: str, allowed: set[str]) -> str:
    if not isinstance(value, str):
        raise UsageError(f"{label} 값이 올바르지 않습니다.")
    normalized = value.strip().lower().replace("-", "_")
    if normalized not in allowed:
        raise UsageError(f"{label} 은 {', '.join(sorted(allowed))} 중 하나여야 합니다.")
    return normalized


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


def _normalize_margin(value: Any) -> tuple[float, float, float, float] | None:
    """create_table 의 cell_margin 입력을 (좌,우,상,하) mm 튜플로 정규화.

    허용: None/"none"/"off"/"" → 미적용, "3.5,2.0"(좌우,상하), "1,2,3,4", 단일 값,
    2/4개 시퀀스.
    """
    if value is None:
        return None
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in ("", "none", "off"):
            return None
        parts = [p.strip() for p in raw.split(",")]
        try:
            nums = [float(p) for p in parts]
        except ValueError as exc:
            raise UsageError(
                f"--cell-padding 형식이 잘못되었습니다: {value}. "
                "'3.5,2.0'(좌우,상하 mm) 또는 '좌,우,상,하' 로 지정하세요."
            ) from exc
    elif isinstance(value, (int, float)):
        nums = [float(value)]
    elif isinstance(value, (list, tuple)):
        try:
            nums = [float(v) for v in value]
        except (TypeError, ValueError) as exc:
            raise UsageError(f"셀 안 여백 값이 잘못되었습니다: {value}") from exc
    else:
        raise UsageError(f"셀 안 여백 값이 잘못되었습니다: {value}")
    if len(nums) == 1:
        left = right = top = bottom = nums[0]
    elif len(nums) == 2:
        left = right = nums[0]
        top = bottom = nums[1]
    elif len(nums) == 4:
        left, right, top, bottom = nums
    else:
        raise UsageError(
            "셀 안 여백은 1개(전체), 2개(좌우,상하), 4개(좌,우,상,하) 값만 허용합니다."
        )
    for v in (left, right, top, bottom):
        if v < 0 or v > 50:
            raise UsageError("셀 안 여백은 0~50mm 범위로 지정하세요.")
    return (left, right, top, bottom)


def _canonical_color(value: Any, label: str = "색") -> str:
    if not isinstance(value, str):
        raise UsageError(f"{label} 값은 색 이름 또는 #RRGGBB 문자열이어야 합니다.")
    red, green, blue = parse_color(value)
    return f"#{red:02X}{green:02X}{blue:02X}"


def _normalize_optional_color(value: str) -> str:
    return _canonical_color(value, "글자색") if value else ""


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise UsageError(f"{label} 값은 숫자여야 합니다.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise UsageError(f"{label} 값은 숫자여야 합니다.") from exc
    if not isfinite(number):
        raise UsageError(f"{label} 값은 유한한 숫자여야 합니다.")
    return number


def _normalize_dimension(value: Any, label: str) -> float:
    number = _finite_number(value, label)
    if not 0 < number <= 500:
        raise UsageError(f"{label} 값은 0보다 크고 500mm 이하여야 합니다.")
    return number


def _normalize_fill(value: Any, *, allow_empty: bool) -> dict[str, Any] | None:
    """공개 채우기 사양을 한/글 COM과 무관한 구조로 정규화한다."""
    if value is None or value == "":
        if allow_empty:
            return None
        raise UsageError("채우기(fill)를 지정하세요.")
    if isinstance(value, str):
        return {"type": "solid", "color": _canonical_color(value, "채우기 색")}
    if not isinstance(value, dict):
        raise UsageError("채우기는 색 문자열 또는 JSON 객체여야 합니다.")

    raw_type = str(value.get("type", value.get("kind", "solid"))).strip().lower()
    fill_type = {
        "solid": "solid",
        "linear_gradient": "linear_gradient",
        "linear-gradient": "linear_gradient",
        "linear": "linear_gradient",
        "gradient": "linear_gradient",
        "radial_gradient": "radial_gradient",
        "radial-gradient": "radial_gradient",
        "radial": "radial_gradient",
    }.get(raw_type)
    if fill_type is None:
        raise UsageError("채우기 type은 solid, linear_gradient 또는 radial_gradient 여야 합니다.")
    if fill_type == "solid":
        color = value.get("color")
        if color is None:
            raise UsageError("solid 채우기에는 color가 필요합니다.")
        return {"type": "solid", "color": _canonical_color(color, "채우기 색")}

    angle = _finite_number(value.get("angle", 0), "그라데이션 angle") % 360
    raw_stops = value.get("stops")
    if raw_stops is None:
        raw_stops = value.get("colors")
    if raw_stops is None:
        start_color = value.get("start_color")
        end_color = value.get("end_color")
        if start_color is not None and end_color is not None:
            raw_stops = [start_color, end_color]
    if not isinstance(raw_stops, (list, tuple)) or len(raw_stops) < 2:
        raise UsageError(
            f"{fill_type} 채우기에는 색 중지점 stops(2개 이상)가 필요합니다."
        )
    # 한/글 2022의 DrawFillAttr는 Color/IndexPos 배열을 10칸만 제공한다.
    # 공개 API가 그보다 많은 값을 받아 놓고 조용히 잘라내면 재현성이 깨지므로
    # COM 경계 전에 명확히 거부한다.
    if len(raw_stops) > 10:
        raise UsageError("그라데이션 중지점은 최대 10개까지 허용합니다.")

    uses_offsets = any(isinstance(stop, dict) and ("offset" in stop or "position" in stop) for stop in raw_stops)
    if uses_offsets and not all(
        isinstance(stop, dict) and ("offset" in stop or "position" in stop) for stop in raw_stops
    ):
        raise UsageError("그라데이션 중지점에는 offset을 모두 지정하거나 모두 생략하세요.")
    stops: list[dict[str, Any]] = []
    for index, stop in enumerate(raw_stops):
        if isinstance(stop, dict):
            color = stop.get("color")
            offset_raw = stop.get("offset", stop.get("position"))
        else:
            color = stop
            offset_raw = None
        if color is None:
            raise UsageError(f"그라데이션 {index + 1}번째 중지점에 color가 필요합니다.")
        offset = (
            _finite_number(offset_raw, f"그라데이션 {index + 1}번째 offset")
            if uses_offsets
            else index / (len(raw_stops) - 1)
        )
        if not 0 <= offset <= 1:
            raise UsageError("그라데이션 offset은 0~1 범위여야 합니다.")
        if stops and offset < stops[-1]["offset"]:
            raise UsageError("그라데이션 중지점 offset은 오름차순이어야 합니다.")
        stops.append({"offset": offset, "color": _canonical_color(color, "그라데이션 색")})
    result: dict[str, Any] = {"type": fill_type, "angle": angle, "stops": stops}
    if fill_type == "radial_gradient":
        # HWPML/한글의 GradationCenterX/Y, Step, StepCenter 는 백분율 정수다.
        # 소수점이나 범위 밖 값을 한글이 자체 보정하도록 두면 참조 조판과 달라질 수
        # 있어 공개 경계에서 정확히 거부한다.
        for key, default in (
            ("center_x", 50),
            ("center_y", 50),
            ("step", 100),
            ("step_center", 50),
        ):
            number = _finite_number(value.get(key, default), f"방사형 그라데이션 {key}")
            if not number.is_integer() or not 0 <= number <= 100:
                raise UsageError(f"방사형 그라데이션 {key}는 0~100 정수여야 합니다.")
            result[key] = int(number)
    return result


def _normalize_line(value: Any) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return {"type": "solid", "color": _canonical_color(value, "테두리 색"), "width_mm": 0.12}
    if not isinstance(value, dict):
        raise UsageError("테두리는 색 문자열 또는 JSON 객체여야 합니다.")
    raw_type = str(value.get("type", value.get("style", "solid"))).strip().lower()
    if raw_type in {"none", "off"}:
        return {"type": "none"}
    if raw_type != "solid":
        raise UsageError("테두리 type은 solid 또는 none이어야 합니다.")
    color = value.get("color", "#000000")
    width = _finite_number(value.get("width_mm", value.get("width", 0.12)), "테두리 width_mm")
    if not 0 <= width <= 10:
        raise UsageError("테두리 width_mm은 0~10mm 범위여야 합니다.")
    if width == 0:
        return {"type": "none"}
    # HwpLineWidth는 연속값이 아니라 한/글이 지원하는 눈금값만 허용한다.
    # 조용한 반올림은 참조 문서와의 선 굵기 차이를 만들기 때문에 API 경계에서 거부한다.
    supported_widths = (0.1, 0.12, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0)
    if not any(abs(width - candidate) < 1e-9 for candidate in supported_widths):
        raise UsageError(
            "테두리 width_mm은 한/글 지원값(0.1, 0.12, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7, 1, 1.5, 2, 3, 4, 5) 중 하나여야 합니다."
        )
    return {"type": "solid", "color": _canonical_color(color, "테두리 색"), "width_mm": width}


def _normalize_shadow(
    value: Any, *, label: str, supports_alpha: bool = True
) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    if isinstance(value, str) and value.strip().lower() in {"none", "off"}:
        return {"type": "none"}
    if not isinstance(value, dict):
        raise UsageError(f"{label}는 JSON 객체 또는 none이어야 합니다.")
    raw_type = str(value.get("type", "offset")).strip().lower()
    if raw_type in {"none", "off"}:
        return {"type": "none"}
    if raw_type not in {"offset", "parallel", "parallel_right_bottom", "parallel-right-bottom"}:
        raise UsageError(f"{label} type은 offset 또는 none이어야 합니다.")
    alpha_raw = value.get("alpha")
    if alpha_raw is None and "opacity" in value:
        alpha_raw = 255 * _finite_number(value["opacity"], f"{label} opacity") / 100
    alpha = _finite_number(128 if alpha_raw is None else alpha_raw, f"{label} alpha")
    if not supports_alpha:
        # HCharShape에는 ShadowAlpha가 없다. 수치를 받았지만 무시하면 실제
        # 출력과 요청이 달라지므로, 생략/0(한/글의 불투명 기본값)만 허용한다.
        if alpha_raw is not None and alpha != 0:
            raise UsageError(f"{label} alpha는 한/글 2022에서 지원되지 않습니다. 생략하거나 0으로 지정하세요.")
        alpha = 0
    if not 0 <= alpha <= 255:
        raise UsageError(f"{label} alpha는 0~255 범위여야 합니다.")
    offset_x = _finite_number(value.get("offset_x_mm", value.get("x_mm", 1.0)), f"{label} offset_x_mm")
    offset_y = _finite_number(value.get("offset_y_mm", value.get("y_mm", 1.0)), f"{label} offset_y_mm")
    if not -50 <= offset_x <= 50 or not -50 <= offset_y <= 50:
        raise UsageError(f"{label} offset_x_mm/offset_y_mm은 -50~50mm 범위여야 합니다.")
    return {
        "type": "offset",
        "color": _canonical_color(value.get("color", "#000000"), f"{label} 색"),
        "alpha": alpha,
        "offset_x_mm": offset_x,
        "offset_y_mm": offset_y,
    }


def _normalize_text_box_position(value: Any) -> dict[str, Any]:
    if value is None or value == "":
        return {"mode": "inline"}
    if isinstance(value, str):
        mode = value.strip().lower()
        if mode == "inline":
            return {"mode": "inline"}
        if mode == "floating":
            raise UsageError("floating 글상자에는 x_mm와 y_mm 좌표가 필요합니다.")
        raise UsageError("글상자 position은 inline 또는 floating이어야 합니다.")
    if not isinstance(value, dict):
        raise UsageError("글상자 position은 문자열 또는 JSON 객체여야 합니다.")
    mode = str(value.get("mode", "inline")).strip().lower()
    if mode == "inline":
        return {"mode": "inline"}
    if mode != "floating":
        raise UsageError("글상자 position mode는 inline 또는 floating이어야 합니다.")
    if "x_mm" not in value or "y_mm" not in value:
        raise UsageError("floating 글상자에는 x_mm와 y_mm 좌표가 필요합니다.")
    x_mm = _finite_number(value["x_mm"], "글상자 x_mm")
    y_mm = _finite_number(value["y_mm"], "글상자 y_mm")
    if not -1000 <= x_mm <= 1000 or not -1000 <= y_mm <= 1000:
        raise UsageError("글상자 좌표는 -1000~1000mm 범위여야 합니다.")
    return {"mode": "floating", "x_mm": x_mm, "y_mm": y_mm}


def _normalize_align(value: str, *, default: str = "") -> str:
    raw = (value or default).strip().lower()
    if raw not in {"left", "center", "right", "justify"}:
        raise UsageError("가로 정렬은 left, center, right, justify 중 하나여야 합니다.")
    return raw


def _validate_text_format(
    *,
    bold: bool | None,
    italic: bool | None,
    font: str,
    size: float | None,
    color: str,
) -> None:
    if bold is not None and not isinstance(bold, bool):
        raise UsageError("bold 값은 true 또는 false여야 합니다.")
    if italic is not None and not isinstance(italic, bool):
        raise UsageError("italic 값은 true 또는 false여야 합니다.")
    if font and not isinstance(font, str):
        raise UsageError("font 값은 문자열이어야 합니다.")
    if size is not None:
        size_number = _finite_number(size, "글자 크기")
        if not 0 < size_number <= 500:
            raise UsageError("글자 크기는 0보다 크고 500pt 이하여야 합니다.")
    if color:
        _normalize_optional_color(color)


def _action_count(value: Any) -> int:
    """COM 어댑터가 실제 액션 수를 반환하면 undo 기록에 반영한다."""
    if isinstance(value, bool):
        return 1
    if isinstance(value, int) and value > 0:
        return value
    return 1


def _range_bounds(cell_range: str) -> tuple[str, str]:
    raw = cell_range.strip().upper()
    if not raw:
        raise UsageError("셀 범위를 지정하세요. 예: A1:B2")
    if ":" not in raw:
        parse_a1(raw)
        return raw, raw
    start, end = raw.split(":", 1)
    parse_a1(start)
    parse_a1(end)
    return start.strip(), end.strip()


def _normalize_positive_numbers(value: Any, label: str) -> list[float]:
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise UsageError(f"{label} 값이 비어 있습니다.")
        parts = [part.strip() for part in raw.split(",")]
    elif isinstance(value, (int, float)):
        parts = [value]
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        raise UsageError(f"{label}은 숫자 또는 숫자 목록이어야 합니다.")
    try:
        numbers = [float(part) for part in parts]
    except (TypeError, ValueError) as exc:
        raise UsageError(f"{label} 값이 올바르지 않습니다: {value}") from exc
    if not numbers or any(not isfinite(number) or number <= 0 for number in numbers):
        raise UsageError(f"{label} 값은 모두 0보다 커야 합니다.")
    return numbers


def _normalize_border_sides(value: str) -> list[str]:
    raw = (value or "").strip().lower()
    if raw == "all":
        return ["left", "right", "top", "bottom"]
    sides = [side.strip() for side in raw.split(",") if side.strip()]
    unsupported = {"horz", "horizontal", "inside-horizontal"}
    if set(sides) & unsupported:
        raise UsageError("한글 2022에서 TypeHorz는 지원하지 않습니다.")
    unknown = set(sides) - {"left", "right", "top", "bottom"}
    if unknown:
        raise UsageError(f"지원하지 않는 셀 테두리 방향입니다: {', '.join(sorted(unknown))}")
    if not sides:
        raise UsageError("셀 테두리 방향을 하나 이상 지정하세요.")
    return list(dict.fromkeys(sides))


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


def _apply_empty_paragraph_spec(
    canvas: HangulCanvas,
    spec: dict[str, Any],
    actions: list[int],
) -> None:
    """이미 만들어진 빈 일반 문단에 source 문단/글자 모양만 적용한다."""
    if spec["page_break_before"]:
        raise UsageError("질문과 답변 사이의 빈 문단에는 page_break_before를 지정할 수 없습니다.")
    if spec["paragraph"]:
        canvas.set_paragraph_format(**spec["paragraph"])
        actions[0] += 1
    for run in spec["runs"]:
        if run["text"]:
            raise UsageError("blank_paragraph의 runs 텍스트는 모두 비어 있어야 합니다.")
        format_kwargs = _run_font_kwargs(run)
        if format_kwargs:
            canvas.set_font(**format_kwargs)
            actions[0] += 1


def _normalize_blank_paragraph(value: Any) -> dict[str, Any]:
    """source 정규화 사양의 빈 일반 문단을 안전한 공개 구조로 바꾼다."""
    if not isinstance(value, dict):
        raise UsageError("blank_paragraph 는 빈 문단 JSON 객체여야 합니다.")
    raw = dict(value)
    kind = raw.pop("kind", "paragraph")
    if kind != "paragraph":
        raise UsageError("blank_paragraph.kind 는 paragraph 여야 합니다.")
    allowed = {"text", "runs", "paragraph", "page_break_before"}
    unknown = set(raw) - allowed
    if unknown:
        raise UsageError(
            "blank_paragraph 에 지원하지 않는 필드가 있습니다: "
            + ", ".join(sorted(str(key) for key in unknown))
        )
    spec = _normalize_paragraph_spec(
        text=raw.get("text", ""),
        runs=raw.get("runs"),
        paragraph=raw.get("paragraph"),
        page_break_before=raw.get("page_break_before", False),
    )
    if spec["page_break_before"]:
        raise UsageError("blank_paragraph 에 page_break_before를 지정할 수 없습니다.")
    if any(run["text"] for run in spec["runs"]):
        raise UsageError("blank_paragraph의 runs 텍스트는 모두 비어 있어야 합니다.")
    return spec


def _normalize_inline_single_cell_table(value: Any) -> dict[str, Any]:
    """문단 앞에 재생성할 source 1×1 인라인 표 사양을 엄격히 검증한다."""
    if not isinstance(value, dict):
        raise UsageError("table_spec 은 1×1 인라인 표 JSON 객체여야 합니다.")
    raw = dict(value)
    allowed = {
        "kind",
        "rows",
        "cols",
        "column_widths_mm",
        "row_heights_mm",
        "default_margin_mm",
        "merges",
        "exit_cell",
        "cells",
        "position",
        "properties",
        "page_break_before",
        "review",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise UsageError(
            "table_spec 에 지원하지 않는 필드가 있습니다: "
            + ", ".join(sorted(str(key) for key in unknown))
        )
    if raw.get("kind", "table") != "table":
        raise UsageError("table_spec.kind 는 table 이어야 합니다.")
    if raw.get("rows") != 1 or raw.get("cols") != 1:
        raise UsageError("이 명령은 1행 1열 인라인 표만 재생성합니다.")
    if raw.get("merges", []) not in ([], None):
        raise UsageError("1행 1열 표에는 merges를 지정할 수 없습니다.")
    if raw.get("exit_cell", "A1").strip().upper() != "A1":
        raise UsageError("1행 1열 표의 exit_cell 은 A1 이어야 합니다.")
    if raw.get("page_break_before", False) is not False:
        raise UsageError("문단 앞 표에는 page_break_before를 지정할 수 없습니다.")

    column_widths = _normalize_positive_numbers(raw.get("column_widths_mm"), "table_spec 열 너비")
    row_heights = _normalize_positive_numbers(raw.get("row_heights_mm"), "table_spec 행 높이")
    if len(column_widths) != 1 or len(row_heights) != 1:
        raise UsageError("1행 1열 표에는 열 너비와 행 높이를 각각 하나만 지정하세요.")
    if column_widths[0] > 500 or row_heights[0] > 500:
        raise UsageError("표 열 너비와 행 높이는 500mm 이하여야 합니다.")

    cells = raw.get("cells")
    if not isinstance(cells, dict) or set(cells) != {"A1"}:
        raise UsageError("1행 1열 표의 cells 는 A1 하나만 포함해야 합니다.")
    cell = cells["A1"]
    if not isinstance(cell, dict):
        raise UsageError("table_spec.cells.A1 은 셀 JSON 객체여야 합니다.")
    cell_allowed = {"paragraphs", "margin_mm", "valign", "borders", "fill"}
    cell_unknown = set(cell) - cell_allowed
    if cell_unknown:
        raise UsageError(
            "table_spec.cells.A1 에 지원하지 않는 필드가 있습니다: "
            + ", ".join(sorted(str(key) for key in cell_unknown))
        )
    paragraphs = _normalize_cell_paragraphs(cell.get("paragraphs"))
    margin = _normalize_margin(cell.get("margin_mm"))
    if margin is None:
        raise UsageError("table_spec.cells.A1.margin_mm 을 4개 mm 값으로 지정하세요.")
    valign = str(cell.get("valign", "")).strip().lower()
    if valign not in {"top", "center", "bottom"}:
        raise UsageError("table_spec.cells.A1.valign 은 top, center, bottom 중 하나여야 합니다.")
    fill = _normalize_fill(cell.get("fill"), allow_empty=False)
    assert fill is not None

    raw_borders = cell.get("borders")
    if not isinstance(raw_borders, (list, tuple)) or not raw_borders:
        raise UsageError("table_spec.cells.A1.borders 는 하나 이상의 테두리 객체여야 합니다.")
    borders: list[dict[str, Any]] = []
    for index, raw_border in enumerate(raw_borders, start=1):
        if not isinstance(raw_border, dict):
            raise UsageError(f"table_spec.cells.A1.borders[{index}] 는 객체여야 합니다.")
        border_unknown = set(raw_border) - {"sides", "line_type", "width", "color"}
        if border_unknown:
            raise UsageError(
                f"table_spec.cells.A1.borders[{index}] 에 지원하지 않는 필드가 있습니다: "
                + ", ".join(sorted(str(key) for key in border_unknown))
            )
        sides = raw_border.get("sides")
        if not isinstance(sides, str):
            raise UsageError(f"table_spec.cells.A1.borders[{index}].sides 는 문자열이어야 합니다.")
        line_type = raw_border.get("line_type")
        width = raw_border.get("width")
        color = raw_border.get("color")
        if not isinstance(line_type, (str, int)) or isinstance(line_type, bool):
            raise UsageError(f"table_spec.cells.A1.borders[{index}].line_type 값이 올바르지 않습니다.")
        if not isinstance(width, (str, int)) or isinstance(width, bool):
            raise UsageError(f"table_spec.cells.A1.borders[{index}].width 값이 올바르지 않습니다.")
        borders.append(
            {
                "sides": _normalize_border_sides(sides),
                "line_type": line_type,
                "width": width,
                "color": _canonical_color(color, "셀 테두리 색"),
            }
        )

    raw_properties = raw.get("properties")
    if not isinstance(raw_properties, dict):
        raise UsageError("table_spec.properties 는 표 속성 JSON 객체여야 합니다.")
    property_unknown = set(raw_properties) - {"page_break", "repeat_header", "cell_spacing_mm"}
    if property_unknown:
        raise UsageError(
            "table_spec.properties 에 지원하지 않는 필드가 있습니다: "
            + ", ".join(sorted(str(key) for key in property_unknown))
        )
    properties = _normalize_table_properties(
        page_break=raw_properties.get("page_break", "cell"),
        repeat_header=raw_properties.get("repeat_header", True),
        cell_spacing_mm=raw_properties.get("cell_spacing_mm", 0.0),
    )

    raw_position = raw.get("position")
    if not isinstance(raw_position, dict):
        raise UsageError("table_spec.position 은 인라인 표 위치 JSON 객체여야 합니다.")
    if str(raw_position.get("mode", "")).strip().lower() != "inline":
        raise UsageError("이 명령은 inline 표 위치만 재생성합니다.")
    inline_position = {
        key: raw_position[key]
        for key in ("mode", "affect_line_spacing", "outside_margin_mm")
        if key in raw_position
    }
    normalized_position = _normalize_table_position(inline_position)

    return {
        "column_width_mm": column_widths[0],
        "row_height_mm": row_heights[0],
        "paragraphs": paragraphs,
        "margin_mm": margin,
        "valign": valign,
        "fill": fill,
        "borders": borders,
        "properties": properties,
        "position": {
            "affect_line_spacing": normalized_position["affect_line_spacing"],
            "outside_margin_mm": normalized_position["outside_margin_mm"],
        },
    }
