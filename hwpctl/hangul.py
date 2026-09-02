"""한/글 2022 캔버스 어댑터.

pyhwpx 를 우선하고, 없으면 win32com ``HWPFrame.HwpObject``.
키 입력(SendKeys) 은 쓰지 않는다. 한글 2024 전용 GSG/SelectCtrl/메타태그는 쓰지 않는다.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from typing import Any, Callable

from hwpctl.colors import parse_color, rgb_to_bgr_int
from hwpctl.errors import HangulCommandError, HangulMissingError, UsageError
from hwpctl.layout import hard_line_count

MISSING_KO = (
    "한/글(한글 오피스)을 찾을 수 없습니다. "
    "이 컴퓨터에 한글 2022가 설치되어 있고 Windows에서 실행 중인지 확인하세요. "
    "pyhwpx와 pywin32가 필요합니다. "
    "예: pip install \"hwpctl[windows]\""
)

CONNECT_KO = (
    "한/글 창에 연결하지 못했습니다. "
    "한글 2022를 실행한 뒤 다시 시도하세요. "
    "보안 모듈(FilePathChecker) 대화 상자가 떠 있으면 허용해 주세요."
)

NO_WINDOW_KO = (
    "실행 중인 한/글 창이 없습니다. "
    "한글 2022를 먼저 실행해 문서를 열어 두세요. "
    "새 창을 만들려면 hwpctl open --new 를 사용하세요."
)


def require_windows() -> None:
    if sys.platform != "win32":
        raise HangulMissingError(MISSING_KO)


@dataclass
class DocInfo:
    window_title: str
    path: str
    modified: bool
    page: int
    page_count: int
    version: list[int]
    backend: str


class HangulCanvas:
    """열린 한/글 창(캔버스) 한 개."""

    def __init__(self, px: Any | None, com: Any, backend: str) -> None:
        self.px = px
        self.com = com
        self.backend = backend

    # --- 연결 --------------------------------------------------------------

    @classmethod
    def connect(
        cls,
        new: bool = False,
        allow_launch: bool = False,
        hwnd: int = 0,
    ) -> HangulCanvas:
        """열린 한/글 창에 붙는다.

        기본은 *붙기만* 한다: 실행 중인 인스턴스가 없으면 한/글을 새로 띄우지 않고
        한국어 오류를 낸다 (pyhwpx ``Hwp()`` 는 없으면 자동 실행하므로 ROT 로 먼저 확인).
        ``new=True`` 또는 ``allow_launch=True`` (open 명령) 일 때만 실행을 허용한다.

        ``hwnd`` 가 있고 ``new`` 가 아니면 pyhwpx 를 거치지 않는다.
        ``Hwp()`` 는 ROT 첫 인스턴스(라이브: ``!HwpObject.120.1``)에 붙어
        고정 창(``120.2``)을 놓친다. win32com 으로 그 핸들을 가진 ROT 객체에만 붙는다.
        """
        require_windows()
        if not new and not allow_launch and not _hwp_running():
            raise HangulMissingError(NO_WINDOW_KO)

        # 고정된 창: pyhwpx 보다 먼저, hwnd 로 ROT 객체를 고른다.
        if hwnd and not new:
            found = _attach_running_com(hwnd=hwnd)
            if found is not None:
                _make_window_current(found, hwnd)
                return cls(px=None, com=found, backend="win32com")
            raise HangulCommandError(
                f"고정된 한/글 창(핸들 {hwnd})을 찾지 못했습니다. "
                "대상 창을 클릭해 활성화한 뒤 다시 시도하거나, "
                "hwpctl open 으로 작업 창을 다시 지정하세요."
            )

        last_error: Exception | None = None
        try:
            from pyhwpx import Hwp  # type: ignore

            px = Hwp(new=new, visible=True, register_module=True)
            com = getattr(px, "hwp", None) or getattr(px, "Application", None) or px
            return cls(px=px, com=com, backend="pyhwpx")
        except HangulMissingError:
            raise
        except ImportError:
            last_error = None
        except Exception as exc:  # COM 실패
            # Hwp(new=True)가 일부 문서를 만든 뒤 실패했을 수 있다. 여기서
            # win32com fallback을 이어가면 빈 문서를 추가 생성할 수 있으므로 중단한다.
            if new:
                raise HangulMissingError(CONNECT_KO) from exc
            last_error = exc
        try:
            import win32com.client  # type: ignore

            com: Any | None = None
            if not new:
                # Dispatch 는 새 인스턴스를 띄우므로, 붙을 때는 ROT 로 기존 창에 바인딩.
                com = _attach_running_com(hwnd=None)
                if com is None and not allow_launch:
                    raise HangulMissingError(NO_WINDOW_KO)
            if com is None:
                com = win32com.client.gencache.EnsureDispatch("HWPFrame.HwpObject")
            try:
                com.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
            except Exception:
                pass
            # EnsureDispatch가 만든 한/글은 보통 빈 문서 하나를 이미 가진다.
            # 그것을 그대로 쓰고, 문서가 전혀 없을 때만 하나 만든다.
            if new:
                _ensure_document_if_empty(com)
            _make_window_current(com, 0)
            return cls(px=None, com=com, backend="win32com")
        except HangulMissingError:
            raise
        except ImportError as exc:
            raise HangulMissingError(MISSING_KO) from exc
        except Exception as exc:
            raise HangulMissingError(CONNECT_KO) from (last_error or exc)

    def window_handle(self) -> int:
        """연결된 한/글 창의 윈도우 핸들. 대상 창 고정(pinning)에 쓴다. 실패 시 0.

        ``Active_XHwpWindow.WindowHandle`` 을 쓰고, 없으면 Item(0).
        한 인스턴스에 창이 둘이면 Item(0) 은 틀린 창일 수 있다.
        """
        return _window_handle_of(self.com)

    @staticmethod
    def list_open_documents() -> list[dict[str, Any]]:
        """실행 중인 모든 한/글 문서의 읽기 전용 메타데이터를 열거한다.

        이 경로는 현재 문서를 활성화하거나 캐럿·선택을 옮기지 않는다. 특히
        ``SetActive_XHwpDocument``·``Visible = True``·저장·닫기 호출을 하지
        않으므로, 여러 창에서 경로 없는 빈 초안을 식별할 때 쓴다.
        """
        return list_open_documents()

    # --- 조회 --------------------------------------------------------------

    def doc_info(self) -> DocInfo:
        title = self._first_str(
            lambda: self.px.get_title() if self.px else None,
            lambda: getattr(self.px, "Title", None) if self.px else None,
            lambda: getattr(self.com, "Title", None),
            default="한글",
        )
        path = self._first_str(
            lambda: getattr(self.px, "Path", None) if self.px else None,
            lambda: getattr(self.com, "Path", None),
            lambda: getattr(self.com, "FullName", None),
            lambda: self._doc_attr("FullName"),
            default="",
        )
        modified = bool(
            self._first(
                lambda: getattr(self.px, "is_modified", None) if self.px else None,
                lambda: self._doc_attr("Modified"),
                default=False,
            )
        )
        page_count = int(
            self._first(
                lambda: getattr(self.px, "PageCount", None) if self.px else None,
                lambda: getattr(self.com, "PageCount", None),
                default=1,
            )
            or 1
        )
        page = int(
            self._first(
                lambda: getattr(self.px, "current_page", None) if self.px else None,
                lambda: self._key_page(),
                default=1,
            )
            or 1
        )
        version = self._version()
        return DocInfo(
            window_title=title,
            path=path or "",
            modified=modified,
            page=page,
            page_count=page_count,
            version=version,
            backend=self.backend,
        )

    def get_body_text(self) -> str:
        if self.px:
            try:
                return str(self.px.get_text_file(format="UNICODE", option="") or "")
            except Exception:
                pass
        try:
            return str(self.com.GetTextFile("UNICODE", "") or "")
        except Exception as exc:
            raise HangulCommandError(f"본문을 읽지 못했습니다: {exc}") from exc

    def has_selection(self) -> bool:
        """실제 블록 선택 여부.

        ``get_selected_text`` 는 선택이 없어도 '현재 단어'(pyhwpx) 또는 문서 전체(COM
        saveblock 폴백)를 리턴하므로 선택 판정에 쓰면 안 된다. GetSelectedPos 의
        첫 요소(is_block)를 쓴다. 판정 실패 시 False(교체 거부가 안전한 방향).
        """
        try:
            pos = self.px.get_selected_pos() if self.px else self.com.GetSelectedPos()
            if pos is not None and len(pos) >= 7:
                return bool(pos[0])
        except Exception:
            pass
        return False

    def get_selected_text(self) -> str:
        if self.px:
            try:
                return str(self.px.get_selected_text(as_="str", keep_select=True) or "")
            except Exception:
                try:
                    return str(self.px.get_selected_text() or "")
                except Exception:
                    pass
        try:
            return str(self.com.GetTextFile("UNICODE", "saveblock:true") or "")
        except Exception:
            return ""

    @staticmethod
    def _paragraph_text_for_compare(value: str) -> str:
        """한/글 블록 선택에 붙는 문단 끝 표식을 비교에서만 제거한다.

        본문 문단을 정확히 찾아 서식을 바꿀 때 선행/후행 공백은 의미가 있다.
        그래서 ``strip()`` 이 아니라 한/글이 선택 텍스트 끝에 더하는 CR/LF와
        NUL만 제거한다.
        """
        return str(value or "").replace("\x00", "").rstrip("\r\n")

    def select_exact_body_paragraph(self, text: str, occurrence: int = 1) -> dict[str, Any]:
        """정확히 일치하는 일반 본문 문단 하나를 블록으로 선택한다.

        HFindReplace 로 문서를 처음부터 순방향 검색한 뒤, 선택된 문자열과 요청을
        다시 대조한다. 표 셀/필드 안의 일치는 거부하고 ``MoveSelParaEnd`` 뒤의
        전체 문단도 다시 대조하므로, 부분 문자열·다른 개체를 조용히 고치지 않는다.
        호출자는 완료 후 저장해 둔 캐럿/선택을 복원해야 한다.
        """
        if not isinstance(text, str) or not text:
            raise UsageError("text 는 비어 있지 않은 한 문단 문자열이어야 합니다.")
        if "\r" in text or "\n" in text:
            raise UsageError("text 에 줄바꿈을 넣을 수 없습니다. 한 문단만 지정하세요.")
        if isinstance(occurrence, bool) or not isinstance(occurrence, int) or occurrence < 1:
            raise UsageError("occurrence 는 1 이상의 정수여야 합니다.")

        expected = self._paragraph_text_for_compare(text)
        self.assert_no_dialog()
        # 한/글 2022는 표 속성 대화상자 직후 MoveDocBegin을 실제로 수행하고도
        # false를 반환하는 경우가 있다. 반환값 대신 바로 뒤 RepeatFind의 실제
        # 선택·전체 문단 대조로 성공 여부를 판정한다.
        self.run("Cancel")
        self.run("MoveDocBegin")

        found = False
        for _ in range(occurrence):
            try:
                pset = self.com.HParameterSet.HFindReplace
                self.com.HAction.GetDefault("RepeatFind", pset.HSet)
                pset.FindString = text
                pset.ReplaceString = ""
                pset.Direction = self.com.FindDir("Forward")
                pset.WholeWordOnly = 0
                pset.UseWildCards = 0
                pset.MatchCase = 0
                pset.ReplaceMode = 0
                pset.IgnoreMessage = 1
                pset.FindType = 1
                found = bool(self.com.HAction.Execute("RepeatFind", pset.HSet))
            except Exception as exc:
                raise HangulCommandError(f"본문 문단 검색에 실패했습니다: {exc}") from exc
            if not found:
                raise HangulCommandError("지정한 본문 문단을 찾지 못했습니다. 문구를 다시 확인하세요.")

        matched = self._paragraph_text_for_compare(self.get_selected_text())
        if matched != expected:
            raise HangulCommandError(
                "찾은 텍스트가 요청한 문단 전체와 정확히 일치하지 않아 수정을 중단했습니다."
            )
        if self.is_cell():
            raise HangulCommandError("찾은 텍스트가 표 셀 안에 있어 본문 문단 수정을 중단했습니다.")

        # 검색 결과는 찾은 문자열만 선택한다. 문단 전체로 확장한 뒤 다시 비교해
        # 표제/글상자 속 부분 일치를 일반 본문으로 오인하지 않게 한다.
        self.run("Cancel")
        if not self.run("MoveParaBegin") or not self.run("MoveSelParaEnd"):
            raise HangulCommandError("찾은 문단 전체를 선택하지 못했습니다.")
        paragraph_text = self._paragraph_text_for_compare(self.get_selected_text())
        if self.is_cell() or paragraph_text != expected:
            raise HangulCommandError(
                "찾은 범위가 일반 본문 한 문단과 정확히 일치하지 않아 수정을 중단했습니다."
            )
        self.assert_no_dialog()
        return {
            "text": paragraph_text,
            "position": self.get_pos(),
            "in_cell": False,
        }

    def table_control(self, table: int) -> Any:
        """표 번호를 검증해 해당 네이티브 표 컨트롤을 반환한다.

        이 객체는 같은 한/글 문서 안에서만 쓸 수 있는 짧은 수명의 내부 핸들이다.
        외부 API에 노출하지 않고, 생성한 대체 표가 정상인지 확인한 뒤 *원래*
        표 하나만 ``DeleteCtrl``로 지우는 원자 작업에만 사용한다.
        """
        if isinstance(table, bool) or not isinstance(table, int) or table < 0:
            raise UsageError("table 은 0 이상의 표 번호여야 합니다.")
        tables = self._table_ctrls()
        if table >= len(tables):
            raise HangulCommandError(f"{table}번 표를 찾지 못했습니다.")
        ctrl = tables[table]
        if str(getattr(ctrl, "CtrlID", "")) != "tbl":
            raise HangulCommandError(f"{table}번 개체가 표가 아니어서 수정을 중단했습니다.")
        return ctrl

    def delete_table_control(self, ctrl: Any) -> None:
        """검증된 표 컨트롤 하나만 확인 대화상자 없이 제거한다."""
        if str(getattr(ctrl, "CtrlID", "")) != "tbl":
            raise HangulCommandError("삭제 대상이 표 컨트롤이 아니어서 수정을 중단했습니다.")
        try:
            result = self.com.DeleteCtrl(ctrl)
        except Exception as exc:
            raise HangulCommandError("기존 질문 표를 제거하지 못했습니다.") from exc
        if result is False:
            raise HangulCommandError("기존 질문 표를 제거하지 못했습니다.")

    def ensure_blank_paragraph_before_body(self, text: str) -> bool:
        """정확한 본문 문단 바로 앞에 일반 빈 문단 하나를 확보한다.

        반환값은 새 Enter를 추가했는지 여부다. 표의 다음 문단이 이미 빈 경우에는
        그것을 그대로 사용하고, 없을 때만 답변 문단의 시작에서 ``BreakPara``를
        한 번 실행한다. 표 안·부분 일치·글상자 일치는
        ``select_exact_body_paragraph`` 단계에서 모두 거부한다.
        """
        if not isinstance(text, str) or not text or "\r" in text or "\n" in text:
            raise UsageError("text 는 비어 있지 않은 한 문단 문자열이어야 합니다.")

        def _previous_is_blank() -> bool:
            self.select_exact_body_paragraph(text)
            self.run("Cancel")
            if not self.run("MoveParaBegin"):
                raise HangulCommandError("본문 문단의 시작으로 이동하지 못했습니다.")
            moved = self.run("MoveUp")
            if not moved or self.is_cell():
                return False
            if not self.run("MoveParaBegin") or not self.run("MoveSelParaEnd"):
                raise HangulCommandError("앞 문단을 검증하지 못했습니다.")
            blank = self._paragraph_text_for_compare(self.get_selected_text()) == ""
            if self.is_cell():
                return False
            if blank:
                self.run("Cancel")
                if not self.run("MoveParaBegin"):
                    raise HangulCommandError("빈 문단의 시작으로 이동하지 못했습니다.")
            return blank

        if _previous_is_blank():
            return False

        # 이전 문단이 표이거나 비어 있지 않으면, 답변 시작을 정확히 다시 잡은 뒤
        # Enter 한 번으로 빈 문단을 만든다. 이 명령은 답변의 내용·서식을 건드리지 않는다.
        self.select_exact_body_paragraph(text)
        self.run("Cancel")
        if not self.run("MoveParaBegin"):
            raise HangulCommandError("본문 문단의 시작으로 이동하지 못했습니다.")
        self.break_paragraph()
        if not _previous_is_blank():
            raise HangulCommandError("질문과 답변 사이의 빈 문단을 확인하지 못했습니다.")
        return True

    def count_blank_paragraphs_before_body(self, text: str, maximum: int = 8) -> int:
        """일반 본문 문단 바로 앞에 연속된 빈 일반 문단 수를 읽는다."""
        if not isinstance(text, str) or not text or "\r" in text or "\n" in text:
            raise UsageError("text 는 비어 있지 않은 한 문단 문자열이어야 합니다.")
        if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 32:
            raise UsageError("maximum 은 1~32 정수여야 합니다.")
        self.select_exact_body_paragraph(text)
        self.run("Cancel")
        if not self.run("MoveParaBegin"):
            raise HangulCommandError("본문 문단의 시작으로 이동하지 못했습니다.")
        count = 0
        for _ in range(maximum):
            if not self.run("MoveUp") or self.is_cell():
                break
            if not self.run("MoveParaBegin") or not self.run("MoveSelParaEnd"):
                raise HangulCommandError("앞 문단을 읽지 못했습니다.")
            if self.is_cell() or self._paragraph_text_for_compare(self.get_selected_text()) != "":
                break
            count += 1
            self.run("Cancel")
            if not self.run("MoveParaBegin"):
                raise HangulCommandError("빈 문단의 시작으로 이동하지 못했습니다.")
        return count

    def remove_empty_paragraph_immediately_before_body(self, text: str) -> None:
        """본문 바로 앞의 빈 일반 문단 하나만 선택해 제거한다.

        ``Delete`` 액션은 표 경계에서 확인 대화상자를 띄울 수 있어 쓰지 않는다.
        빈 문단 전체를 블록 선택한 뒤 InsertText 빈 문자열로 치환하므로, 답변과
        표 컨트롤 자체는 선택하지 않는다.
        """
        self.select_exact_body_paragraph(text)
        self.run("Cancel")
        if not self.run("MoveParaBegin") or not self.run("MoveUp"):
            raise HangulCommandError("제거할 빈 문단으로 이동하지 못했습니다.")
        if self.is_cell():
            raise HangulCommandError("본문 바로 앞이 표여서 빈 문단을 제거하지 않습니다.")
        if not self.run("MoveParaBegin") or not self.run("MoveSelParaEnd"):
            raise HangulCommandError("제거할 빈 문단을 선택하지 못했습니다.")
        if self.is_cell() or self._paragraph_text_for_compare(self.get_selected_text()) != "":
            raise HangulCommandError("본문 바로 앞 문단이 비어 있지 않아 제거하지 않습니다.")
        self.insert_text("")
        self.select_exact_body_paragraph(text)
        self.run("Cancel")

    def get_page_text(self, page_index_1: int) -> str:
        pgno0 = max(0, page_index_1 - 1)
        if self.px:
            try:
                return str(self.px.get_page_text(pgno=pgno0) or "")
            except Exception:
                pass
        try:
            return str(self.com.GetPageText(pgno0, 0xFFFFFFFF) or "")
        except Exception as exc:
            raise HangulCommandError(f"쪽 텍스트를 읽지 못했습니다: {exc}") from exc

    def table_count(self) -> int:
        return self._table_count()

    def list_tables(
        self,
        preview_rows: int = 8,
        preview_cols: int = 8,
        max_tables: int = 10,
    ) -> list[dict[str, Any]]:
        count = self._table_count()
        tables: list[dict[str, Any]] = []
        for i in range(min(count, max_tables)):
            self.get_into_nth_table(i)
            # win32com 폴백에는 get_row_num/get_col_num 편의 메서드가 없다.
            # 1×1로 추측하면 실제 2×2 표도 스냅샷에서 잘못 보고되어 비교 자료가
            # 무의미해진다. 현재 표의 실제 A1 주소 순회 결과를 우선 사용한다.
            addresses = self._table_addresses()
            parsed_addresses: list[tuple[int, int]] = []
            for address in addresses:
                try:
                    parsed_addresses.append(_parse_a1(address))
                except UsageError:
                    continue
            rows = (
                max(row for row, _column in parsed_addresses) + 1
                if parsed_addresses
                else int(self._call_px("get_row_num") or self._guess_rows())
            )
            cols = (
                max(column for _row, column in parsed_addresses) + 1
                if parsed_addresses
                else int(self._call_px("get_col_num") or self._guess_cols())
            )
            preview: list[list[str]] = []
            for r in range(min(rows, preview_rows)):
                line: list[str] = []
                for c in range(min(cols, preview_cols)):
                    try:
                        self.goto_addr(_a1(r, c))
                        # goto_addr는 캐럿만 옮긴다. 선택 영역을 읽으면 이전 블록
                        # 선택 또는 빈 문자열이 나올 수 있으므로 현재 셀을 명시적으로
                        # 선택·복원하는 전용 판독기를 쓴다.
                        line.append(self._get_current_cell_text())
                    except HangulCommandError:
                        line.append("")
                preview.append(line)
            tables.append({"index": i, "rows": rows, "cols": cols, "preview": preview})
        return tables

    def inspect_table_layout(self, n: int) -> dict[str, Any]:
        """n번 표의 조판 치수를 읽는다 (한글 2022 Automation만 사용).

        셀의 실제 조판 줄 수는 셀 리스트 안에서 조판 줄 끝을 순회하며 위치 진행과
        KeyIndicator를 함께 확인한다. 이동/상태바 조회가 실패한 셀만 명시 줄바꿈
        수로 보수적으로 대체한다.
        """
        self.get_into_nth_table(n)
        addresses = self._table_addresses()
        if not addresses:
            raise HangulCommandError(f"{n}번 표의 셀 구조를 읽지 못했습니다.")
        parsed = [(_parse_a1(addr), addr) for addr in addresses]
        rows = max(rc[0][0] for rc in parsed) + 1
        cols = max(rc[0][1] for rc in parsed) + 1

        column_widths: list[float] = []
        for col in range(cols):
            addr = next((addr for (row_col, addr) in parsed if row_col[1] == col), None)
            if addr is None:
                column_widths.append(0.0)
                continue
            self.goto_addr(addr)
            column_widths.append(self._get_col_width_mm())

        row_heights: list[float] = []
        cells: list[dict[str, Any]] = []
        warnings: list[str] = []
        for row in range(rows):
            row_height = 0.0
            for (cell_row, cell_col), addr in parsed:
                if cell_row != row:
                    continue
                self.goto_addr(addr)
                text = self._get_current_cell_text().rstrip("\x00")
                line_count, measured = self._cell_line_count(text)
                margins = self._get_cell_margin_mm()
                height = self._get_row_height_mm()
                font_size, line_spacing = self._get_cell_typography(text)
                row_height = max(row_height, height)
                cells.append(
                    {
                        "row": cell_row,
                        "col": cell_col,
                        "address": addr,
                        "text": text,
                        "line_count": line_count,
                        "hard_line_count": hard_line_count(text),
                        "soft_wrapped": line_count > hard_line_count(text),
                        "line_measurement": (
                            "key_indicator" if measured else "explicit_break_estimate"
                        ),
                        "font_size_pt": font_size,
                        "line_spacing_percent": line_spacing,
                        "margins_mm": margins,
                        "row_height_mm": height,
                    }
                )
                if not measured:
                    warnings.append(
                        f"{n}번 표 {addr} 셀은 KeyIndicator 줄 수를 읽지 못해 "
                        "명시적 줄바꿈만 사용했습니다."
                    )
            row_heights.append(row_height)

        table_width = max(self._get_table_width_mm(), sum(column_widths))
        body_width = self._get_body_width_mm()
        outside = self._get_table_outside_margin_mm()
        max_width = max(0.0, body_width - outside["left"] - outside["right"])
        if table_width > max_width + 0.5:
            warnings.append(
                f"{n}번 표 폭({table_width:.2f}mm)이 본문 가용 폭"
                f"({max_width:.2f}mm)을 넘습니다."
            )
        return {
            "index": n,
            "rows": rows,
            "cols": cols,
            "table_width_mm": table_width,
            "body_width_mm": body_width,
            "max_table_width_mm": max_width,
            "column_widths_mm": column_widths,
            "row_heights_mm": row_heights,
            "cells": cells,
            "warnings": warnings,
        }

    def set_table_column_widths(self, n: int, widths_mm: list[float]) -> int:
        """열 너비를 mm로 일괄 적용하고 실제 TablePropertyDialog 액션 수를 반환."""
        actions = 0
        for col, width in enumerate(widths_mm):
            actions += self.set_table_column_width(n, col, width)
        return actions

    def set_table_column_width(self, n: int, col: int, width_mm: float) -> int:
        """한 열의 너비를 직접 설정한다. Execute 결과를 확인해 성공 시 1을 반환."""
        self.get_into_nth_table(n)
        addresses = self._table_addresses()
        addr = next((addr for addr in addresses if _parse_a1(addr)[1] == col), None)
        if addr is None:
            raise HangulCommandError(
                f"{n}번 표 {col + 1}열은 병합 구조 때문에 너비를 조절할 셀을 찾지 못했습니다."
            )
        self.goto_addr(addr)
        self.set_col_width_current(width_mm)
        return 1

    def set_col_width_current(self, width_mm: float) -> None:
        """현재 셀이 속한 열을 선택해 너비(mm)를 설정한다."""
        self.assert_no_dialog()
        if not self.run("TableColPageUp"):
            raise HangulCommandError("현재 열 선택에 실패했습니다 (열 첫 행 이동 실패).")
        top = self.current_cell_addr()
        if top:
            self.begin_cell_block(top)
        elif not self.run("TableCellBlock"):
            raise HangulCommandError("현재 열 선택에 실패했습니다.")
        if not (self.run("TableCellBlockExtend") and self.run("TableColPageDown")):
            raise HangulCommandError("현재 열 선택에 실패했습니다.")
        try:
            pset = self.com.HParameterSet.HShapeObject
            self.com.HAction.GetDefault("TablePropertyDialog", pset.HSet)
            pset.HSet.SetItem("ShapeType", 3)
            pset.HSet.SetItem("ShapeCellSize", 1)
            pset.ShapeTableCell.Width = self._mm_to_hwpunit(width_mm)
            ok = bool(self.com.HAction.Execute("TablePropertyDialog", pset.HSet))
            if not ok:
                raise HangulCommandError("현재 열 너비 조절 액션이 실패했습니다.")
        except HangulCommandError:
            raise
        except Exception as exc:
            raise HangulCommandError(f"현재 열 너비 조절에 실패했습니다: {exc}") from exc
        finally:
            # 열 전체 셀블록 선택이 다음 병합/이동으로 새지 않게 항상 해제한다.
            try:
                self.run("Cancel")
            except HangulCommandError:
                pass
        self.assert_no_dialog()

    def get_col_width(self) -> float:
        """현재 셀의 열 너비(mm). GetCellWidth 대신 TablePropertyDialog를 쓴다."""
        if not self.is_cell():
            raise HangulCommandError("캐럿이 표 셀 안에 있지 않아 열 너비를 읽을 수 없습니다.")
        return self._get_col_width_mm()

    def get_table_column_widths(self) -> list[float]:
        """현재 표의 각 열 너비(mm)를 첫 행의 실제 셀 기준으로 읽는다."""
        representatives = self.table_column_addresses()
        widths: list[float] = []
        for _col, addr in sorted(representatives.items()):
            self.goto_addr(addr)
            widths.append(self._get_col_width_mm())
        return widths

    def set_table_row_height(self, n: int, row: int, height_mm: float) -> int:
        """행 높이를 mm로 설정한다. 성공하면 한/글 액션 수 1."""
        self.get_into_nth_table(n)
        addr = next(
            (addr for addr in self._table_addresses() if _parse_a1(addr)[0] == row),
            None,
        )
        if addr is None:
            raise HangulCommandError(
                f"{n}번 표 {row + 1}행은 병합 구조 때문에 높이를 조절할 셀을 찾지 못했습니다."
            )
        self.goto_addr(addr)
        self.set_row_height_current(height_mm)
        return 1

    def set_row_height_current(self, height_mm: float) -> None:
        """현재 셀이 속한 행 높이(mm)를 설정한다."""
        self.assert_no_dialog()
        try:
            pset = self.com.HParameterSet.HShapeObject
            self.com.HAction.GetDefault("TablePropertyDialog", pset.HSet)
            pset.HSet.SetItem("ShapeType", 3)
            pset.HSet.SetItem("ShapeCellSize", 1)
            pset.ShapeTableCell.Height = self._mm_to_hwpunit(height_mm)
            ok = bool(self.com.HAction.Execute("TablePropertyDialog", pset.HSet))
        except Exception as exc:
            raise HangulCommandError(f"현재 행 높이 조절에 실패했습니다: {exc}") from exc
        if not ok:
            raise HangulCommandError("현재 행 높이 조절 액션이 실패했습니다.")
        self.assert_no_dialog()

    def get_row_height(self) -> float:
        """현재 셀의 행 높이(mm). TablePropertyDialog 기본값에서 읽는다."""
        if not self.is_cell():
            raise HangulCommandError("캐럿이 표 셀 안에 있지 않아 행 높이를 읽을 수 없습니다.")
        return self._get_row_height_mm()

    # --- 편집 (COM 액션, 키 입력 없음) ------------------------------------

    def run(self, action_id: str) -> bool:
        if self.px:
            try:
                return bool(self.px.Run(action_id))
            except Exception:
                pass
        try:
            return bool(self.com.HAction.Run(action_id))
        except Exception as exc:
            raise HangulCommandError(f"한/글 액션 '{action_id}' 실패: {exc}") from exc

    def insert_text(self, text: str) -> None:
        if self.px:
            ok = self.px.insert_text(text)
            if not ok:
                raise HangulCommandError("텍스트 삽입에 실패했습니다.")
            return
        try:
            pset = self.com.HParameterSet.HInsertText
            self.com.HAction.GetDefault("InsertText", pset.HSet)
            pset.Text = text
            if not self.com.HAction.Execute("InsertText", pset.HSet):
                raise HangulCommandError("텍스트 삽입에 실패했습니다.")
        except HangulCommandError:
            raise
        except Exception as exc:
            raise HangulCommandError(f"텍스트 삽입에 실패했습니다: {exc}") from exc

    def get_charshape(self) -> Any | None:
        """현재 캐럿의 글자모양 파라미터셋 (insert_title 서식 복원용). 실패 시 None."""
        try:
            return self.px.get_charshape() if self.px else self.com.CharShape
        except Exception:
            return None

    def set_charshape(self, pset: Any) -> bool:
        if pset is None:
            return False
        try:
            if self.px:
                self.px.set_charshape(pset)
            else:
                self.com.CharShape = pset
            return True
        except Exception:
            return False

    def get_parashape(self) -> Any | None:
        try:
            return self.px.get_parashape() if self.px else self.com.ParaShape
        except Exception:
            return None

    def set_parashape(self, pset: Any) -> bool:
        if pset is None:
            return False
        try:
            if self.px:
                self.px.set_parashape(pset)
            else:
                self.com.ParaShape = pset
            return True
        except Exception:
            return False

    def set_font(
        self,
        *,
        bold: bool | None = None,
        italic: bool | None = None,
        superscript: bool | None = None,
        subscript: bool | None = None,
        underline: dict[str, Any] | bool | None = None,
        strikeout: dict[str, Any] | bool | None = None,
        kerning: bool | None = None,
        face: str = "",
        height_pt: float | None = None,
        text_color: str = "",
        text_shadow: dict[str, Any] | None = None,
        letter_spacing_percent: int | None = None,
        width_scale_percent: int | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {}
        if bold is not None:
            kwargs["Bold"] = bold
        if italic is not None:
            kwargs["Italic"] = italic
        if face:
            kwargs["FaceName"] = face
        if height_pt is not None:
            kwargs["Height"] = height_pt
        if text_color:
            rgb = parse_color(text_color)
            kwargs["TextColor"] = rgb_to_bgr_int(rgb)
        if (
            not kwargs
            and text_shadow is None
            and letter_spacing_percent is None
            and width_scale_percent is None
            and superscript is None
            and subscript is None
            and underline is None
            and strikeout is None
            and kerning is None
        ):
            return
        if self.px:
            # pyhwpx does not expose the complete HCharShape shadow/자간/장평 surface.
            # Keep its well-tested font path for normal character attributes,
            # then use the underlying 2022 COM parameter set for the missing fields.
            if kwargs:
                self.px.set_font(**kwargs)
            if (
                text_shadow is None
                and letter_spacing_percent is None
                and width_scale_percent is None
                and superscript is None
                and subscript is None
                and underline is None
                and strikeout is None
                and kerning is None
            ):
                return
        pset = self.com.HParameterSet.HCharShape
        self.com.HAction.GetDefault("CharShape", pset.HSet)
        if "Bold" in kwargs:
            pset.Bold = bool(kwargs["Bold"])
        if "Italic" in kwargs:
            pset.Italic = bool(kwargs["Italic"])
        if superscript is not None and not isinstance(superscript, bool):
            raise UsageError("superscript 값은 true 또는 false여야 합니다.")
        if subscript is not None and not isinstance(subscript, bool):
            raise UsageError("subscript 값은 true 또는 false여야 합니다.")
        if superscript and subscript:
            raise UsageError("superscript와 subscript를 함께 true로 지정할 수 없습니다.")
        if superscript is not None:
            # HCharShape exposes these flags through the backing HSet on
            # Hancom Office 2022.  Direct HCharShape attribute assignment
            # raises AttributeError in the real COM object.
            self._set_pset_item(pset.HSet, "Superscript", bool(superscript))
        if subscript is not None:
            self._set_pset_item(pset.HSet, "Subscript", bool(subscript))
        if superscript:
            self._set_pset_item(pset.HSet, "Subscript", False)
        if subscript:
            self._set_pset_item(pset.HSet, "Superscript", False)
        if underline is not None:
            self._apply_underline(pset, underline)
        if strikeout is not None:
            self._apply_strikeout(pset, strikeout)
        if kerning is not None:
            if not isinstance(kerning, bool):
                raise UsageError("kerning 값은 true 또는 false여야 합니다.")
            self._set_pset_item(pset.HSet, "UseKerning", bool(kerning))
        if "FaceName" in kwargs:
            name = kwargs["FaceName"]
            for attr in (
                "FaceNameHangul",
                "FaceNameLatin",
                "FaceNameHanja",
                "FaceNameJapanese",
                "FaceNameOther",
                "FaceNameSymbol",
                "FaceNameUser",
            ):
                try:
                    setattr(pset, attr, name)
                except Exception:
                    pass
        if "Height" in kwargs:
            try:
                pset.Height = int(float(kwargs["Height"]) * 100)
            except Exception:
                pass
        if "TextColor" in kwargs:
            try:
                pset.TextColor = kwargs["TextColor"]
            except Exception:
                pass
        if letter_spacing_percent is not None:
            spacing = self._number(
                letter_spacing_percent,
                "letter_spacing_percent",
                minimum=-50,
                maximum=50,
            )
            if not spacing.is_integer():
                raise UsageError("letter_spacing_percent 값은 정수여야 합니다.")
            for language in (
                "Hangul",
                "Hanja",
                "Japanese",
                "Latin",
                "Other",
                "Symbol",
                "User",
            ):
                setattr(pset, f"Spacing{language}", int(spacing))
        if width_scale_percent is not None:
            ratio = self._number(
                width_scale_percent,
                "width_scale_percent",
                minimum=50,
                maximum=200,
            )
            if not ratio.is_integer():
                raise UsageError("width_scale_percent 값은 정수여야 합니다.")
            for language in (
                "Hangul",
                "Hanja",
                "Japanese",
                "Latin",
                "Other",
                "Symbol",
                "User",
            ):
                setattr(pset, f"Ratio{language}", int(ratio))
        if text_shadow is not None:
            self._apply_text_shadow(pset, text_shadow, height_pt=height_pt)
        try:
            ok = bool(self.com.HAction.Execute("CharShape", pset.HSet))
        except Exception as exc:
            raise HangulCommandError(f"글자 모양을 적용하지 못했습니다: {exc}") from exc
        if not ok:
            raise HangulCommandError("글자 모양(CharShape) 액션이 실패했습니다.")

    def set_align(self, align: str) -> None:
        mapping = {
            "left": "Left",
            "center": "Center",
            "right": "Right",
            "justify": "Justify",
        }
        key = mapping.get(align.lower() if align else "")
        if not key:
            return
        if self.px:
            self.px.set_para(AlignType=key)
            return
        # AlignType 은 숫자 열거값. 문자열 대입은 실패한다 — HAlign 으로 변환 (pyhwpx set_para 와 동일)
        try:
            pset = self.com.HParameterSet.HParaShape
            self.com.HAction.GetDefault("ParagraphShape", pset.HSet)
            pset.AlignType = self.com.HAlign(key)
            ok = bool(self.com.HAction.Execute("ParagraphShape", pset.HSet))
        except Exception as exc:
            raise HangulCommandError(f"정렬을 적용하지 못했습니다: {exc}") from exc
        if not ok:
            raise HangulCommandError("정렬(ParagraphShape) 액션이 실패했습니다.")

    def set_paragraph_format(
        self,
        *,
        align: str | None = None,
        left_margin_mm: float | None = None,
        right_margin_mm: float | None = None,
        first_line_indent_mm: float | None = None,
        before_spacing_mm: float | None = None,
        after_spacing_mm: float | None = None,
        line_spacing_percent: float | None = None,
        break_latin_word: str | None = None,
        break_non_latin_word: str | None = None,
    ) -> None:
        """현재 문단의 공개 mm/% 레이아웃 사양을 HParaShape에 적용한다.

        HWPML의 ``PARAMARGIN``은 HwpUnit이지만 외부 API는 mm를 사용한다.
        줄간격은 한/글의 비율 방식(``LineSpacingType=0``)으로 고정해 참조
        문서의 90/140/150/160% 같은 값을 보존한다.
        """
        mapping = {
            "left": "Left",
            "center": "Center",
            "right": "Right",
            "justify": "Justify",
        }
        if align is not None and align not in mapping:
            raise UsageError("가로 정렬은 left, center, right, justify 중 하나여야 합니다.")
        for label, value in (
            ("break_latin_word", break_latin_word),
            ("break_non_latin_word", break_non_latin_word),
        ):
            if value is not None and value not in {"keep_word", "break_word"}:
                raise UsageError(f"{label} 값은 keep_word 또는 break_word여야 합니다.")
        fields = {
            "LeftMargin": left_margin_mm,
            "RightMargin": right_margin_mm,
            "Indentation": first_line_indent_mm,
            "PrevSpacing": before_spacing_mm,
            "NextSpacing": after_spacing_mm,
        }
        self.assert_no_dialog()
        try:
            pset = self.com.HParameterSet.HParaShape
            self.com.HAction.GetDefault("ParagraphShape", pset.HSet)
            if align is not None:
                pset.AlignType = self.com.HAlign(mapping[align])
            for name, value in fields.items():
                if value is not None:
                    setattr(pset, name, self._mm_to_hwpunit(float(value)))
            if line_spacing_percent is not None:
                pset.LineSpacing = int(round(float(line_spacing_percent)))
                pset.LineSpacingType = 0
            # HParaShape의 두 항목은 COM bool이다. HWPML에서는 Latin 쪽은
            # KeepWord, 비라틴 쪽은 true로 저장되지만 둘 다 1=단어 유지다.
            if break_latin_word is not None:
                pset.BreakLatinWord = 1 if break_latin_word == "keep_word" else 0
            if break_non_latin_word is not None:
                pset.BreakNonLatinWord = 1 if break_non_latin_word == "keep_word" else 0
            ok = bool(self.com.HAction.Execute("ParagraphShape", pset.HSet))
        except (UsageError, HangulCommandError):
            raise
        except Exception as exc:
            raise HangulCommandError(f"문단 서식을 적용하지 못했습니다: {exc}") from exc
        if not ok:
            raise HangulCommandError("문단 서식(ParagraphShape) 액션이 실패했습니다.")
        self.assert_no_dialog()

    def set_style(self, style: str | int) -> None:
        """현재 문단 스타일을 적용한다. HwpOutlineType/Style 변환 API는 쓰지 않는다."""
        self.assert_no_dialog()
        try:
            if self.px:
                ok = bool(self.px.set_style(style))
            elif isinstance(style, int):
                pset = self.com.HParameterSet.HStyle
                self.com.HAction.GetDefault("Style", pset.HSet)
                pset.Apply = style
                ok = bool(self.com.HAction.Execute("Style", pset.HSet))
            else:
                raise HangulCommandError(
                    "스타일 이름 적용은 pyhwpx 1.7.2가 필요합니다. "
                    "HwpOutlineType/HwpOutlineStyle 직접 호출은 한글 2022에서 실패하므로 사용하지 않습니다."
                )
        except HangulCommandError:
            raise
        except (KeyError, ValueError) as exc:
            raise HangulCommandError(f"문서에서 스타일 '{style}'을 찾지 못했습니다.") from exc
        except Exception as exc:
            raise HangulCommandError(f"스타일 '{style}'을 적용하지 못했습니다: {exc}") from exc
        if not ok:
            raise HangulCommandError(f"스타일 '{style}' 적용 액션이 실패했습니다.")
        self.assert_no_dialog()

    def create_table(self, rows: int, cols: int, header: bool = True) -> None:
        if rows < 1 or cols < 1:
            raise UsageError("행과 열은 1 이상이어야 합니다.")
        if self.px:
            ok = self.px.create_table(rows=rows, cols=cols, treat_as_char=True, header=header)
            if not ok:
                raise HangulCommandError("표 만들기에 실패했습니다.")
            return
        pset = self.com.HParameterSet.HTableCreation
        self.com.HAction.GetDefault("TableCreate", pset.HSet)
        pset.Rows = rows
        pset.Cols = cols
        try:
            pset.WidthType = 2
            pset.HeightType = 1
        except Exception:
            pass
        try:
            pset.CreateHeader = 1 if header else 0
        except Exception:
            pass
        if not self.com.HAction.Execute("TableCreate", pset.HSet):
            raise HangulCommandError("표 만들기에 실패했습니다.")

    def get_into_nth_table(self, n: int = 0) -> None:
        if self.px:
            self.px.get_into_nth_table(n=n, select_cell=False)
            return
        tables = self._table_ctrls()
        if n < 0 or n >= len(tables):
            raise HangulCommandError(f"{n}번 표를 찾지 못했습니다.")
        ctrl = tables[n]
        try:
            pos = ctrl.GetAnchorPos(0)
            self.com.SetPos(pos.Item("List"), pos.Item("Para"), pos.Item("Pos"))
        except Exception as exc:
            raise HangulCommandError(f"{n}번 표로 이동하지 못했습니다: {exc}") from exc
        try:
            # 앵커 위치의 컨트롤(표)을 선택해야 ShapeObjTableSelCell 이 셀로 들어간다 (2022 방식).
            self.com.FindCtrl()
        except Exception:
            pass
        self.run("ShapeObjTableSelCell")
        if not self.is_cell():
            self.run("TableLeftCell")
        if not self.is_cell():
            raise HangulCommandError(f"{n}번 표 안으로 들어가지 못했습니다.")

    def goto_addr(self, addr: str) -> None:
        if self.px:
            if not self.px.goto_addr(addr=addr, select_cell=False):
                raise HangulCommandError(f"셀 {addr} 로 이동하지 못했습니다.")
            return
        # COM 폴백: 이동 액션의 반환값을 전부 검사하고, KeyIndicator 로 결과 주소를 검증한다.
        # (이전 구현은 실패를 무시해 캐럿이 본문에 남은 채 SelectAll → 문서 전체 교체 사고 가능)
        _parse_a1(addr)  # 형식 검증
        if not self.is_cell():
            raise HangulCommandError(
                f"캐럿이 표 안에 있지 않아 셀 {addr} 로 이동할 수 없습니다."
            )
        # A1 로: TableColBegin(행의 첫 칸) + TableColPageUp(열의 첫 행)
        if not self.run("TableColBegin") or not self.run("TableColPageUp"):
            raise HangulCommandError(f"셀 {addr} 로 이동하지 못했습니다 (표 시작 이동 실패).")
        # 병합 표에서는 TableRightCell이 병합 셀의 좌상단 주소를 한 번 더
        # 보고할 수 있다. 예: A1:C2 병합 뒤 순서는 A1 → D1 → A1 → D2
        # → A3 ... 이다. 중복 주소를 "순회 종료"로 취급하면 A3 이하에
        # 도달할 수 없어, 두 번째 병합/셀 채우기가 실패한다. 액션의 False를
        # 유일한 종료 신호로 쓰고, 실제 한/글이 보고하는 순서를 끝까지 따른다.
        want = addr.strip().upper()
        for _ in range(5000):
            if not self.is_cell():
                raise HangulCommandError(f"셀 {addr} 이동 후 캐럿이 표 밖에 있습니다.")
            current = self.current_cell_addr()
            if current == want:
                return
            if not current:
                break
            if not self.run("TableRightCell"):
                break
        current = self.current_cell_addr()
        raise HangulCommandError(
            f"셀 이동 결과가 다릅니다 (요청 {want}, 현재 {current or '알 수 없음'}). "
            "표 크기를 벗어난 주소이거나 병합으로 사라진 셀일 수 있습니다."
        )

    def current_cell_addr(self) -> str:
        """상태 바(KeyIndicator)의 컨트롤 이름에서 현재 셀 주소를 읽는다. 실패 시 ""."""
        try:
            info = self.px.key_indicator() if self.px else self.com.KeyIndicator()
            ctrlname = str(info[-1])
            if "(" in ctrlname and ")" in ctrlname:
                return ctrlname.split("(", 1)[1].split(")", 1)[0].strip().upper()
        except Exception:
            pass
        return ""

    def cell_fill(self, color: str) -> None:
        rgb = parse_color(color)
        if self.px:
            self.px.cell_fill(face_color=rgb)
            return
        # pyhwpx cell_fill 소스와 동일한 아이템 이름 사용 (WinBrushFaceColor 등).
        # 이전 구현의 FillAttr.Type / FillAttr.FaceColor 는 존재하지 않는 아이템이었다.
        ok = False
        try:
            pset = self.com.HParameterSet.HCellBorderFill
            self.com.HAction.GetDefault("CellFill", pset.HSet)
            fill = pset.FillAttr
            fill.type = self.com.BrushType("NullBrush|WinBrush")
            fill.WinBrushFaceColor = self._rgb_value(rgb)
            fill.WinBrushHatchColor = self._rgb_value((153, 153, 153))
            fill.WinBrushFaceStyle = self.com.HatchStyle("None")
            fill.WindowsBrush = 1
            ok = bool(self.com.HAction.Execute("CellFill", pset.HSet))
        except Exception as exc:
            raise HangulCommandError(f"셀 배경을 칠하지 못했습니다: {exc}") from exc
        finally:
            try:
                self.run("Cancel")
            except Exception:
                pass
        if not ok:
            raise HangulCommandError("셀 배경 칠하기(CellFill) 액션이 실패했습니다.")

    def _rgb_value(self, rgb: tuple[int, int, int]) -> int:
        try:
            return int(self.com.RGBColor(*rgb))
        except Exception:
            return rgb_to_bgr_int(rgb)

    # --- 도형/그라데이션 -------------------------------------------------

    @staticmethod
    def _number(
        value: Any,
        label: str,
        *,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> float:
        """공개 명령 입력을 COM 호출 전에 엄격히 숫자로 정규화한다."""
        if isinstance(value, bool):
            raise UsageError(f"{label} 값은 숫자여야 합니다.")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise UsageError(f"{label} 값은 숫자여야 합니다.") from exc
        if not math.isfinite(number):
            raise UsageError(f"{label} 값은 유한한 숫자여야 합니다.")
        if minimum is not None and number < minimum:
            raise UsageError(f"{label} 값은 {minimum:g} 이상이어야 합니다.")
        if maximum is not None and number > maximum:
            raise UsageError(f"{label} 값은 {maximum:g} 이하여야 합니다.")
        return number

    @staticmethod
    def _mapping(value: Any, label: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise UsageError(f"{label}은(는) 객체여야 합니다.")
        return value

    def _set_pset_item(self, pset: Any, name: str, value: Any) -> None:
        """COM ParameterSet/테스트 더블 모두에서 항목을 설정한다."""
        try:
            pset.SetItem(name, value)
        except Exception:
            try:
                setattr(pset, name, value)
            except Exception as exc:
                raise HangulCommandError(
                    f"한/글 파라미터 '{name}'을(를) 설정하지 못했습니다: {exc}"
                ) from exc

    def _enum(self, factory: str, name: str, fallback: int) -> int:
        """실제 한/글 열거형을 우선 쓰되 COM 스텁에서도 검증 가능하게 한다."""
        try:
            return int(getattr(self.com, factory)(name))
        except Exception:
            return fallback

    def _underline_type(self, enabled: bool) -> int:
        """boolean 공개 API를 한/글 밑줄 위치 열거형으로 바꾼다."""
        return self._enum(
            "HwpUnderlineType",
            "Bottom" if enabled else "None",
            1 if enabled else 0,
        )

    def _strikeout_type(self, enabled: bool) -> int:
        """boolean 공개 API를 한/글 한 줄 취소선 열거형으로 바꾼다."""
        return self._enum(
            "HwpStrikeOutType",
            "Continuous" if enabled else "None",
            1 if enabled else 0,
        )

    @staticmethod
    def _text_decoration_spec(
        value: dict[str, Any] | bool,
        label: str,
        *,
        default_type: str,
    ) -> dict[str, Any]:
        """Engine 정규화 값을 다시 확인해 Canvas 직접 호출도 안전하게 한다."""
        if isinstance(value, bool):
            return {"enabled": value, "type": default_type, "shape": "solid"}
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
        raw_type = value.get("type", default_type)
        if not isinstance(raw_type, str) or raw_type.strip().lower().replace("-", "_") != default_type:
            raise UsageError(f"{label}.type 은 {default_type}이어야 합니다.")
        raw_shape = value.get("shape", "solid")
        if not isinstance(raw_shape, str) or raw_shape.strip().lower().replace("-", "_") != "solid":
            raise UsageError(f"{label}.shape 은 solid여야 합니다.")
        out = {"enabled": enabled, "type": default_type, "shape": "solid"}
        if "color" in value:
            color = value["color"]
            if not isinstance(color, str):
                raise UsageError(f"{label}.color는 색 문자열이어야 합니다.")
            # parse_color로 Canvas 직호출에도 같은 색 범위 검증을 보장한다.
            parse_color(color)
            out["color"] = color
        return out

    def _apply_underline(self, pset: Any, value: dict[str, Any] | bool) -> None:
        spec = self._text_decoration_spec(value, "underline", default_type="bottom")
        enabled = bool(spec["enabled"])
        self._set_pset_item(pset, "UnderlineType", self._underline_type(enabled))
        if not enabled:
            return
        self._set_pset_item(pset, "UnderlineShape", self._enum("HwpUnderlineShape", "Solid", 1))
        if "color" in spec:
            self._set_pset_item(pset, "UnderlineColor", self._rgb_value(parse_color(spec["color"])))

    def _apply_strikeout(self, pset: Any, value: dict[str, Any] | bool) -> None:
        spec = self._text_decoration_spec(value, "strikeout", default_type="continuous")
        enabled = bool(spec["enabled"])
        self._set_pset_item(pset, "StrikeOutType", self._strikeout_type(enabled))
        if not enabled:
            return
        self._set_pset_item(pset, "StrikeOutShape", self._enum("HwpStrikeOutShape", "Solid", 1))
        if "color" in spec:
            self._set_pset_item(pset, "StrikeOutColor", self._rgb_value(parse_color(spec["color"])))

    def _gradient(self, fill: Any) -> tuple[float, list[tuple[float, tuple[int, int, int]]]]:
        spec = self._mapping(fill, "채우기")
        kind = str(spec.get("type", "")).strip().lower()
        if kind not in {"linear_gradient", "radial_gradient"}:
            raise UsageError("채우기 type은 linear_gradient 또는 radial_gradient여야 합니다.")
        angle = self._number(spec.get("angle"), "그라데이션 각도", minimum=0.0)
        if angle >= 360.0:
            raise UsageError("그라데이션 각도는 360 미만이어야 합니다.")
        raw_stops = spec.get("stops")
        if not isinstance(raw_stops, (list, tuple)) or not 2 <= len(raw_stops) <= 10:
            raise UsageError("그라데이션 stops는 2개 이상 10개 이하여야 합니다.")

        stops: list[tuple[float, tuple[int, int, int]]] = []
        previous = -1.0
        for index, raw_stop in enumerate(raw_stops):
            stop = self._mapping(raw_stop, f"그라데이션 stops[{index}]")
            offset = self._number(
                stop.get("offset"), f"그라데이션 stops[{index}].offset", minimum=0.0, maximum=1.0
            )
            if offset < previous:
                raise UsageError("그라데이션 stops의 offset은 오름차순이어야 합니다.")
            color = stop.get("color")
            if not isinstance(color, str):
                raise UsageError(f"그라데이션 stops[{index}].color는 색 문자열이어야 합니다.")
            stops.append((offset, parse_color(color)))
            previous = offset
        if abs(stops[0][0]) > 1e-9 or abs(stops[-1][0] - 1.0) > 1e-9:
            raise UsageError("그라데이션 stops는 offset 0에서 시작해 1에서 끝나야 합니다.")
        return angle, stops

    def _set_item_array(self, pset: Any, name: str, values: list[int]) -> None:
        try:
            array = pset.CreateItemArray(name, len(values))
        except Exception as exc:
            raise HangulCommandError(
                f"한/글 그라데이션 배열 '{name}'을(를) 만들지 못했습니다: {exc}"
            ) from exc
        if array is None:
            raise HangulCommandError(f"한/글 그라데이션 배열 '{name}'을(를) 만들지 못했습니다.")
        for index, value in enumerate(values):
            try:
                array.SetItem(index, int(value))
            except Exception as exc:
                raise HangulCommandError(
                    f"한/글 그라데이션 배열 '{name}[{index}]'을(를) 설정하지 못했습니다: {exc}"
                ) from exc

    def _apply_gradient(self, fill_pset: Any, fill: Any) -> None:
        """HDrawFillAttr에 공개 선형/방사형 그라데이션을 쓴다.

        한/글 2022는 ``GradationColor``/``GradationIndexPos`` 배열을 각각
        10칸만 제공한다. Engine 검증과 별개로 여기서도 10개를 넘기지 않는다.
        """
        spec = self._mapping(fill, "채우기")
        kind = str(spec.get("type", "")).strip().lower()
        if kind not in {"linear_gradient", "radial_gradient"}:
            raise UsageError("채우기 type은 linear_gradient 또는 radial_gradient여야 합니다.")
        angle, stops = self._gradient(fill)
        colors = [self._rgb_value(color) for _offset, color in stops]
        # 두 색의 기본 선형 그라데이션은 IndexPos가 모두 0인 한/글 기본
        # 배치를 쓴다. 3색 이상은 공개 stop 위치(%)를 전달한다.
        positions = (
            [0] * len(stops)
            if len(stops) == 2
            else [int(round(offset * 100.0)) for offset, _color in stops]
        )
        self._set_pset_item(
            fill_pset,
            "Type",
            self._enum("BrushType", "NullBrush|GradBrush", 4),
        )
        if kind == "radial_gradient":
            values: dict[str, int] = {}
            for name, default in (
                ("center_x", 50),
                ("center_y", 50),
                ("step", 100),
                ("step_center", 50),
            ):
                value = self._number(
                    spec.get(name, default),
                    f"방사형 그라데이션 {name}",
                    minimum=0.0,
                    maximum=100.0,
                )
                if not value.is_integer():
                    raise UsageError(f"방사형 그라데이션 {name}는 0~100 정수여야 합니다.")
                values[name] = int(value)
            gradation_type = self._enum("Gradation", "Radial", 2)
            center_x = values["center_x"]
            center_y = values["center_y"]
            step = values["step"]
            step_center = values["step_center"]
        else:
            gradation_type = self._enum("Gradation", "Linear", 1)
            center_x = 0
            center_y = 0
            step = 100
            step_center = 50
        self._set_pset_item(fill_pset, "GradationType", gradation_type)
        self._set_pset_item(fill_pset, "GradationCenterX", center_x)
        self._set_pset_item(fill_pset, "GradationCenterY", center_y)
        self._set_pset_item(fill_pset, "GradationAngle", int(round(angle)))
        self._set_pset_item(fill_pset, "GradationStep", step)
        self._set_pset_item(fill_pset, "GradationStepCenter", step_center)
        self._set_pset_item(fill_pset, "GradationColorNum", len(colors))
        self._set_item_array(
            fill_pset, "GradationColor", colors + [colors[0]] * (10 - len(colors))
        )
        self._set_item_array(
            fill_pset, "GradationIndexPos", positions + [0] * (10 - len(positions))
        )
        self._set_pset_item(fill_pset, "GradationBrush", 1)

    def _apply_linear_gradient(self, fill_pset: Any, fill: Any) -> None:
        """호환용 내부 별칭. 공개 호출은 ``_apply_fill``만 사용한다."""
        self._apply_gradient(fill_pset, fill)

    def _apply_radial_gradient(self, fill_pset: Any, fill: Any) -> None:
        self._apply_gradient(fill_pset, fill)

    def _apply_solid_fill(self, fill_pset: Any, color: str) -> None:
        rgb = parse_color(color)
        color_value = self._rgb_value(rgb)
        self._set_pset_item(
            fill_pset,
            "Type",
            self._enum("BrushType", "NullBrush|WinBrush", 1),
        )
        self._set_pset_item(fill_pset, "WinBrushFaceColor", color_value)
        self._set_pset_item(fill_pset, "WinBrushHatchColor", color_value)
        self._set_pset_item(
            fill_pset,
            "WinBrushFaceStyle",
            self._enum("HatchStyle", "None", 0),
        )
        self._set_pset_item(fill_pset, "WindowsBrush", 1)

    def _apply_fill(self, fill_pset: Any, fill: Any) -> None:
        spec = self._mapping(fill, "채우기")
        kind = str(spec.get("type", "")).strip().lower()
        if kind == "solid":
            color = spec.get("color")
            if not isinstance(color, str):
                raise UsageError("단색 채우기의 color는 색 문자열이어야 합니다.")
            self._apply_solid_fill(fill_pset, color)
            return
        if kind == "linear_gradient":
            self._apply_linear_gradient(fill_pset, spec)
            return
        if kind == "radial_gradient":
            self._apply_radial_gradient(fill_pset, spec)
            return
        raise UsageError("채우기 type은 solid, linear_gradient 또는 radial_gradient여야 합니다.")

    def _shadow(self, shadow: Any, label: str) -> tuple[str, tuple[int, int, int], int, float, float]:
        spec = self._mapping(shadow, label)
        kind = str(spec.get("type", "")).strip().lower()
        if kind == "none":
            return ("none", (0, 0, 0), 0, 0.0, 0.0)
        if kind != "offset":
            raise UsageError(f"{label} type은 none 또는 offset이어야 합니다.")
        color = spec.get("color")
        if not isinstance(color, str):
            raise UsageError(f"{label} color는 색 문자열이어야 합니다.")
        alpha_number = self._number(spec.get("alpha", 0), f"{label} alpha", minimum=0, maximum=255)
        if not alpha_number.is_integer():
            raise UsageError(f"{label} alpha는 정수여야 합니다.")
        x = self._number(spec.get("offset_x_mm", 0), f"{label} 가로 오프셋", minimum=-50, maximum=50)
        y = self._number(spec.get("offset_y_mm", 0), f"{label} 세로 오프셋", minimum=-50, maximum=50)
        return ("offset", parse_color(color), int(alpha_number), x, y)

    def _apply_text_shadow(
        self, pset: Any, shadow: Any, *, height_pt: float | None = None
    ) -> None:
        """HCharShape 그림자를 적용한다.

        HCharShape의 ShadowOffsetX/Y는 HwpUnit가 아니라 글자 크기 대비
        signed percentage(PIT_I1)다. 따라서 공개 mm 입력을 현재 글자 크기에
        맞춰 변환한다. 한/글 2022 HCharShape에는 ShadowAlpha가 없다.
        """
        kind, color, alpha, x_mm, y_mm = self._shadow(shadow, "글자 그림자")
        if alpha:
            raise UsageError("한/글 2022 글자 그림자는 alpha 0만 지원합니다.")
        if kind == "none":
            self._set_pset_item(
                pset,
                "ShadowType",
                self._enum("CharShadowType", "None", 0),
            )
            return
        font_pt = height_pt
        if font_pt is None:
            try:
                font_pt = float(pset.Height) / 100.0
            except Exception:
                font_pt = 10.0
        font_pt = self._number(font_pt, "글자 크기", minimum=0.01)
        font_mm = font_pt * 25.4 / 72.0
        x = int(round(x_mm / font_mm * 100.0))
        y = int(round(y_mm / font_mm * 100.0))
        if not -100 <= x <= 100 or not -100 <= y <= 100:
            raise UsageError(
                "글자 그림자 오프셋은 현재 글자 크기 기준 -100%~100% 범위를 벗어났습니다."
            )
        self._set_pset_item(
            pset,
            "ShadowType",
            self._enum("CharShadowType", "Drop", 1),
        )
        self._set_pset_item(pset, "ShadowColor", self._rgb_value(color))
        self._set_pset_item(pset, "ShadowOffsetX", x)
        self._set_pset_item(pset, "ShadowOffsetY", y)

    def _apply_shape_shadow(self, owner_pset: Any, shadow: Any) -> None:
        shape_shadow = owner_pset.CreateItemSet("ShapeDrawShadow", "DrawShadow")
        kind, color, alpha, x_mm, y_mm = self._shadow(shadow, "도형 그림자")
        if kind == "none":
            self._set_pset_item(
                shape_shadow,
                "ShadowType",
                self._enum("DrawShadowType", "None", 0),
            )
            return
        # DrawShadow의 오프셋은 HwpUnit이며 Alpha는 0=불투명, 255=투명이다.
        self._set_pset_item(
            shape_shadow,
            "ShadowType",
            self._enum("DrawShadowType", "ParellelRightBottom", 4),
        )
        self._set_pset_item(shape_shadow, "ShadowColor", self._rgb_value(color))
        self._set_pset_item(shape_shadow, "ShadowOffsetX", self._mm_to_hwpunit(x_mm))
        self._set_pset_item(shape_shadow, "ShadowOffsetY", self._mm_to_hwpunit(y_mm))
        self._set_pset_item(shape_shadow, "ShadowAlpha", alpha)

    def _apply_shape_line(self, owner_pset: Any, line: Any) -> None:
        spec, kind, color, width, widths = self._shape_line_values(line)
        line_pset = owner_pset.CreateItemSet("ShapeDrawLineAttr", "DrawLineAttr")
        if kind == "none":
            self._set_pset_item(
                line_pset,
                "Style",
                self._enum("HwpLineType", "None", 0),
            )
            return
        if width == 0:
            self._set_pset_item(
                line_pset,
                "Style",
                self._enum("HwpLineType", "None", 0),
            )
            return
        selected = next((value for value in widths if abs(value - width) < 1e-9), None)
        assert selected is not None
        self._set_pset_item(
            line_pset,
            "Style",
            self._enum("HwpLineType", "Solid", 1),
        )
        self._set_pset_item(line_pset, "Color", self._rgb_value(parse_color(color)))
        self._set_pset_item(
            line_pset,
            "Width",
            self._enum("HwpLineWidth", widths[selected], int(list(widths).index(selected))),
        )

    def _shape_line_values(
        self, line: Any
    ) -> tuple[dict[str, Any], str, str, float, dict[float, str]]:
        spec = self._mapping(line, "도형 테두리")
        kind = str(spec.get("type", "")).strip().lower()
        widths = {
            0.1: "0.1mm", 0.12: "0.12mm", 0.15: "0.15mm", 0.2: "0.2mm",
            0.25: "0.25mm", 0.3: "0.3mm", 0.4: "0.4mm", 0.5: "0.5mm",
            0.6: "0.6mm", 0.7: "0.7mm", 1.0: "1.0mm", 1.5: "1.5mm",
            2.0: "2.0mm", 3.0: "3.0mm", 4.0: "4.0mm", 5.0: "5.0mm",
        }
        if kind == "none":
            return spec, kind, "", 0.0, widths
        if kind != "solid":
            raise UsageError("도형 테두리 type은 none 또는 solid여야 합니다.")
        color = spec.get("color")
        if not isinstance(color, str):
            raise UsageError("단색 도형 테두리의 color는 색 문자열이어야 합니다.")
        parse_color(color)
        width = self._number(spec.get("width_mm", 0), "도형 테두리 두께", minimum=0)
        if width and not any(abs(value - width) < 1e-9 for value in widths):
            allowed = ", ".join(f"{value:g}" for value in widths)
            raise UsageError(f"도형 테두리 두께는 한/글 지원값({allowed}mm) 중 하나여야 합니다.")
        return spec, kind, color, width, widths

    def set_cell_fill(self, fill: dict[str, Any]) -> int:
        """현재 선택 셀 범위에 단색/선형/방사형 그라데이션을 적용한다."""
        spec = self._mapping(fill, "셀 채우기")
        kind = str(spec.get("type", "")).strip().lower()
        if kind == "solid":
            color = spec.get("color")
            if not isinstance(color, str):
                raise UsageError("단색 셀 채우기의 color는 색 문자열이어야 합니다.")
            self.cell_fill(color)
            return 1
        if kind not in {"linear_gradient", "radial_gradient"}:
            raise UsageError("셀 채우기 type은 solid, linear_gradient 또는 radial_gradient여야 합니다.")
        # Validate before touching the document; this also enforces the 10-stop limit.
        self._gradient(spec)
        self.assert_no_dialog()
        ok = False
        try:
            action = self.com.CreateAction("CellFill")
            if action is None:
                raise HangulCommandError("셀 배경(CellFill) 액션을 만들지 못했습니다.")
            pset = action.CreateSet()
            action.GetDefault(pset)
            fill_pset = pset.CreateItemSet("FillAttr", "DrawFillAttr")
            self._apply_gradient(fill_pset, spec)
            ok = bool(action.Execute(pset))
        except HangulCommandError:
            raise
        except Exception as exc:
            raise HangulCommandError(f"셀 그라데이션을 적용하지 못했습니다: {exc}") from exc
        finally:
            try:
                self.run("Cancel")
            except Exception:
                pass
        if not ok:
            raise HangulCommandError("셀 그라데이션(CellFill) 액션이 실패했습니다.")
        self.assert_no_dialog()
        return 1

    def _validate_text_box_margin(self, margin: Any) -> tuple[float, float, float, float] | None:
        if margin is None:
            return None
        if not isinstance(margin, (list, tuple)) or len(margin) != 4:
            raise UsageError("글상자 margin은 (left, right, top, bottom) 네 값이어야 합니다.")
        return tuple(
            self._number(value, "글상자 안쪽 여백", minimum=0) for value in margin
        )  # type: ignore[return-value]

    def _apply_text_box_margin(self, margin: tuple[float, float, float, float] | None) -> None:
        """선택된 글상자의 안쪽 여백을 ShapeObjDialog로 적용한다.

        HWP 2022는 이 값을 ShapeObject 액션에서만 갱신한다. 지원하지 않는
        설치본에서 기본 여백으로 조용히 성공 처리하면 재현성이 깨지므로,
        호출자에게 명시적으로 실패를 돌려준다.
        """
        if margin is None:
            return
        try:
            pset = self.com.HParameterSet.HShapeObject
            self.com.HAction.GetDefault("ShapeObjDialog", pset.HSet)
            text_box = pset.CreateItemSet("ShapeDrawTextBox", "DrawTextBox")
            left, right, top, bottom = (self._mm_to_hwpunit(value) for value in margin)
            for name, value in (
                ("MarginLeft", left), ("MarginRight", right),
                ("MarginTop", top), ("MarginBottom", bottom),
            ):
                self._set_pset_item(text_box, name, value)
            if not bool(self.com.HAction.Execute("ShapeObjDialog", pset.HSet)):
                raise HangulCommandError("글상자 안쪽 여백(ShapeObjDialog) 액션이 실패했습니다.")
        except HangulCommandError:
            raise
        except Exception as exc:
            raise HangulCommandError(
                "글상자 안쪽 여백을 적용하지 못했습니다. "
                "현재 한/글 2022 설치본이 DrawTextBox 여백 쓰기를 지원하는지 확인하세요."
            ) from exc

    def insert_text_box(
        self,
        text: str,
        width_mm: float,
        height_mm: float,
        *,
        fill: dict[str, Any] | None = None,
        line: dict[str, Any] | None = None,
        shadow: dict[str, Any] | None = None,
        text_shadow: dict[str, Any] | None = None,
        margin: tuple[float, float, float, float] | list[float] | None = None,
        align: str = "left",
        position: dict[str, Any] | None = None,
        bold: bool | None = None,
        italic: bool | None = None,
        font: str = "",
        size: float | None = None,
        color: str = "",
        # Legacy internal aliases are retained so callers on older branches
        # can share this adapter while public callers use font/size/color.
        face: str = "",
        height_pt: float | None = None,
        text_color: str = "",
    ) -> int:
        """현재 캐럿에 편집 가능한 한/글 글상자를 만든다.

        저장된 그림이나 HWPML 주입이 아니라 DrawObjCreatorTextBox →
        ShapeObjTextBoxEdit → InsertText 공개 COM 액션만 쓴다.
        """
        if not isinstance(text, str):
            raise UsageError("글상자 text는 문자열이어야 합니다.")
        width = self._number(width_mm, "글상자 너비", minimum=0.01)
        height = self._number(height_mm, "글상자 높이", minimum=0.01)
        margins = self._validate_text_box_margin(margin)
        if fill is not None:
            self._mapping(fill, "글상자 채우기")
            if str(fill.get("type", "")).strip().lower() == "linear_gradient":
                self._gradient(fill)
            elif str(fill.get("type", "")).strip().lower() == "solid":
                raw_color = fill.get("color")
                if not isinstance(raw_color, str):
                    raise UsageError("단색 글상자 채우기의 color는 색 문자열이어야 합니다.")
                parse_color(raw_color)
            else:
                raise UsageError("글상자 채우기 type은 solid 또는 linear_gradient여야 합니다.")
        if line is not None:
            self._shape_line_values(line)
        if shadow is not None:
            self._shadow(shadow, "도형 그림자")
        if text_shadow is not None:
            _kind, _color, alpha, _x, _y = self._shadow(text_shadow, "글자 그림자")
            if alpha:
                raise UsageError("한/글 2022 글자 그림자는 alpha 0만 지원합니다.")

        alignment = str(align or "").strip().lower()
        if alignment not in {"left", "center", "right", "justify"}:
            raise UsageError("글상자 align은 left, center, right, justify 중 하나여야 합니다.")
        pos = {"mode": "inline"} if position is None else self._mapping(position, "글상자 position")
        mode = str(pos.get("mode", "")).strip().lower()
        if mode not in {"inline", "floating"}:
            raise UsageError("글상자 position.mode는 inline 또는 floating이어야 합니다.")
        x_mm = y_mm = 0.0
        if mode == "floating":
            x_mm = self._number(pos.get("x_mm"), "글상자 x 좌표")
            y_mm = self._number(pos.get("y_mm"), "글상자 y 좌표")

        # Prefer canonical public style names; aliases only fill gaps.
        actual_face = font or face
        actual_size = size if size is not None else height_pt
        actual_color = color or text_color
        original_pos = self.get_pos()
        anchor: Any | None = None
        entered_text_box = False
        self.assert_no_dialog()
        try:
            action = self.com.CreateAction("DrawObjCreatorTextBox")
            if action is None:
                raise HangulCommandError("글상자 만들기 액션을 만들지 못했습니다.")
            pset = action.CreateSet()
            action.GetDefault(pset)
            self._set_pset_item(pset, "Width", self._mm_to_hwpunit(width))
            self._set_pset_item(pset, "Height", self._mm_to_hwpunit(height))
            self._set_pset_item(pset, "TreatAsChar", 1 if mode == "inline" else 0)
            if mode == "floating":
                self._set_pset_item(pset, "VertRelTo", self._enum("VertRel", "Paper", 0))
                self._set_pset_item(pset, "VertAlign", self._enum("VAlign", "Top", 0))
                self._set_pset_item(pset, "VertOffset", self._mm_to_hwpunit(y_mm))
                self._set_pset_item(pset, "HorzRelTo", self._enum("HorzRel", "Paper", 0))
                self._set_pset_item(pset, "HorzAlign", self._enum("HAlign", "Left", 1))
                self._set_pset_item(pset, "HorzOffset", self._mm_to_hwpunit(x_mm))
                self._set_pset_item(pset, "TextWrap", self._enum("TextWrapType", "Square", 0))
                self._set_pset_item(pset, "FlowWithText", 1)
                self._set_pset_item(pset, "AllowOverlap", 1)
            if fill is not None:
                self._apply_fill(pset.CreateItemSet("ShapeDrawFillAttr", "DrawFillAttr"), fill)
            if line is not None:
                self._apply_shape_line(pset, line)
            if shadow is not None:
                self._apply_shape_shadow(pset, shadow)
            if not bool(action.Execute(pset)):
                raise HangulCommandError("글상자 만들기(DrawObjCreatorTextBox) 액션이 실패했습니다.")

            ctrl = self.com.LastCtrl
            if ctrl is None or str(getattr(ctrl, "CtrlID", "")) != "gso":
                raise HangulCommandError("글상자는 만들어졌지만 선택할 수 없습니다.")
            anchor = ctrl.GetAnchorPos(0)
            self.com.SetPosBySet(anchor)
            self.com.FindCtrl()
            self._apply_text_box_margin(margins)
            if not bool(self.com.HAction.Run("ShapeObjTextBoxEdit")):
                raise HangulCommandError("글상자 편집 모드로 들어가지 못했습니다.")
            entered_text_box = True
            self.set_font(
                bold=bold,
                italic=italic,
                face=actual_face,
                height_pt=actual_size,
                text_color=actual_color,
                text_shadow=text_shadow,
            )
            self.set_align(alignment)
            if text:
                self.insert_text(text)
        except HangulCommandError:
            if entered_text_box:
                self._restore_text_box_cursor(original_pos, anchor)
            raise
        except Exception as exc:
            if entered_text_box:
                self._restore_text_box_cursor(original_pos, anchor)
            raise HangulCommandError(f"글상자를 만들지 못했습니다: {exc}") from exc
        if not self._restore_text_box_cursor(original_pos, anchor):
            raise HangulCommandError(
                "글상자 편집을 마친 뒤 문서 캐럿을 복원하지 못했습니다. "
                "다음 명령이 글상자 안에 쓰이지 않도록 작업을 중단했습니다."
            )
        self.assert_no_dialog()
        return 1

    def _restore_text_box_cursor(self, original_pos: tuple | None, anchor: Any | None) -> bool:
        """글상자 편집 모드가 다음 명령으로 새지 않도록 본문 캐럿을 복구한다."""
        if original_pos is not None and self.set_pos(original_pos):
            return True
        if anchor is None:
            return False
        try:
            # 개체 앵커로 직접 이동하면 ShapeObjTextBoxEdit의 내부 캐럿을
            # 벗어난다. 원래 위치를 읽지 못한 드문 COM 빌드의 안전한 폴백이다.
            self.com.SetPosBySet(anchor)
            return True
        except Exception:
            return False

    def insert_picture(
        self,
        path: str,
        size_option: int = 3,
        width_mm: float = 0.0,
        height_mm: float = 0.0,
        embedded: bool = True,
    ) -> None:
        """캐럿 위치에 그림 파일을 넣는다 (한/글 ``InsertPicture``).

        ``size_option`` 0=원본 크기, 1=width/height 지정, 2=셀 크기에 맞춤,
        3=셀 크기에 맞추되 비율 유지. 2/3 은 캐럿이 표 셀 안일 때만 뜻이 있다.
        ``embedded=True`` 면 문서에 포함되므로 원본 파일이 사라져도 그림이 남는다.
        """
        self.assert_no_dialog()
        width = self._mm_to_hwpunit(width_mm) if width_mm else 0
        height = self._mm_to_hwpunit(height_mm) if height_mm else 0
        try:
            ctrl = self.com.InsertPicture(
                path, bool(embedded), int(size_option), False, False, 0, width, height
            )
        except Exception as exc:
            raise HangulCommandError(f"그림 삽입에 실패했습니다: {exc}") from exc
        if ctrl is None:
            raise HangulCommandError(
                "그림 삽입에 실패했습니다 (한/글이 그림 개체를 만들지 못했습니다). "
                "파일 형식이 한/글에서 열리는 그림인지 확인하세요."
            )
        self.assert_no_dialog()

    def _mm_to_hwpunit(self, mm: float) -> int:
        try:
            return int(self.com.MiliToHwpUnit(mm))
        except Exception:
            return int(round(mm * 7200 / 25.4))  # 1 inch = 25.4mm = 7200 HwpUnit

    def set_cell_margin_current(
        self, left: float, right: float, top: float, bottom: float
    ) -> None:
        """캐럿이 있는 셀(또는 다중선택 셀들)의 안쪽 여백을 mm 로 지정."""
        self.assert_no_dialog()
        if self.px:
            if not self.px.set_cell_margin(
                left=left, right=right, top=top, bottom=bottom, as_="mm"
            ):
                raise HangulCommandError(
                    "셀 안 여백을 적용하지 못했습니다. 캐럿이 표 셀 안에 있어야 합니다."
                )
            self.assert_no_dialog()
            return
        if not self.is_cell():
            raise HangulCommandError(
                "캐럿이 표 셀 안에 있지 않아 셀 안 여백을 적용할 수 없습니다."
            )
        # pyhwpx set_cell_margin 소스와 동일: TablePropertyDialog + ShapeTableCell.Margin*
        ok = False
        try:
            pset = self.com.HParameterSet.HShapeObject
            self.com.HAction.GetDefault("TablePropertyDialog", pset.HSet)
            pset.HSet.SetItem("ShapeType", 3)
            pset.HSet.SetItem("ShapeCellSize", 0)
            cell = pset.ShapeTableCell
            cell.HasMargin = 1
            cell.MarginLeft = self._mm_to_hwpunit(left)
            cell.MarginRight = self._mm_to_hwpunit(right)
            cell.MarginTop = self._mm_to_hwpunit(top)
            cell.MarginBottom = self._mm_to_hwpunit(bottom)
            ok = bool(self.com.HAction.Execute("TablePropertyDialog", pset.HSet))
        except Exception as exc:
            raise HangulCommandError(f"셀 안 여백 적용에 실패했습니다: {exc}") from exc
        if not ok:
            raise HangulCommandError("셀 안 여백(TablePropertyDialog) 액션이 실패했습니다.")
        self.assert_no_dialog()

    def set_table_inside_margin(
        self, left: float, right: float, top: float, bottom: float
    ) -> None:
        """지원하지 않는 pyhwpx 일괄 API를 명시적으로 막는다."""
        raise HangulCommandError(
            "set_table_inside_margin은 한글 2022에서 성공을 반환해도 값이 바뀌지 않습니다. "
            "표 전체 안 여백은 셀을 순회해 set_cell_margin을 적용해야 합니다."
        )

    def table_cell_addresses(self) -> list[str]:
        """현재 표의 실제 셀 주소를 이동 액션과 KeyIndicator로 읽는다."""
        addresses = self._table_addresses()
        if not addresses:
            raise HangulCommandError("현재 표의 셀 구조를 읽지 못했습니다.")
        return addresses

    def table_column_addresses(self) -> dict[int, str]:
        """현재 표에서 각 열을 대표하는 실제 셀 주소."""
        representatives: dict[int, str] = {}
        for addr in self.table_cell_addresses():
            _row, col = _parse_a1(addr)
            representatives.setdefault(col, addr)
        return representatives

    def table_row_addresses(self) -> dict[int, str]:
        """현재 표에서 각 행을 대표하는 실제 셀 주소."""
        representatives: dict[int, str] = {}
        for addr in self.table_cell_addresses():
            row, _col = _parse_a1(addr)
            representatives.setdefault(row, addr)
        return representatives

    def set_all_cell_margins(
        self, left: float, right: float, top: float, bottom: float
    ) -> int:
        """현재 표의 실제 셀을 하나씩 순회해 안 여백을 적용한다."""
        addresses = self.table_cell_addresses()
        actions = 0
        for addr in addresses:
            self.goto_addr(addr)
            self.set_cell_margin_current(left, right, top, bottom)
            actions += 1
        return actions

    def select_all_cells(self) -> None:
        """캐럿이 들어 있는 표의 모든 셀을 셀블록으로 선택 (차트 데이터용)."""
        if not self.is_cell():
            raise HangulCommandError(
                "캐럿이 표 안에 있지 않아 표 전체 셀을 선택할 수 없습니다."
            )
        # pyhwpx 소스에서 확인한 시퀀스: ExtendAbs → Extend = 표 전체 셀 선택
        if not (self.run("TableCellBlockExtendAbs") and self.run("TableCellBlockExtend")):
            raise HangulCommandError("표 전체 셀 선택에 실패했습니다.")

    def begin_cell_block(self, addr: str, tries: int = 3) -> None:
        """``addr`` 에서 셀블록(F5)을 시작한다.

        한글 2022 의 ``TableCellBlock`` 은 캐럿이 셀에 막 들어온 직후에 False 를
        돌려주는 일이 있다. 셀을 한 번이라도 순회한 뒤에는 항상 성공하므로,
        Cancel 로 선택 상태를 지우고 같은 칸으로 다시 이동해 재시도한다.
        (실측: 재시도 없이는 표 생성 직후 병합·열 선택이 실패한다.)
        """
        for _ in range(max(1, tries)):
            if self.run("TableCellBlock"):
                return
            self.run("Cancel")
            self.goto_addr(addr)
        raise HangulCommandError(
            "셀블록 시작(TableCellBlock)에 실패했습니다. "
            "캐럿이 표 안에 있는지, 대화상자가 떠 있지 않은지 확인하세요."
        )

    def select_cell_range(self, start: str, end: str) -> None:
        """start~end 셀을 셀블록으로 선택. (F5 셀블록 후 이동 액션이 블록을 확장)"""
        r0, c0 = _parse_a1(start)
        r1, c1 = _parse_a1(end)
        if r1 < r0:
            r0, r1 = r1, r0
        if c1 < c0:
            c0, c1 = c1, c0
        # 이전 셀블록이 Extend 상태일 수 있으므로, 이동 전에 반드시 해제한다.
        self.run("Cancel")
        self.goto_addr(_a1(r0, c0))
        self.begin_cell_block(_a1(r0, c0))
        for _ in range(c1 - c0):
            if not self.run("TableRightCell"):
                raise HangulCommandError("셀블록 확장(열)에 실패했습니다.")
        for _ in range(r1 - r0):
            if not self.run("TableLowerCell"):
                raise HangulCommandError("셀블록 확장(행)에 실패했습니다.")

    def merge_cells(self, start: str, end: str) -> None:
        """한글 2022에서 확인된 셀블록 선택 순서로 범위를 합친다."""
        r0, c0 = _parse_a1(start)
        r1, c1 = _parse_a1(end)
        if r1 < r0:
            r0, r1 = r1, r0
        if c1 < c0:
            c0, c1 = c1, c0
        if r0 == r1 and c0 == c1:
            raise UsageError("두 칸 이상을 지정해야 셀을 합칠 수 있습니다.")
        # 이전 셀블록이 남은 채 goto_addr를 실행하면 이동 자체가 이전 범위를 확장해
        # 의도보다 큰 표 영역이 합쳐질 수 있다. 이동 전·후 모두 상태를 정리한다.
        self.run("Cancel")
        try:
            self.goto_addr(_a1(r0, c0))
            self.assert_no_dialog()
            self.begin_cell_block(_a1(r0, c0))
            if not self.run("TableCellBlockExtend"):
                raise HangulCommandError("셀 합치기 선택 확장(TableCellBlockExtend)에 실패했습니다.")
            for _ in range(c1 - c0):
                if not self.run("TableRightCell"):
                    raise HangulCommandError("셀 합치기 범위의 열 이동에 실패했습니다.")
            for _ in range(r1 - r0):
                if not self.run("TableLowerCell"):
                    raise HangulCommandError("셀 합치기 범위의 행 이동에 실패했습니다.")
            if not self.run("TableMergeCell"):
                raise HangulCommandError(
                    "셀 합치기(TableMergeCell)에 실패했습니다. "
                    "TableMergeCell은 셀블록 선택 없이 단독으로 실행할 수 없습니다."
                )
        finally:
            try:
                self.run("Cancel")
            except HangulCommandError:
                pass
        self.assert_no_dialog()

    def set_valign_current(self, align: str) -> int:
        """현재 셀의 세로 정렬. VertAlign 0/1/2에 대응하는 확인된 액션만 쓴다."""
        actions = {
            "top": ("TableVAlignTop", 0),
            "center": ("TableVAlignCenter", 1),
            "bottom": ("TableVAlignBottom", 2),
        }
        key = (align or "").strip().lower()
        if key not in actions:
            raise UsageError("세로 정렬은 top, center, bottom 중 하나여야 합니다.")
        if not self.is_cell():
            raise HangulCommandError("캐럿이 표 셀 안에 있지 않아 세로 정렬을 적용할 수 없습니다.")
        action_id, vert_align = actions[key]
        self.assert_no_dialog()
        if not self.run(action_id):
            raise HangulCommandError(f"셀 세로 정렬({action_id})에 실패했습니다.")
        self.assert_no_dialog()
        return vert_align

    def set_cell_border_current(
        self,
        *,
        sides: list[str],
        line_type: str | int,
        width: str | int,
        color: str,
    ) -> None:
        """현재 셀 테두리를 CellBorderFill로 설정한다."""
        allowed = {"left", "right", "top", "bottom"}
        unknown = set(sides) - allowed
        if unknown:
            if unknown & {"horz", "horizontal", "inside-horizontal"}:
                raise UsageError("한글 2022에서 TypeHorz는 지원하지 않습니다.")
            raise UsageError(f"지원하지 않는 셀 테두리 방향입니다: {', '.join(sorted(unknown))}")
        if not sides:
            raise UsageError("셀 테두리 방향을 하나 이상 지정하세요.")
        if not self.is_cell():
            raise HangulCommandError("캐럿이 표 셀 안에 있지 않아 테두리를 적용할 수 없습니다.")
        rgb = parse_color(color)
        try:
            line_type_value = (
                int(line_type)
                if isinstance(line_type, int)
                else int(self.com.HwpLineType(line_type))
            )
            width_value = (
                int(width) if isinstance(width, int) else int(self.com.HwpLineWidth(width))
            )
            color_value = self._rgb_value(rgb)
            pset = self.com.HParameterSet.HCellBorderFill
            self.com.HAction.GetDefault("CellBorderFill", pset.HSet)
            for side in sides:
                suffix = side.title()
                setattr(pset, f"BorderType{suffix}", line_type_value)
                setattr(pset, f"BorderWidth{suffix}", width_value)
                # 한글 2022 자동화의 왼쪽 색 항목은 실제로 Corlor 오탈자다.
                color_attr = "BorderCorlorLeft" if side == "left" else f"BorderColor{suffix}"
                setattr(pset, color_attr, color_value)
            self.assert_no_dialog()
            ok = bool(self.com.HAction.Execute("CellBorderFill", pset.HSet))
        except (UsageError, HangulCommandError):
            raise
        except Exception as exc:
            raise HangulCommandError(f"셀 테두리를 적용하지 못했습니다: {exc}") from exc
        if not ok:
            raise HangulCommandError("셀 테두리(CellBorderFill) 액션이 실패했습니다.")
        self.assert_no_dialog()

    def insert_chart(
        self,
        chart_group: int,
        chart_index: int = 0,
        dialog_disable: bool = True,
    ) -> None:
        """선택된 표(셀블록) 데이터로 한/글 네이티브 차트를 삽입.

        한컴 포럼(1529, 1649)에서 확인: InsertChart 액션에 노출된 아이템은
        ChartGroup / ChartIndex / ChartDataDialogDisable 3개뿐이고, 생성 후 수정
        API 는 없다. ChartDataDialogDisable 은 2020 에서는 지원되지 않아 데이터
        대화상자가 뜬다 — 대화상자가 뜨면 자동화 실패로 간주한다 (2022 대상).
        """
        ok = False
        try:
            act = self.com.CreateAction("InsertChart")
            pset = act.CreateSet()
            act.GetDefault(pset)
            pset.SetItem("ChartGroup", int(chart_group))
            pset.SetItem("ChartIndex", int(chart_index))
            if dialog_disable:
                pset.SetItem("ChartDataDialogDisable", 1)
            ok = bool(act.Execute(pset))
        except Exception as exc:
            raise HangulCommandError(
                f"차트 삽입에 실패했습니다: {exc}. "
                "한글 2022 이상에서만 데이터 대화상자 없이 삽입할 수 있습니다."
            ) from exc
        if not ok:
            raise HangulCommandError(
                "차트 삽입(InsertChart) 액션이 실패했습니다. "
                "차트로 만들 표의 셀들이 선택된 상태여야 합니다. "
                "데이터 편집 대화상자가 화면에 떠 있다면 닫아 주세요 — "
                "대화상자가 뜨는 버전(한글 2020 이하)에서는 자동화가 지원되지 않습니다."
            )

    def get_pos(self) -> tuple | None:
        try:
            pos = self.px.get_pos() if self.px else self.com.GetPos()
            return tuple(pos) if pos else None
        except Exception:
            return None

    def set_pos(self, pos: tuple | None) -> bool:
        if not pos or len(pos) < 3:
            return False
        try:
            if self.px:
                self.px.set_pos(pos[0], pos[1], pos[2])
            else:
                self.com.SetPos(pos[0], pos[1], pos[2])
            return True
        except Exception:
            return False

    def selection_range(self) -> tuple | None:
        """(is_block, slist, spara, spos, elist, epara, epos) 또는 None."""
        try:
            pos = self.px.get_selected_pos() if self.px else self.com.GetSelectedPos()
            if pos is not None and len(pos) >= 7 and bool(pos[0]):
                return tuple(pos)
        except Exception:
            pass
        return None

    def restore_selection(self, sel: tuple | None) -> bool:
        """snapshot 등 읽기 작업 후 사용자의 블록 선택을 되살린다 (best effort)."""
        if not sel or len(sel) < 7:
            return False
        _is_block, slist, spara, spos, _elist, epara, epos = sel[:7]
        try:
            if self.px:
                return bool(
                    self.px.select_text(
                        spara=spara, spos=spos, epara=epara, epos=epos, slist=slist
                    )
                )
            return bool(self.com.SelectText(spara, spos, epara, epos))
        except Exception:
            return False

    def select_row(self) -> None:
        if self.px:
            try:
                self.px.TableCellBlockRow()
                return
            except Exception:
                pass
        self.run("TableCellBlockRow")

    def select_cell_text(self) -> None:
        # 캐럿이 셀 밖일 때 SelectAll 은 문서 전체를 선택하므로 반드시 막는다.
        if not self.is_cell():
            raise HangulCommandError(
                "캐럿이 표 셀 안에 있지 않아 셀 내용을 선택할 수 없습니다."
            )
        self.run("SelectAll")

    def open_path(self, path: str) -> None:
        if self.px:
            if not self.px.open(path):
                raise HangulCommandError(f"파일을 열지 못했습니다: {path}")
            return
        if not self.com.Open(path, "", "forceopen:true"):
            raise HangulCommandError(f"파일을 열지 못했습니다: {path}")

    def new_document(self) -> None:
        if self.px:
            try:
                self.px.add_doc()
                return
            except Exception:
                pass
        self.run("FileNew")

    def save_as(self, path: str, fmt: str = "") -> None:
        fmt = _infer_format(path, fmt)
        arg = "lock:false;backup:false;autosave:false"
        if self.px:
            if not self.px.save_as(path, format=fmt, arg=arg):
                raise HangulCommandError(f"다른 이름으로 저장하지 못했습니다: {path}")
            return
        if not self.com.SaveAs(path, fmt, arg):
            raise HangulCommandError(f"다른 이름으로 저장하지 못했습니다: {path}")

    def save_overwrite(self) -> None:
        if self.px:
            if not self.px.save(save_if_dirty=False):
                raise HangulCommandError("저장에 실패했습니다.")
            return
        if not self.com.Save(False):
            raise HangulCommandError("저장에 실패했습니다.")

    def close_discard(self) -> None:
        """현재 활성 문서 하나만 저장 없이 닫는다.

        ``XHwpDocuments.Close(False)`` 는 컬렉션 전체를 닫을 수 있다. hwpctl은
        고정한 활성 창의 문서만 조작한다는 계약이므로, 컬렉션 API나 FileClose
        폴백으로 범위를 넓히지 않는다. 문서 단위 Close를 제공하지 않는 오래된
        COM 환경에서는 안전을 위해 명시적으로 실패시킨다.
        """
        try:
            documents = self.com.XHwpDocuments
            document = documents.Active_XHwpDocument
            close = getattr(document, "Close", None)
        except Exception as exc:
            raise HangulCommandError("현재 문서를 안전하게 닫을 수 없습니다.") from exc
        if not callable(close):
            raise HangulCommandError(
                "현재 한/글 버전은 문서 단위 닫기를 제공하지 않습니다. "
                "다른 열린 문서를 보호하기 위해 닫기를 취소했습니다."
            )
        try:
            result = close(False)
        except Exception as exc:
            raise HangulCommandError("현재 문서를 저장 없이 닫지 못했습니다.") from exc
        if result is False:
            raise HangulCommandError("현재 문서를 저장 없이 닫지 못했습니다.")

    def undo_once(self) -> None:
        self.run("Undo")

    def exit_table(self) -> None:
        """현재 표의 마지막 셀에서 문서 본문으로 커서를 옮긴다.

        한/글 2022에서는 마지막 셀 *문단 끝*에서 ``MoveRight``가 표 밖의
        일반 문단으로 이동한다. 구조화 ``write_cell``은 마지막 실행 후 캐럿을
        문단 중간에 남길 수 있으므로 먼저 ``MoveListEnd``로 끝을 명시한다.
        다른 셀에서는 다음 셀로만 이동할 수 있으므로, 이동 뒤에도 셀 안이면
        실패해 본문을 표 안에 삽입하는 실수를 막는다.
        """
        if not self.is_cell():
            raise HangulCommandError(
                "캐럿이 표 셀 안에 있지 않아 표 밖으로 이동할 수 없습니다."
            )
        if not self.run("MoveListEnd"):
            raise HangulCommandError("표 마지막 셀의 끝으로 이동하는 MoveListEnd 액션이 실패했습니다.")
        if not self.run("MoveRight"):
            raise HangulCommandError("표 밖으로 이동하는 MoveRight 액션이 실패했습니다.")
        if self.is_cell():
            # 다문단 1×1 셀은 MoveListEnd/MoveRight 뒤에도 셀의 하위 목록에
            # 남을 수 있다. 한/글의 MoveParentList로 문서 본문 목록으로 한
            # 단계만 올라간 뒤 다시 확인한다. 표의 다른 셀로 이동하는 대신
            # 부모 목록으로만 나가므로 다음 본문을 셀 안에 쓰지 않는다.
            if self.run("MoveParentList") and not self.is_cell():
                return
            raise HangulCommandError(
                "MoveRight 뒤에도 캐럿이 표 셀 안에 있습니다. "
                "표의 마지막 셀 끝에 캐럿을 둔 뒤 exit_table을 다시 호출하세요."
            )

    def set_table_properties(
        self,
        *,
        table: int,
        page_break: str,
        repeat_header: bool,
        cell_spacing_mm: float,
    ) -> int:
        """표의 쪽 경계, 제목 행 반복, 셀 간격을 TablePropertyDialog로 적용한다.

        이 동작은 표를 다시 만들거나 HWPML을 주입하지 않는다. 표 개체를 선택해
        한/글이 제공하는 표 속성 액션을 한 번 실행하고, 원래 캐럿을 복원한다.
        """
        if page_break not in {"none", "table", "cell"}:
            raise UsageError("표 페이지 나눔은 none, table, cell 중 하나여야 합니다.")
        if not isinstance(repeat_header, bool):
            raise UsageError("표 제목 행 반복 값은 true 또는 false여야 합니다.")
        spacing = self._number(
            cell_spacing_mm,
            "표 셀 간격",
            minimum=0.0,
            maximum=50.0,
        )
        page_breaks = {
            "none": ("None", 0),
            "table": ("Table", 1),
            "cell": ("Cell", 2),
        }
        saved = self.get_pos()
        self.assert_no_dialog()
        ok = False
        try:
            self.get_into_nth_table(table)
            # 표 셀 편집 상태에서는 일부 표 전역 속성이 누락될 수 있어 개체 선택
            # 상태로 전환한다. set_table_position과 같은 검증된 전환 순서다.
            self.run("CloseEx")
            try:
                self.com.FindCtrl()
            except Exception:
                pass
            pset = self.com.HParameterSet.HShapeObject
            self.com.HAction.GetDefault("TablePropertyDialog", pset.HSet)
            # ShapeType/ShapeCellSize는 HShapeObject의 속성이 아니라 HSet의
            # 필수 아이템이다. 일부 COM 설치본은 속성 대입을 허용하지 않는다.
            self._set_pset_item(pset.HSet, "ShapeType", 3)
            self._set_pset_item(pset.HSet, "ShapeCellSize", 0)
            self._set_pset_item(
                pset,
                "PageBreak",
                self._enum("TableBreak", *page_breaks[page_break]),
            )
            self._set_pset_item(pset, "RepeatHeader", 1 if repeat_header else 0)
            self._set_pset_item(pset, "CellSpacing", self._mm_to_hwpunit(spacing))
            ok = bool(self.com.HAction.Execute("TablePropertyDialog", pset.HSet))
        except (UsageError, HangulCommandError):
            raise
        except Exception as exc:
            raise HangulCommandError(f"표 속성을 적용하지 못했습니다: {exc}") from exc
        finally:
            try:
                self.run("Cancel")
            except Exception:
                pass
            if saved is not None and not self.set_pos(saved):
                raise HangulCommandError("표 속성 적용 뒤 원래 커서 위치를 복원하지 못했습니다.")
        if not ok:
            raise HangulCommandError("표 속성(TablePropertyDialog) 액션이 실패했습니다.")
        self.assert_no_dialog()
        return 1

    def set_table_position(self, *, table: int, position: dict[str, Any]) -> int:
        """표 개체의 inline/floating 위치와 본문 배치를 네이티브로 적용한다.

        ``TablePropertyDialog``은 표 내부 편집 상태가 아니라 표 개체 선택 상태를
        요구한다. 호출 전 커서를 저장하고 완료 뒤 되돌려, 이미 ``exit_table``한
        작성 흐름이 떠 있는 표의 속성 변경 때문에 표 안으로 빨려 들어가지 않게 한다.
        """
        if not isinstance(position, dict):
            raise UsageError("표 위치는 JSON 객체여야 합니다.")
        mode = position.get("mode")
        if mode not in {"inline", "floating"}:
            raise UsageError("표 위치 mode는 inline 또는 floating이어야 합니다.")
        saved = self.get_pos()
        self.assert_no_dialog()
        ok = False
        try:
            self.get_into_nth_table(table)
            # 셀 편집 모드에서 빠져나온 뒤 표 개체 자체를 선택한다. 한/글 2022의
            # TablePropertyDialog는 이 순서가 아니면 셀 크기만 바꾸거나 실패한다.
            self.run("CloseEx")
            try:
                self.com.FindCtrl()
            except Exception:
                pass
            pset = self.com.HParameterSet.HShapeObject
            self.com.HAction.GetDefault("TablePropertyDialog", pset.HSet)
            self._set_pset_item(pset.HSet, "ShapeType", 3)
            self._set_pset_item(pset, "TreatAsChar", 1 if mode == "inline" else 0)
            self._set_pset_item(
                pset,
                "AffectsLine",
                1 if bool(position.get("affect_line_spacing", False)) else 0,
            )
            margins = position.get("outside_margin_mm", (0, 0, 0, 0))
            if not isinstance(margins, (list, tuple)) or len(margins) != 4:
                raise UsageError("표 바깥 여백은 [left, right, top, bottom] 4개 값이어야 합니다.")
            left, right, top, bottom = (
                self._number(value, f"표 바깥 여백[{index}]", minimum=0.0, maximum=50.0)
                for index, value in enumerate(margins)
            )
            for name, value in (
                ("OutsideMarginLeft", left),
                ("OutsideMarginRight", right),
                ("OutsideMarginTop", top),
                ("OutsideMarginBottom", bottom),
            ):
                self._set_pset_item(pset, name, self._mm_to_hwpunit(value))
            if mode == "floating":
                horizontal_relative = {
                    "paper": ("Paper", 0),
                    "page": ("Page", 1),
                    "column": ("Column", 2),
                    "para": ("Para", 3),
                }
                vertical_relative = {
                    "paper": ("Paper", 0),
                    "page": ("Page", 1),
                    "para": ("Para", 2),
                }
                horizontal_align = {
                    "left": ("Left", 1),
                    "center": ("Center", 2),
                    "right": ("Right", 3),
                }
                vertical_align = {
                    "top": ("Top", 0),
                    "center": ("Center", 1),
                    "bottom": ("Bottom", 2),
                }
                wraps = {
                    "square": ("Square", 0),
                    "top_and_bottom": ("TopAndBottom", 1),
                    "behind_text": ("BehindText", 2),
                    "in_front_of_text": ("InFrontOfText", 3),
                }
                h_rel = position.get("horizontal_relative_to")
                v_rel = position.get("vertical_relative_to")
                h_align = position.get("horizontal_align")
                v_align = position.get("vertical_align")
                wrap = position.get("wrap")
                if h_rel not in horizontal_relative or v_rel not in vertical_relative:
                    raise UsageError("지원하지 않는 떠 있는 표의 위치 기준입니다.")
                if h_align not in horizontal_align or v_align not in vertical_align:
                    raise UsageError("지원하지 않는 떠 있는 표의 정렬입니다.")
                if wrap not in wraps:
                    raise UsageError("지원하지 않는 떠 있는 표의 본문 배치입니다.")
                x_mm = self._number(position.get("x_mm"), "표 x_mm", minimum=-500.0, maximum=500.0)
                y_mm = self._number(position.get("y_mm"), "표 y_mm", minimum=-500.0, maximum=500.0)
                self._set_pset_item(
                    pset,
                    "HorzRelTo",
                    self._enum("HorzRel", *horizontal_relative[h_rel]),
                )
                self._set_pset_item(
                    pset,
                    "VertRelTo",
                    self._enum("VertRel", *vertical_relative[v_rel]),
                )
                self._set_pset_item(
                    pset,
                    "HorzAlign",
                    self._enum("HAlign", *horizontal_align[h_align]),
                )
                self._set_pset_item(
                    pset,
                    "VertAlign",
                    self._enum("VAlign", *vertical_align[v_align]),
                )
                self._set_pset_item(pset, "HorzOffset", self._mm_to_hwpunit(x_mm))
                self._set_pset_item(pset, "VertOffset", self._mm_to_hwpunit(y_mm))
                self._set_pset_item(
                    pset,
                    "TextWrap",
                    self._enum("TextWrapType", *wraps[wrap]),
                )
                self._set_pset_item(
                    pset,
                    "FlowWithText",
                    1 if bool(position.get("flow_with_text", True)) else 0,
                )
                self._set_pset_item(
                    pset,
                    "AllowOverlap",
                    1 if bool(position.get("allow_overlap", False)) else 0,
                )
            ok = bool(self.com.HAction.Execute("TablePropertyDialog", pset.HSet))
        except (UsageError, HangulCommandError):
            raise
        except Exception as exc:
            raise HangulCommandError(f"표 위치를 적용하지 못했습니다: {exc}") from exc
        finally:
            try:
                self.run("Cancel")
            except Exception:
                pass
            if saved is not None and not self.set_pos(saved):
                raise HangulCommandError("표 위치 적용 뒤 원래 커서 위치를 복원하지 못했습니다.")
        if not ok:
            raise HangulCommandError("표 위치(TablePropertyDialog) 액션이 실패했습니다.")
        self.assert_no_dialog()
        return 1

    def set_current_table_properties(
        self,
        *,
        page_break: str,
        repeat_header: bool,
        cell_spacing_mm: float,
    ) -> int:
        """캐럿이 든 새 표에 전역 표 속성을 적용한다.

        표를 막 삽입한 직후에는 컨트롤 순서가 바뀔 수 있다. 표 번호를 다시
        추정하지 않고 현재 셀의 표 개체를 직접 선택해 적용하므로, 다른 표의
        페이지 나눔/반복 속성을 바꾸지 않는다.
        """
        if not self.is_cell():
            raise HangulCommandError("새 표 셀 안에 있지 않아 표 속성을 적용할 수 없습니다.")
        if page_break not in {"none", "table", "cell"}:
            raise UsageError("표 페이지 나눔은 none, table, cell 중 하나여야 합니다.")
        if not isinstance(repeat_header, bool):
            raise UsageError("표 제목 행 반복 값은 true 또는 false여야 합니다.")
        spacing = self._number(
            cell_spacing_mm,
            "표 셀 간격",
            minimum=0.0,
            maximum=50.0,
        )
        page_breaks = {
            "none": ("None", 0),
            "table": ("Table", 1),
            "cell": ("Cell", 2),
        }
        saved = self.get_pos()
        ok = False
        self.assert_no_dialog()
        try:
            self.run("CloseEx")
            self.com.FindCtrl()
            pset = self.com.HParameterSet.HShapeObject
            self.com.HAction.GetDefault("TablePropertyDialog", pset.HSet)
            self._set_pset_item(pset.HSet, "ShapeType", 3)
            self._set_pset_item(pset.HSet, "ShapeCellSize", 0)
            self._set_pset_item(
                pset,
                "PageBreak",
                self._enum("TableBreak", *page_breaks[page_break]),
            )
            self._set_pset_item(pset, "RepeatHeader", 1 if repeat_header else 0)
            self._set_pset_item(pset, "CellSpacing", self._mm_to_hwpunit(spacing))
            ok = bool(self.com.HAction.Execute("TablePropertyDialog", pset.HSet))
        except (UsageError, HangulCommandError):
            raise
        except Exception as exc:
            raise HangulCommandError("새 표의 전역 속성을 적용하지 못했습니다.") from exc
        finally:
            try:
                self.run("Cancel")
            except Exception:
                pass
            if saved is not None and not self.set_pos(saved):
                raise HangulCommandError("새 표 속성 적용 뒤 커서 위치를 복원하지 못했습니다.")
        if not ok:
            raise HangulCommandError("새 표 속성(TablePropertyDialog) 액션이 실패했습니다.")
        self.assert_no_dialog()
        return 1

    def set_current_inline_table_position(
        self,
        *,
        affect_line_spacing: bool,
        outside_margin_mm: list[float] | tuple[float, float, float, float],
    ) -> int:
        """캐럿이 든 새 표를 글자처럼 취급하는 인라인 표로 확정한다."""
        if not self.is_cell():
            raise HangulCommandError("새 표 셀 안에 있지 않아 인라인 위치를 적용할 수 없습니다.")
        if not isinstance(affect_line_spacing, bool):
            raise UsageError("affect_line_spacing 값은 true 또는 false여야 합니다.")
        if not isinstance(outside_margin_mm, (list, tuple)) or len(outside_margin_mm) != 4:
            raise UsageError("표 바깥 여백은 [left, right, top, bottom] 4개 값이어야 합니다.")
        left, right, top, bottom = (
            self._number(value, f"표 바깥 여백[{index}]", minimum=0.0, maximum=50.0)
            for index, value in enumerate(outside_margin_mm)
        )
        saved = self.get_pos()
        ok = False
        self.assert_no_dialog()
        try:
            self.run("CloseEx")
            self.com.FindCtrl()
            pset = self.com.HParameterSet.HShapeObject
            self.com.HAction.GetDefault("TablePropertyDialog", pset.HSet)
            self._set_pset_item(pset.HSet, "ShapeType", 3)
            self._set_pset_item(pset, "TreatAsChar", 1)
            self._set_pset_item(pset, "AffectsLine", 1 if affect_line_spacing else 0)
            for name, value in (
                ("OutsideMarginLeft", left),
                ("OutsideMarginRight", right),
                ("OutsideMarginTop", top),
                ("OutsideMarginBottom", bottom),
            ):
                self._set_pset_item(pset, name, self._mm_to_hwpunit(value))
            ok = bool(self.com.HAction.Execute("TablePropertyDialog", pset.HSet))
        except (UsageError, HangulCommandError):
            raise
        except Exception as exc:
            raise HangulCommandError("새 표의 인라인 위치를 적용하지 못했습니다.") from exc
        finally:
            try:
                self.run("Cancel")
            except Exception:
                pass
            if saved is not None and not self.set_pos(saved):
                raise HangulCommandError("새 표 위치 적용 뒤 커서 위치를 복원하지 못했습니다.")
        if not ok:
            raise HangulCommandError("새 표 위치(TablePropertyDialog) 액션이 실패했습니다.")
        self.assert_no_dialog()
        return 1

    def set_pagedef(
        self,
        *,
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
    ) -> None:
        """현재 편집용지의 용지·여백·방향을 PageSetup으로 바꾼다."""
        apply_to = {"current": 2, "all": 3, "new": 4}
        if apply not in apply_to:
            raise UsageError("편집용지 적용 범위는 current, all, new 중 하나여야 합니다.")
        fields = {
            "PaperWidth": paper_width,
            "PaperHeight": paper_height,
            "LeftMargin": left,
            "RightMargin": right,
            "TopMargin": top,
            "BottomMargin": bottom,
            "HeaderLen": header,
            "FooterLen": footer,
            "GutterLen": gutter,
        }
        self.assert_no_dialog()
        try:
            pset = self.com.HParameterSet.HSecDef
            self.com.HAction.GetDefault("PageSetup", pset.HSet)
            for name, value in fields.items():
                if value is not None:
                    setattr(pset.PageDef, name, self._mm_to_hwpunit(value))
            if landscape is not None:
                pset.PageDef.Landscape = 1 if landscape else 0
            pset.HSet.SetItem("ApplyTo", apply_to[apply])
            ok = bool(self.com.HAction.Execute("PageSetup", pset.HSet))
        except Exception as exc:
            raise HangulCommandError(f"편집용지를 적용하지 못했습니다: {exc}") from exc
        if not ok:
            raise HangulCommandError("편집용지(PageSetup) 액션이 실패했습니다.")
        self.assert_no_dialog()

    def break_page(self) -> None:
        """캐럿 위치에서 확인된 BreakPage 액션으로 쪽을 나눈다."""
        self.assert_no_dialog()
        if not self.run("BreakPage"):
            raise HangulCommandError("쪽 나누기(BreakPage) 액션이 실패했습니다.")
        self.assert_no_dialog()

    def break_paragraph(self) -> None:
        """현재 위치에서 다음 문단으로 이동한다 (BreakPara)."""
        self.assert_no_dialog()
        if not self.run("BreakPara"):
            raise HangulCommandError("문단 나누기(BreakPara) 액션이 실패했습니다.")
        self.assert_no_dialog()

    def set_page_number(self, *, position: str, separator: str) -> None:
        """네이티브 PageNumPos 쪽 번호를 적용한다 (본문 텍스트 삽입 아님)."""
        mapping = {
            "top_left": "TopLeft",
            "top_center": "TopCenter",
            "top_right": "TopRight",
            "bottom_left": "BottomLeft",
            "bottom_center": "BottomCenter",
            "bottom_right": "BottomRight",
        }
        enum_name = mapping.get(position)
        if enum_name is None:
            raise UsageError("지원하지 않는 쪽 번호 위치입니다.")
        if not isinstance(separator, str) or len(separator) > 1:
            raise UsageError("쪽 번호 separator 는 한 글자 또는 빈 문자열이어야 합니다.")
        self.assert_no_dialog()
        try:
            pset = self.com.HParameterSet.HPageNumPos
            self.com.HAction.GetDefault("PageNumPos", pset.HSet)
            pset.DrawPos = self.com.PageNumPosition(enum_name)
            pset.NumberFormat = 0  # digit
            pset.SideChar = ord(separator) if separator else 0
            ok = bool(self.com.HAction.Execute("PageNumPos", pset.HSet))
        except (UsageError, HangulCommandError):
            raise
        except Exception as exc:
            raise HangulCommandError(f"쪽 번호 모양을 적용하지 못했습니다: {exc}") from exc
        if not ok:
            raise HangulCommandError("쪽 번호(PageNumPos) 액션이 실패했습니다.")
        self.assert_no_dialog()

    def set_page_visibility(
        self,
        *,
        hide_header: bool,
        hide_footer: bool,
        hide_master_page: bool,
        hide_border: bool,
        hide_fill: bool,
        hide_page_num: bool,
    ) -> None:
        """현재 위치에 PageHiding 네이티브 제어를 삽입한다."""
        values = {
            "hide_header": hide_header,
            "hide_footer": hide_footer,
            "hide_master_page": hide_master_page,
            "hide_border": hide_border,
            "hide_fill": hide_fill,
            "hide_page_num": hide_page_num,
        }
        if not all(isinstance(value, bool) for value in values.values()):
            raise UsageError("쪽 표시 감춤 값은 모두 true 또는 false여야 합니다.")
        # PageHiding.Fields의 저비트 0~5는 HWPML의 six hide flags와 같은 순서다.
        # Hwp.Hiding()에 의존하지 않고 고정된 공개 bit mapping을 써서 COM 스텁과
        # 한/글 2022 모두에서 같은 요청을 만든다.
        bits = {
            "hide_header": 1,
            "hide_footer": 2,
            "hide_master_page": 4,
            "hide_border": 8,
            "hide_fill": 16,
            "hide_page_num": 32,
        }
        fields = sum(bits[key] for key, value in values.items() if value)
        self.assert_no_dialog()
        try:
            pset = self.com.HParameterSet.HPageHiding
            self.com.HAction.GetDefault("PageHiding", pset.HSet)
            self._set_pset_item(pset, "Fields", fields)
            ok = bool(self.com.HAction.Execute("PageHiding", pset.HSet))
        except (UsageError, HangulCommandError):
            raise
        except Exception as exc:
            raise HangulCommandError(f"쪽 표시 감춤을 적용하지 못했습니다: {exc}") from exc
        if not ok:
            raise HangulCommandError("쪽 표시 감춤(PageHiding) 액션이 실패했습니다.")
        self.assert_no_dialog()

    def restart_page_number(self, *, number: int) -> None:
        """현재 캐럿 위치에 한/글의 NewNumber(Page) 제어를 넣는다."""
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise UsageError("새 쪽 번호는 1 이상의 정수여야 합니다.")
        self.assert_no_dialog()
        try:
            # 일부 한/글 2022 COM 설치본에는 편의 메서드 ``NewNumber``가 노출되지
            # 않는다. 문서화된 NewNumber 액션을 직접 실행하면 같은 <NEWNUM
            # NumberType="Page"> 제어를 만들며 설치본 차이도 피할 수 있다.
            action = self.com.CreateAction("NewNumber")
            if action is None:
                raise HangulCommandError("새 쪽 번호(NewNumber) 액션을 만들지 못했습니다.")
            pset = action.CreateSet()
            action.GetDefault(pset)
            self._set_pset_item(pset, "NumType", 0)  # Page
            self._set_pset_item(pset, "NewNumber", number)
            ok = bool(action.Execute(pset))
        except (UsageError, HangulCommandError):
            raise
        except Exception as exc:
            raise HangulCommandError(f"새 쪽 번호를 적용하지 못했습니다: {exc}") from exc
        if not ok:
            raise HangulCommandError("새 쪽 번호(NewNumber) 액션이 실패했습니다.")
        self.assert_no_dialog()

    def goto_page(self, page_index_1: int) -> None:
        if page_index_1 < 1:
            raise UsageError("쪽 번호는 1부터입니다.")
        if self.px:
            try:
                if self.px.goto_page(page_index=page_index_1):
                    return
            except Exception:
                pass
        # 한/글 2022 COM의 GotoPage는 예외 없이 현재 쪽에 머무는 경우가 있다.
        # 문서 처음에서 MovePageDown을 반복하는 편이 실제 커서 위치를 옮긴다.
        if not self.run("MoveDocBegin"):
            raise HangulCommandError("문서 처음으로 이동하지 못해 쪽 이동에 실패했습니다.")
        previous = self.get_pos()
        for _ in range(page_index_1 - 1):
            if not self.run("MovePageDown"):
                raise HangulCommandError(f"{page_index_1}쪽으로 이동하지 못했습니다.")
            current = self.get_pos()
            if previous and current == previous:
                raise HangulCommandError(
                    f"{page_index_1}쪽으로 이동하지 못했습니다 (쪽 이동 후 위치가 바뀌지 않았습니다)."
                )
            previous = current

    def move_doc_end(self) -> None:
        self.run("MoveDocEnd")

    def is_cell(self) -> bool:
        if self.px:
            try:
                return bool(self.px.is_cell())
            except Exception:
                pass
        try:
            # 셀 안 1, 셀필드 안 17 (pyhwpx CurFieldState 문서)
            return int(getattr(self.com, "CurFieldState", 0)) in (1, 17)
        except Exception:
            return False

    def assert_no_dialog(self) -> None:
        """대상 한/글 창이 소유한 보이는 대화상자가 있으면 한국어로 실패."""
        if sys.platform != "win32":
            return
        try:
            import win32gui  # type: ignore

            target = self.window_handle()
            found: list[str] = []

            def inspect(hwnd: int, _extra: Any) -> None:
                if not win32gui.IsWindowVisible(hwnd):
                    return
                if win32gui.GetClassName(hwnd) != "#32770":
                    return
                owner = win32gui.GetWindow(hwnd, 4)  # GW_OWNER
                while owner:
                    if owner == target:
                        found.append(win32gui.GetWindowText(hwnd) or "대화상자")
                        return
                    owner = win32gui.GetWindow(owner, 4)

            win32gui.EnumWindows(inspect, None)
            if found:
                raise HangulCommandError(
                    f"한/글 대화상자('{found[0]}')가 떠 있어 레이아웃 검토를 중단했습니다. "
                    "대화상자를 닫은 뒤 다시 실행하세요."
                )
        except HangulCommandError:
            raise
        except Exception:
            # 창 열거 자체가 불가능해도 COM 편집을 막지는 않는다.
            return

    # --- 내부 --------------------------------------------------------------

    def _table_addresses(self) -> list[str]:
        """현재 표 셀을 2022의 TableRightCell+KeyIndicator로 순회."""
        saved = self.get_pos()
        addresses: list[str] = []
        try:
            if not self.run("TableColBegin") or not self.run("TableColPageUp"):
                return []
            for _ in range(5000):
                addr = self.current_cell_addr()
                if not addr:
                    break
                # 병합 셀은 다음 행으로 갈 때 같은 좌상단 주소를 다시 보고한다.
                # 주소 목록에는 한 번만 담되, 순회는 멈추지 않아야 뒤쪽 행의
                # 실제 셀(D2, A3...)을 찾을 수 있다.
                if addr not in addresses:
                    addresses.append(addr)
                if not self.run("TableRightCell"):
                    break
        finally:
            self.set_pos(saved)
        return addresses

    def _cell_line_count(self, text: str) -> tuple[int, bool]:
        """현재 셀의 실제 조판 줄 수.

        KeyIndicator의 줄 번호를 단순히 빼면 쪽/구역/중첩 리스트 경계에서 번호가
        재시작될 수 있다. 따라서 MoveLineEnd와 문서 위치의 실제 진행으로 줄을 세고,
        매 단계에서 같은 셀 주소인지 KeyIndicator로 검증한다.
        """
        saved = self.get_pos()
        try:
            cell_addr = self.current_cell_addr()
            if not cell_addr:
                return hard_line_count(text), False
            if not self.run("MoveListEnd"):
                return hard_line_count(text), False
            end_pos = self.get_pos()
            if not end_pos:
                return hard_line_count(text), False
            if not self.run("MoveListBegin"):
                return hard_line_count(text), False
            count = 1
            for _ in range(10000):
                current = self.get_pos()
                if current == end_pos:
                    return count, True
                if not current or not self.run("MoveLineEnd"):
                    return hard_line_count(text), False
                line_end = self.get_pos()
                if line_end == end_pos:
                    return count, True
                if not line_end or not self.run("MoveNextChar"):
                    return hard_line_count(text), False
                next_pos = self.get_pos()
                if not next_pos or next_pos == line_end:
                    return hard_line_count(text), False
                if self.current_cell_addr() != cell_addr:
                    return hard_line_count(text), False
                count += 1
        except Exception:
            pass
        finally:
            self.set_pos(saved)
        return hard_line_count(text), False

    def _get_current_cell_text(self) -> str:
        """현재 셀만 명시적으로 선택해 텍스트를 읽고 캐럿을 복원."""
        if not self.is_cell():
            raise HangulCommandError("캐럿이 표 셀 안에 있지 않아 셀 내용을 읽을 수 없습니다.")
        saved = self.get_pos()
        try:
            self.select_cell_text()
            return self.get_selected_text()
        finally:
            self.set_pos(saved)

    def _get_col_width_mm(self) -> float:
        if self.px:
            try:
                return float(self.px.get_col_width(as_="mm"))
            except Exception:
                pass
        try:
            pset = self.com.HParameterSet.HShapeObject
            self.com.HAction.GetDefault("TablePropertyDialog", pset.HSet)
            return self._hwpunit_to_mm(pset.ShapeTableCell.Width)
        except Exception as exc:
            raise HangulCommandError(f"열 너비를 읽지 못했습니다: {exc}") from exc

    def _get_row_height_mm(self) -> float:
        if self.px:
            try:
                return float(self.px.get_row_height(as_="mm"))
            except Exception:
                pass
        try:
            pset = self.com.HParameterSet.HShapeObject
            self.com.HAction.GetDefault("TablePropertyDialog", pset.HSet)
            return self._hwpunit_to_mm(pset.ShapeTableCell.Height)
        except Exception as exc:
            raise HangulCommandError(f"행 높이를 읽지 못했습니다: {exc}") from exc

    def _get_table_width_mm(self) -> float:
        if self.px:
            try:
                return float(self.px.get_table_width(as_="mm"))
            except Exception:
                pass
        try:
            return self._hwpunit_to_mm(self.com.CellShape.Item("Width"))
        except Exception:
            return 0.0

    def _get_cell_margin_mm(self) -> dict[str, float]:
        if self.px:
            try:
                margins = self.px.get_cell_margin(as_="mm")
                if isinstance(margins, dict):
                    return {key: float(margins[key]) for key in ("left", "right", "top", "bottom")}
            except Exception:
                pass
        try:
            pset = self.com.HParameterSet.HShapeObject
            self.com.HAction.GetDefault("TablePropertyDialog", pset.HSet)
            cell = pset.ShapeTableCell
            return {
                "left": self._hwpunit_to_mm(cell.MarginLeft),
                "right": self._hwpunit_to_mm(cell.MarginRight),
                "top": self._hwpunit_to_mm(cell.MarginTop),
                "bottom": self._hwpunit_to_mm(cell.MarginBottom),
            }
        except Exception:
            return {"left": 3.5, "right": 3.5, "top": 2.0, "bottom": 2.0}

    def _get_font_size_pt(self) -> float:
        try:
            shape = self.px.get_charshape() if self.px else self.com.CharShape
            height = shape.Item("Height")
            return max(1.0, float(height) / 100.0)
        except Exception:
            return 10.0

    def _get_line_spacing_percent(self) -> float:
        try:
            shape = self.px.get_parashape() if self.px else self.com.ParaShape
            value = float(shape.Item("LineSpacing"))
            return value if 50 <= value <= 500 else 160.0
        except Exception:
            return 160.0

    def _get_cell_typography(self, text: str = "") -> tuple[float, float]:
        """셀 전체를 순회해 가장 큰 글자와 줄간격을 읽는다.

        한 지점만 표본으로 삼으면 혼합 서식 셀의 큰 글자를 놓쳐 행을 너무 낮출 수
        있다. MoveNextChar는 한/글 2022에서 셀 끝에서도 True를 반환하거나 위치를
        바꾸지 않는 경우가 있어, 끝 위치·위치 진행·셀 주소를 모두 확인한다.
        매우 긴 셀은 5000자까지만 확인하고, 이 경우에도 시작점 표본보다 안전하다.
        """
        saved = self.get_pos()
        max_font = 10.0
        max_spacing = 160.0
        try:
            cell_addr = self.current_cell_addr()
            if not self.run("MoveListEnd"):
                return self._get_font_size_pt(), self._get_line_spacing_percent()
            end_pos = self.get_pos()
            if not end_pos:
                return self._get_font_size_pt(), self._get_line_spacing_percent()
            if not self.run("MoveListBegin"):
                return self._get_font_size_pt(), self._get_line_spacing_percent()
            current_pos = self.get_pos()
            if not current_pos:
                return self._get_font_size_pt(), self._get_line_spacing_percent()
            # 과거에는 짧은 셀도 5000회 순회했다. 실제 텍스트 길이를 우선 상한으로
            # 써서 한/글의 MoveNextChar가 셀 끝에서 진행하지 않아도 즉시 멈춘다.
            max_steps = max(1, min(len(text), 5000))
            for _ in range(max_steps):
                max_font = max(max_font, self._get_font_size_pt())
                max_spacing = max(max_spacing, self._get_line_spacing_percent())
                if current_pos == end_pos:
                    break
                if not self.run("MoveNextChar"):
                    break
                next_pos = self.get_pos()
                if not next_pos or next_pos == current_pos:
                    break
                if cell_addr and self.current_cell_addr() != cell_addr:
                    break
                current_pos = next_pos
        except Exception:
            pass
        finally:
            self.set_pos(saved)
        return max_font, max_spacing

    def _get_body_width_mm(self) -> float:
        if self.px:
            try:
                page = self.px.get_pagedef_as_dict(as_="eng")
                paper = float(page["PaperHeight"] if int(page.get("Landscape", 0)) else page["PaperWidth"])
                return max(
                    0.0,
                    paper
                    - float(page.get("LeftMargin", 0))
                    - float(page.get("RightMargin", 0))
                    - float(page.get("GutterLen", 0)),
                )
            except Exception:
                pass
        try:
            pset = self.com.HParameterSet.HSecDef
            self.com.HAction.GetDefault("PageSetup", pset.HSet)
            page = pset.PageDef
            paper = page.PaperHeight if int(page.Landscape) else page.PaperWidth
            return self._hwpunit_to_mm(
                paper - page.LeftMargin - page.RightMargin - page.GutterLen
            )
        except Exception:
            return 150.0

    def _get_table_outside_margin_mm(self) -> dict[str, float]:
        if self.px:
            try:
                margins = self.px.get_table_outside_margin(as_="mm")
                if isinstance(margins, dict):
                    return {"left": float(margins["left"]), "right": float(margins["right"])}
            except Exception:
                pass
        saved = self.get_pos()
        try:
            self.run("TableCellBlock")
            pset = self.com.HParameterSet.HShapeObject
            self.com.HAction.GetDefault("TablePropertyDialog", pset.HSet)
            return {
                "left": self._hwpunit_to_mm(pset.OutsideMarginLeft),
                "right": self._hwpunit_to_mm(pset.OutsideMarginRight),
            }
        except Exception:
            return {"left": 0.0, "right": 0.0}
        finally:
            self.set_pos(saved)

    def _hwpunit_to_mm(self, value: Any) -> float:
        try:
            return float(self.com.HwpUnitToMili(value))
        except Exception:
            return float(value) * 25.4 / 7200.0

    def _table_count(self) -> int:
        return len(self._table_ctrls())

    def _table_ctrls(self) -> list[Any]:
        if self.px:
            try:
                return [c for c in self.px.ctrl_list if getattr(c, "CtrlID", "") == "tbl"]
            except Exception:
                pass
        found: list[Any] = []
        try:
            ctrl = self.com.HeadCtrl
            seen = 0
            while ctrl is not None and seen < 5000:
                seen += 1
                if str(getattr(ctrl, "CtrlID", "")) == "tbl":
                    found.append(ctrl)
                ctrl = getattr(ctrl, "Next", None)
        except Exception:
            return found
        return found

    def _guess_rows(self) -> int:
        return 1

    def _guess_cols(self) -> int:
        return 1

    def _key_page(self) -> int:
        try:
            info = self.px.key_indicator() if self.px else self.com.KeyIndicator()
            return int(info[3])
        except Exception:
            return 1

    def _version(self) -> list[int]:
        try:
            if self.px:
                v = self.px.Version
                return [int(x) for x in v]
        except Exception:
            pass
        try:
            v = self.com.Version
            if isinstance(v, str):
                return [int(p) for p in v.split(".") if p.isdigit()]
            return [int(x) for x in v]
        except Exception:
            return []

    def _doc_attr(self, name: str) -> Any:
        try:
            docs = self.com.XHwpDocuments
            doc = docs.Active_XHwpDocument
            return getattr(doc, name)
        except Exception:
            return None

    def _call_px(self, name: str, *args: Any, **kwargs: Any) -> Any:
        if not self.px:
            return None
        fn = getattr(self.px, name, None)
        if fn is None:
            return None
        try:
            return fn(*args, **kwargs)
        except Exception:
            return None

    def _first(self, *getters: Callable[[], Any], default: Any = None) -> Any:
        for getter in getters:
            try:
                value = getter()
            except Exception:
                continue
            if value is not None:
                return value
        return default

    def _first_str(self, *getters: Callable[[], Any], default: str = "") -> str:
        value = self._first(*getters, default=default)
        return "" if value is None else str(value)


def _active_hwp_window(windows: Any) -> Any | None:
    """한글 2022 의 활성 창. 속성 이름이 달라도 찾는다. 없으면 None."""
    for name in ("Active_XHwpWindow", "ActiveXHwpWindow"):
        try:
            win = getattr(windows, name, None)
        except Exception:
            win = None
        if win is not None:
            return win
    try:
        win = windows.get_Active_XHwpWindow()
    except Exception:
        win = None
    return win if win is not None else None


def _windows_count(windows: Any) -> int:
    try:
        return int(windows.Count)
    except Exception:
        return 0


def _item_handle(windows: Any, index: int) -> int:
    try:
        return int(windows.Item(index).WindowHandle)
    except Exception:
        return 0


def _window_handle_of(com: Any) -> int:
    """이 COM 이 가리키는 *현재* 창의 WindowHandle.

    Item(0) 은 처음 연 창이라 Count>1 이면 이전 파일이다 (라이브 855126 vs 3738628).
    Active_XHwpWindow 를 쓰고, 없거나 이름이 다르면 Item 을 훑어
    활성/보이는 현재 창을 고른다. Count>1 일 때 Item(0) 을 그대로 쓰지 않는다.
    """
    try:
        windows = com.XHwpWindows
    except Exception:
        return 0

    active = _active_hwp_window(windows)
    if active is not None:
        try:
            handle = int(active.WindowHandle)
            if handle:
                return handle
        except Exception:
            pass

    count = _windows_count(windows)
    if count > 1:
        # Add()/FileNew 직후 새 창은 보통 마지막 슬롯. 뒤부터 보이는 창을 고른다.
        for i in range(count - 1, -1, -1):
            try:
                win = windows.Item(i)
                handle = int(win.WindowHandle)
            except Exception:
                continue
            if not handle:
                continue
            if i == 0:
                continue  # Count>1 이면 첫 창은 이전 문서
            visible = getattr(win, "Visible", True)
            if visible in (False, 0):
                continue
            return handle
        # Visible 을 못 읽으면 마지막 핸들 (방금 Add 한 창)
        last = _item_handle(windows, count - 1)
        if last:
            return last
        return 0

    return _item_handle(windows, 0)


def _iter_window_handles(com: Any):
    """이 HwpObject 의 모든 창 WindowHandle 을 낸다 (활성 창 포함)."""
    seen: set[int] = set()
    try:
        windows = com.XHwpWindows
    except Exception:
        return
    try:
        active = int(windows.Active_XHwpWindow.WindowHandle)
        if active:
            seen.add(active)
            yield active
    except Exception:
        pass
    count = 0
    try:
        count = int(windows.Count)
    except Exception:
        count = 0
    if count <= 0:
        # Count 를 못 읽으면 Item(0) 만이라도.
        try:
            handle = int(windows.Item(0).WindowHandle)
        except Exception:
            return
        if handle and handle not in seen:
            yield handle
        return
    for i in range(count):
        try:
            handle = int(windows.Item(i).WindowHandle)
        except Exception:
            continue
        if handle and handle not in seen:
            seen.add(handle)
            yield handle


def _com_has_hwnd(com: Any, hwnd: int) -> bool:
    if not hwnd:
        return False
    return any(handle == int(hwnd) for handle in _iter_window_handles(com))


def _show_window(com: Any, hwnd: int = 0) -> None:
    """해당 핸들의 창을 보이게 한다. Activate 는 없다 — Visible 만."""
    _make_window_current(com, hwnd)


def _make_window_current(com: Any, hwnd: int = 0) -> None:
    """고정 창을 현재 창으로 만든다.

    ``IXHwpWindow`` 에 Activate 는 없다. ``Visible = True`` 와
    ``XHwpDocuments.Item(i).SetActive_XHwpDocument()`` 를 쓴다.
    """
    win_index = -1
    try:
        windows = com.XHwpWindows
    except Exception:
        windows = None
    if windows is not None and hwnd:
        count = _windows_count(windows) or 8
        for i in range(max(count, 1)):
            try:
                win = windows.Item(i)
                if int(win.WindowHandle) == int(hwnd):
                    win.Visible = True
                    win_index = i
                    break
            except Exception:
                continue
    elif windows is not None:
        try:
            windows.Active_XHwpWindow.Visible = True
        except Exception:
            try:
                windows.Item(0).Visible = True
            except Exception:
                pass
        win_index = 0
    if win_index < 0:
        return
    try:
        docs = com.XHwpDocuments
        docs.Item(win_index).SetActive_XHwpDocument()
    except Exception:
        pass


def _pick_com_by_hwnd(instances: list[Any], hwnd: int | None) -> Any | None:
    """hwnd 가 있으면 그 핸들을 가진 인스턴스만 고른다. 없으면 None (ROT-first 금지).

    hwnd 가 없거나 0 이면 첫 인스턴스 (호출측이 pin 없을 때만 씀).
    """
    if hwnd:
        for com in instances:
            if _com_has_hwnd(com, hwnd):
                return com
        return None
    return instances[0] if instances else None


def list_open_documents() -> list[dict[str, Any]]:
    """ROT의 모든 실행 중 한/글 문서를 읽기 전용으로 열거한다.

    일반 ``connect`` 경로는 고정된 창을 현재 문서로 만들 수 있다. 반면 이 함수는
    ROT에서 얻은 객체의 ``XHwpDocuments``/``XHwpWindows`` 속성만 읽는다. 따라서
    문서 활성화, 화면 표시 변경, 캐럿 이동, 저장·닫기를 전혀 하지 않는다.

    ``PageCount``는 한/글 애플리케이션의 *현재 문서* 속성이다. 한 인스턴스에
    여러 문서가 있을 때 비활성 문서의 쪽 수를 얻으려고 활성화하지 않으며, 그런
    항목의 ``page_count``는 ``None``으로 둔다.
    """
    require_windows()
    records: list[dict[str, Any]] = []
    for moniker, com in _iter_running_hwp_com_instances():
        records.extend(_document_records_from_com(moniker, com))
    return sorted(
        records,
        key=lambda record: (
            int(record.get("pid") or 0),
            int(record.get("window_handle") or 0),
            int(record.get("document_index") or 0),
        ),
    )


def close_all_open_documents_discard() -> dict[str, Any]:
    """ROT에 있는 모든 한/글 문서를 문서 단위로 저장 없이 닫는다.

    이 함수는 명시적 ``--force``/``force=true`` 요청에서만 Engine이 호출한다.
    컬렉션 ``XHwpDocuments.Close``·``FileClose``·``Quit``는 쓰지 않는다. 각
    문서의 ``Close(False)``를 큰 index부터 실행해 컬렉션 index 이동으로 다른
    문서를 건너뛰지 않는다. 모든 문서를 닫은 인스턴스는 ``Quit``으로 끝내, 한/글이
    자동으로 새 빈 문서를 띄워 창을 남기는 동작도 막는다.
    """
    require_windows()
    closed: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    closed_instances: list[str] = []
    for moniker, com in _iter_running_hwp_com_instances():
        try:
            documents = com.XHwpDocuments
            count = int(getattr(documents, "Count", 0) or 0)
        except Exception as exc:
            failures.append({"instance": moniker, "error": f"문서 목록을 읽지 못했습니다: {exc}"})
            continue
        for index in range(max(0, count) - 1, -1, -1):
            record: dict[str, Any] = {"instance": moniker, "document_index": index}
            try:
                document = documents.Item(index)
                record["path"] = _safe_com_str(document, "FullName")
                modified = _safe_com_attr(document, "Modified")
                record["modified"] = bool(modified) if modified is not None else None
                close = getattr(document, "Close", None)
                if not callable(close):
                    raise HangulCommandError("문서 단위 Close를 제공하지 않습니다.")
                result = close(False)
                if result is False:
                    raise HangulCommandError("저장 없이 닫기에 실패했습니다.")
                closed.append(record)
            except Exception as exc:
                failures.append({**record, "error": str(exc) or "저장 없이 닫지 못했습니다."})
        # Close(False)는 한/글이 빈 문서를 새로 만들며 창을 유지할 수 있다. 이 명령은
        # 명시적으로 '모든 한/글 창'을 닫는 공개 파괴 명령이므로, 해당 인스턴스의
        # 모든 원래 문서를 Close한 경우에만 Quit으로 남은 빈 창을 종료한다.
        instance_failures = [failure for failure in failures if failure.get("instance") == moniker]
        if not instance_failures:
            try:
                quit_app = getattr(com, "Quit", None)
                if not callable(quit_app):
                    raise HangulCommandError("한/글 인스턴스 종료(Quit)를 제공하지 않습니다.")
                result = quit_app()
                if result is False:
                    raise HangulCommandError("한/글 인스턴스를 종료하지 못했습니다.")
                closed_instances.append(moniker)
            except Exception as exc:
                failures.append({"instance": moniker, "error": str(exc) or "한/글 창을 닫지 못했습니다."})
    return {"closed": closed, "closed_instances": closed_instances, "failures": failures}


def _iter_running_hwp_com_instances():
    """ROT의 실행 중 HwpObject를 IDispatch와 함께 낸다. 생성·활성화는 하지 않는다."""
    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore
    except ImportError as exc:
        raise HangulMissingError(MISSING_KO) from exc

    co_initialized = False
    try:
        pythoncom.CoInitialize()
        co_initialized = True
        context = pythoncom.CreateBindCtx(0)
        for rot, moniker in _iter_running_hwp_monikers():
            try:
                name = str(moniker.GetDisplayName(context, None))
                raw = rot.GetObject(moniker)
                dispatch = raw.QueryInterface(pythoncom.IID_IDispatch)
                yield name, win32com.client.Dispatch(dispatch)
            except Exception:
                # 다른 인스턴스가 종료 중이면 그 인스턴스만 건너뛴다. 나머지
                # 문서를 놓치지 않으며, 실패 때문에 새 한/글을 만들지 않는다.
                continue
    finally:
        if co_initialized:
            pythoncom.CoUninitialize()


def _document_records_from_com(moniker: str, com: Any) -> list[dict[str, Any]]:
    """한 HwpObject에서 활성화 없이 문서별 메타데이터를 읽는다."""
    try:
        documents = com.XHwpDocuments
        document_count = int(getattr(documents, "Count", 0) or 0)
    except Exception:
        return []
    try:
        windows = com.XHwpWindows
        window_count = int(getattr(windows, "Count", 0) or 0)
    except Exception:
        windows = None
        window_count = 0

    active_handle = _active_window_handle_readonly(windows)
    app_page_count = _safe_positive_int(getattr(com, "PageCount", None))
    records: list[dict[str, Any]] = []
    for index in range(max(0, document_count)):
        try:
            document = documents.Item(index)
        except Exception:
            continue
        window = _document_window_at(windows, window_count, index)
        window_handle = _safe_int(getattr(window, "WindowHandle", None)) if window else 0
        window_title, pid = _native_window_metadata(window_handle)
        is_active = bool(window_handle and window_handle == active_handle)
        # 한 인스턴스에 문서가 하나면 그것은 PageCount의 대상이다. 여러 문서일
        # 때는 활성 창만 PageCount를 읽을 수 있으며, 다른 문서를 활성화하지 않는다.
        page_count = app_page_count if (is_active or document_count == 1) else None
        path = _safe_com_str(document, "FullName")
        if not path and document_count == 1:
            path = _safe_com_str(com, "Path")
        modified_value = _safe_com_attr(document, "Modified")
        modified = bool(modified_value) if modified_value is not None else None
        visible_value = _safe_com_attr(window, "Visible") if window else None
        records.append(
            {
                "instance": moniker,
                "document_index": index,
                "window_handle": window_handle,
                "window_title": window_title,
                "pid": pid,
                "path": path,
                "unsaved": not bool(path),
                "modified": modified,
                "page_count": page_count,
                "active": is_active,
                "visible": bool(visible_value) if visible_value is not None else None,
            }
        )
    return records


def _document_window_at(windows: Any | None, count: int, index: int) -> Any | None:
    if windows is None or index >= count:
        return None
    try:
        return windows.Item(index)
    except Exception:
        return None


def _active_window_handle_readonly(windows: Any | None) -> int:
    if windows is None:
        return 0
    active = _active_hwp_window(windows)
    return _safe_int(getattr(active, "WindowHandle", None)) if active else 0


def _native_window_metadata(window_handle: int) -> tuple[str, int | None]:
    """Win32 창 제목·PID를 읽는다. 불가하면 빈 값만 반환한다."""
    if not window_handle:
        return "", None
    try:
        import win32gui  # type: ignore
        import win32process  # type: ignore

        title = str(win32gui.GetWindowText(int(window_handle)) or "")
        _thread_id, pid = win32process.GetWindowThreadProcessId(int(window_handle))
        return title, int(pid)
    except Exception:
        return "", None


def _safe_com_attr(obj: Any, name: str) -> Any | None:
    try:
        return getattr(obj, name)
    except Exception:
        return None


def _safe_com_str(obj: Any, name: str) -> str:
    value = _safe_com_attr(obj, name)
    return "" if value is None else str(value)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_positive_int(value: Any) -> int | None:
    number = _safe_int(value)
    return number if number > 0 else None


def _iter_running_hwp_monikers() -> Any:
    """ROT(Running Object Table)에서 HwpObject 모니커를 순회한다. (Windows 전용)"""
    import pythoncom  # type: ignore

    context = pythoncom.CreateBindCtx(0)
    rot = pythoncom.GetRunningObjectTable()
    enum = rot.EnumRunning()
    while True:
        monikers = enum.Next(1)
        if not monikers:
            return
        moniker = monikers[0]
        try:
            name = moniker.GetDisplayName(context, None)
        except Exception:
            continue
        if "HwpObject" in str(name):
            yield rot, moniker


def _hwp_running() -> bool:
    """실행 중인 한/글 인스턴스가 있는지. 판정 불가 시 True(기존 동작 유지)."""
    try:
        import pythoncom  # noqa: F401  # type: ignore
    except ImportError:
        return True
    try:
        for _rot, _mk in _iter_running_hwp_monikers():
            return True
        return False
    except Exception:
        return True


def _attach_running_com(hwnd: int | None = None) -> Any | None:
    """ROT 의 한/글 인스턴스에 IDispatch 로 붙는다.

    ``hwnd`` 가 있으면 그 WindowHandle 을 가진 인스턴스만 고른다.
    일치하는 창이 없으면 None (ROT 첫 객체 ``!HwpObject.120.1`` 을 조용히 쓰지 않는다).
    hwnd 가 없으면 첫 인스턴스.
    """
    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore
    except ImportError:
        return None
    found: list[Any] = []
    try:
        for rot, moniker in _iter_running_hwp_monikers():
            try:
                obj = rot.GetObject(moniker)
                disp = obj.QueryInterface(pythoncom.IID_IDispatch)
                found.append(win32com.client.Dispatch(disp))
            except Exception:
                continue
        picked = _pick_com_by_hwnd(found, hwnd)
        if picked is not None and hwnd:
            _make_window_current(picked, int(hwnd))
        return picked
    except Exception:
        return None


def _ensure_document_if_empty(com: Any) -> bool:
    """문서가 전혀 없는 새 한/글 객체에만 빈 문서를 한 번 만든다.

    ``EnsureDispatch``가 이미 제공한 초기 빈 문서에 Add/FileNew를 다시 실행하면
    ``open --new`` 한 번에 빈 문서가 여러 장 생긴다. 문서 수를 읽지 못한 경우도
    중복 생성보다 안전하게 아무 작업도 하지 않는다.
    """
    try:
        docs = com.XHwpDocuments
        count = int(getattr(docs, "Count", 0) or 0)
    except Exception:
        return False
    if count > 0:
        return False
    try:
        docs.Add(False)
    except Exception:
        try:
            result = com.HAction.Run("FileNew")
        except Exception as exc:
            raise HangulCommandError("새 빈 문서를 만들지 못했습니다.") from exc
        if result is False:
            raise HangulCommandError("새 빈 문서를 만들지 못했습니다.")
    return True


def _infer_format(path: str, fmt: str) -> str:
    if fmt:
        return fmt.upper()
    lower = path.lower()
    if lower.endswith(".hwpx"):
        return "HWPX"
    if lower.endswith(".pdf"):
        return "PDF"
    if lower.endswith(".html") or lower.endswith(".htm"):
        return "HTML"
    return "HWP"


def _a1(row: int, col: int) -> str:
    return f"{_col_letters(col)}{row + 1}"


def _col_letters(col: int) -> str:
    n = col + 1
    letters = ""
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _parse_a1(addr: str) -> tuple[int, int]:
    raw = addr.strip().upper()
    i = 0
    while i < len(raw) and raw[i].isalpha():
        i += 1
    if i == 0 or i == len(raw):
        raise UsageError(f"셀 주소가 올바르지 않습니다: {addr}")
    letters, digits = raw[:i], raw[i:]
    if not digits.isdigit():
        raise UsageError(f"셀 주소가 올바르지 않습니다: {addr}")
    col = 0
    for ch in letters:
        col = col * 26 + (ord(ch) - 64)
    return int(digits) - 1, col - 1


def parse_a1(addr: str) -> tuple[int, int]:
    return _parse_a1(addr)


def a1(row: int, col: int) -> str:
    return _a1(row, col)


def expand_range(cell_range: str) -> list[str]:
    raw = cell_range.strip().upper()
    if ":" not in raw:
        parse_a1(raw)
        return [raw]
    start, end = raw.split(":", 1)
    r0, c0 = parse_a1(start)
    r1, c1 = parse_a1(end)
    if r1 < r0:
        r0, r1 = r1, r0
    if c1 < c0:
        c0, c1 = c1, c0
    return [_a1(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)]
