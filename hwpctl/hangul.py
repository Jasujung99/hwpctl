"""한/글 2022 캔버스 어댑터.

pyhwpx 를 우선하고, 없으면 win32com ``HWPFrame.HwpObject``.
키 입력(SendKeys) 은 쓰지 않는다. 한글 2024 전용 GSG/SelectCtrl/메타태그는 쓰지 않는다.
"""

from __future__ import annotations

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

        ``hwnd`` 가 있으면 ROT 첫 창이 아니라 그 ``WindowHandle`` 을 가진 창을 고른다.
        (여러 창이 열려 있을 때 엉뚱한 문서에 쓰는 것을 막는다.)
        """
        require_windows()
        if not new and not allow_launch and not _hwp_running():
            raise HangulMissingError(NO_WINDOW_KO)
        last_error: Exception | None = None
        try:
            from pyhwpx import Hwp  # type: ignore

            if hwnd and not new:
                # Hwp() 는 '마지막 접근 창' 또는 ROT 첫 인스턴스에 붙는다.
                # 고정된 창이 있으면 핸들로 직접 고른다.
                found = _attach_running_com(hwnd=hwnd)
                if found is not None:
                    return cls(px=None, com=found, backend="win32com")
            px = Hwp(new=new, visible=True, register_module=True)
            com = getattr(px, "hwp", None) or getattr(px, "Application", None) or px
            if hwnd and not new and not _com_has_hwnd(com, hwnd):
                found = _attach_running_com(hwnd=hwnd)
                if found is not None:
                    return cls(px=None, com=found, backend="win32com")
            return cls(px=px, com=com, backend="pyhwpx")
        except HangulMissingError:
            raise
        except ImportError:
            last_error = None
        except Exception as exc:  # COM 실패
            last_error = exc
        try:
            import win32com.client  # type: ignore

            com: Any | None = None
            if not new:
                # Dispatch 는 새 인스턴스를 띄우므로, 붙을 때는 반드시 ROT 로 기존 창에 바인딩.
                # hwnd 가 있으면 ROT 첫 창이 아니라 그 핸들의 창을 고른다.
                com = _attach_running_com(hwnd=hwnd)
                if com is None and not allow_launch:
                    raise HangulMissingError(NO_WINDOW_KO)
            if com is None:
                com = win32com.client.gencache.EnsureDispatch("HWPFrame.HwpObject")
            try:
                com.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
            except Exception:
                pass
            _show_window(com, hwnd)
            if new:
                try:
                    com.XHwpDocuments.Add(False)
                except Exception:
                    com.HAction.Run("FileNew")
            return cls(px=None, com=com, backend="win32com")
        except HangulMissingError:
            raise
        except ImportError as exc:
            raise HangulMissingError(MISSING_KO) from exc
        except Exception as exc:
            raise HangulMissingError(CONNECT_KO) from (last_error or exc)

    def window_handle(self) -> int:
        """연결된 한/글 창의 윈도우 핸들. 대상 창 고정(pinning)에 쓴다. 실패 시 0.

        ``XHwpWindows.Item(0)`` 은 *처음 연* 창이라 ``open --new`` 직후 새 창과
        어긋난다. 활성 창(``Active_XHwpWindow``)을 우선한다.
        """
        return _window_handle_of(self.com)

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
            rows = int(self._call_px("get_row_num") or self._guess_rows())
            cols = int(self._call_px("get_col_num") or self._guess_cols())
            preview: list[list[str]] = []
            for r in range(min(rows, preview_rows)):
                line: list[str] = []
                for c in range(min(cols, preview_cols)):
                    try:
                        self.goto_addr(_a1(r, c))
                        line.append(self.get_selected_text())
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
                font_size, line_spacing = self._get_cell_typography()
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
        if not (
            self.run("TableColPageUp")
            and self.run("TableCellBlock")
            and self.run("TableCellBlockExtend")
            and self.run("TableColPageDown")
        ):
            raise HangulCommandError("현재 열 선택에 실패했습니다.")
        try:
            pset = self.com.HParameterSet.HShapeObject
            self.com.HAction.GetDefault("TablePropertyDialog", pset.HSet)
            pset.HSet.SetItem("ShapeType", 3)
            pset.HSet.SetItem("ShapeCellSize", 1)
            pset.ShapeTableCell.Width = self._mm_to_hwpunit(width_mm)
            ok = bool(self.com.HAction.Execute("TablePropertyDialog", pset.HSet))
        except Exception as exc:
            raise HangulCommandError(f"현재 열 너비 조절에 실패했습니다: {exc}") from exc
        if not ok:
            raise HangulCommandError("현재 열 너비 조절 액션이 실패했습니다.")
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
        face: str = "",
        height_pt: float | None = None,
        text_color: str = "",
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
        if not kwargs:
            return
        if self.px:
            self.px.set_font(**kwargs)
            return
        pset = self.com.HParameterSet.HCharShape
        self.com.HAction.GetDefault("CharShape", pset.HSet)
        if "Bold" in kwargs:
            pset.Bold = bool(kwargs["Bold"])
        if "Italic" in kwargs:
            pset.Italic = bool(kwargs["Italic"])
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
        self.com.HAction.Execute("CharShape", pset.HSet)

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
        row, col = _parse_a1(addr)
        if not self.is_cell():
            raise HangulCommandError(
                f"캐럿이 표 안에 있지 않아 셀 {addr} 로 이동할 수 없습니다."
            )
        # A1 로: TableColBegin(행의 첫 칸) + TableColPageUp(열의 첫 행)
        if not self.run("TableColBegin") or not self.run("TableColPageUp"):
            raise HangulCommandError(f"셀 {addr} 로 이동하지 못했습니다 (표 시작 이동 실패).")
        for _ in range(col):
            if not self.run("TableRightCell"):
                raise HangulCommandError(f"셀 {addr} 로 이동하지 못했습니다 (열 이동 실패).")
        for _ in range(row):
            if not self.run("TableLowerCell"):
                raise HangulCommandError(f"셀 {addr} 로 이동하지 못했습니다 (행 이동 실패).")
        if not self.is_cell():
            raise HangulCommandError(f"셀 {addr} 이동 후 캐럿이 표 밖에 있습니다.")
        current = self.current_cell_addr()
        want = addr.strip().upper()
        if current and current != want:
            raise HangulCommandError(
                f"셀 이동 결과가 다릅니다 (요청 {want}, 현재 {current}). "
                "표 크기를 벗어난 주소일 수 있습니다."
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

    def select_cell_range(self, start: str, end: str) -> None:
        """start~end 셀을 셀블록으로 선택. (F5 셀블록 후 이동 액션이 블록을 확장)"""
        r0, c0 = _parse_a1(start)
        r1, c1 = _parse_a1(end)
        if r1 < r0:
            r0, r1 = r1, r0
        if c1 < c0:
            c0, c1 = c1, c0
        self.goto_addr(_a1(r0, c0))
        if not self.run("TableCellBlock"):
            raise HangulCommandError("셀블록 시작(TableCellBlock)에 실패했습니다.")
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
        self.goto_addr(_a1(r0, c0))
        self.assert_no_dialog()
        if not self.run("TableCellBlock"):
            raise HangulCommandError("셀 합치기 선택 시작(TableCellBlock)에 실패했습니다.")
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
        if self.px:
            try:
                self.px.close(is_dirty=False)
                return
            except Exception:
                pass
        try:
            self.com.XHwpDocuments.Close(False)
        except Exception:
            self.run("FileClose")

    def undo_once(self) -> None:
        self.run("Undo")

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

    def goto_page(self, page_index_1: int) -> None:
        if page_index_1 < 1:
            raise UsageError("쪽 번호는 1부터입니다.")
        if self.px:
            self.px.goto_page(page_index=page_index_1)
            return
        try:
            self.com.GotoPage(page_index_1)
        except Exception:
            self.run("MovePageBegin")
            for _ in range(page_index_1 - 1):
                self.run("MovePageDown")

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
        seen: set[str] = set()
        try:
            if not self.run("TableColBegin") or not self.run("TableColPageUp"):
                return []
            for _ in range(5000):
                addr = self.current_cell_addr()
                if not addr or addr in seen:
                    break
                seen.add(addr)
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

    def _get_cell_typography(self) -> tuple[float, float]:
        """셀 전체를 순회해 가장 큰 글자와 줄간격을 읽는다.

        한 지점만 표본으로 삼으면 혼합 서식 셀의 큰 글자를 놓쳐 행을 너무 낮출 수
        있다. MoveNextChar는 현재 셀 리스트 안에서만 움직이며 편집 액션이 아니다.
        매우 긴 셀은 5000자까지만 확인하고, 이 경우에도 시작점 표본보다 안전하다.
        """
        saved = self.get_pos()
        max_font = 10.0
        max_spacing = 160.0
        try:
            if not self.run("MoveListBegin"):
                return self._get_font_size_pt(), self._get_line_spacing_percent()
            for _ in range(5000):
                max_font = max(max_font, self._get_font_size_pt())
                max_spacing = max(max_spacing, self._get_line_spacing_percent())
                if not self.run("MoveNextChar"):
                    break
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
            if self.px:
                info = self.px.key_indicator()
                return int(info[3])
        except Exception:
            pass
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


def _window_handle_of(com: Any) -> int:
    """COM 객체가 가리키는 창의 WindowHandle. 활성 창 우선, 없으면 Item(0). 실패 시 0."""
    try:
        return int(com.XHwpWindows.Active_XHwpWindow.WindowHandle)
    except Exception:
        pass
    try:
        return int(com.XHwpWindows.Item(0).WindowHandle)
    except Exception:
        return 0


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
    """해당 핸들의 창(없으면 활성/첫 창)을 보이게 한다."""
    try:
        windows = com.XHwpWindows
    except Exception:
        return
    if hwnd:
        count = 0
        try:
            count = int(windows.Count)
        except Exception:
            count = 8  # Count 미지원 시 몇 개만 훑는다
        for i in range(max(count, 1)):
            try:
                win = windows.Item(i)
                if int(win.WindowHandle) == int(hwnd):
                    win.Visible = True
                    return
            except Exception:
                continue
    try:
        windows.Active_XHwpWindow.Visible = True
        return
    except Exception:
        pass
    try:
        windows.Item(0).Visible = True
    except Exception:
        pass


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


def _attach_running_com(hwnd: int = 0) -> Any | None:
    """ROT 의 한/글 인스턴스에 IDispatch 로 붙는다.

    ``hwnd`` 가 있으면 그 WindowHandle 을 가진 창만 고른다 (ROT 첫 창 금지).
    없거나 못 찾으면, hwnd 미지정일 때만 첫 인스턴스를 반환한다.
    """
    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore
    except ImportError:
        return None
    first: Any | None = None
    try:
        for rot, moniker in _iter_running_hwp_monikers():
            try:
                obj = rot.GetObject(moniker)
                disp = obj.QueryInterface(pythoncom.IID_IDispatch)
                com = win32com.client.Dispatch(disp)
            except Exception:
                continue
            if first is None:
                first = com
            if hwnd and _com_has_hwnd(com, hwnd):
                _show_window(com, hwnd)
                return com
        if hwnd:
            return None
        return first
    except Exception:
        return None


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