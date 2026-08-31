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
    def connect(cls, new: bool = False, allow_launch: bool = False) -> HangulCanvas:
        """열린 한/글 창에 붙는다.

        기본은 *붙기만* 한다: 실행 중인 인스턴스가 없으면 한/글을 새로 띄우지 않고
        한국어 오류를 낸다 (pyhwpx ``Hwp()`` 는 없으면 자동 실행하므로 ROT 로 먼저 확인).
        ``new=True`` 또는 ``allow_launch=True`` (open 명령) 일 때만 실행을 허용한다.
        """
        require_windows()
        if not new and not allow_launch and not _hwp_running():
            raise HangulMissingError(NO_WINDOW_KO)
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
            last_error = exc
        try:
            import win32com.client  # type: ignore

            com: Any | None = None
            if not new:
                # Dispatch 는 새 인스턴스를 띄우므로, 붙을 때는 반드시 ROT 로 기존 창에 바인딩.
                com = _attach_running_com()
                if com is None and not allow_launch:
                    raise HangulMissingError(NO_WINDOW_KO)
            if com is None:
                com = win32com.client.gencache.EnsureDispatch("HWPFrame.HwpObject")
            try:
                com.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
            except Exception:
                pass
            try:
                com.XHwpWindows.Item(0).Visible = True
            except Exception:
                pass
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
        """연결된 한/글 창의 윈도우 핸들. 대상 창 고정(pinning)에 쓴다. 실패 시 0."""
        try:
            return int(self.com.XHwpWindows.Item(0).WindowHandle)
        except Exception:
            return 0

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

        셀의 실제 조판 줄 수는 셀 리스트의 처음/끝으로 이동한 뒤 KeyIndicator의
        ``line`` 차이로 측정한다. 이동/상태바 조회가 실패한 셀만 명시 줄바꿈 수로
        보수적으로 대체한다.
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
                text = self.get_selected_text().rstrip("\x00")
                line_count, measured = self._cell_line_count(text)
                margins = self._get_cell_margin_mm()
                height = self._get_row_height_mm()
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
                        "font_size_pt": self._get_font_size_pt(),
                        "line_spacing_percent": self._get_line_spacing_percent(),
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
        if not widths_mm:
            return 0
        self.get_into_nth_table(n)
        self.assert_no_dialog()
        if self.px:
            try:
                ok = self.px.adjust_cellwidth(widths_mm, as_="mm")
            except Exception as exc:
                raise HangulCommandError(f"{n}번 표 열 너비 조절에 실패했습니다: {exc}") from exc
            if not ok:
                raise HangulCommandError(f"{n}번 표 열 너비 조절 액션이 실패했습니다.")
            self.assert_no_dialog()
            # pyhwpx adjust_cellwidth(list)는 열마다 TablePropertyDialog를 한 번 실행한다.
            return len(widths_mm)

        addresses = self._table_addresses()
        for col, width in enumerate(widths_mm):
            addr = next(
                (addr for addr in addresses if _parse_a1(addr)[1] == col),
                None,
            )
            if addr is None:
                raise HangulCommandError(
                    f"{n}번 표 {col + 1}열은 병합 구조 때문에 너비를 조절할 셀을 찾지 못했습니다."
                )
            self.get_into_nth_table(n)
            self.goto_addr(addr)
            if not (
                self.run("TableColPageUp")
                and self.run("TableCellBlock")
                and self.run("TableCellBlockExtend")
                and self.run("TableColPageDown")
            ):
                raise HangulCommandError(f"{n}번 표 {col + 1}열 선택에 실패했습니다.")
            try:
                pset = self.com.HParameterSet.HShapeObject
                self.com.HAction.GetDefault("TablePropertyDialog", pset.HSet)
                pset.HSet.SetItem("ShapeType", 3)
                pset.HSet.SetItem("ShapeCellSize", 1)
                pset.ShapeTableCell.Width = self._mm_to_hwpunit(width)
                ok = bool(self.com.HAction.Execute("TablePropertyDialog", pset.HSet))
            except Exception as exc:
                raise HangulCommandError(
                    f"{n}번 표 {col + 1}열 너비 조절에 실패했습니다: {exc}"
                ) from exc
            if not ok:
                raise HangulCommandError(f"{n}번 표 {col + 1}열 너비 조절 액션이 실패했습니다.")
            self.assert_no_dialog()
        return len(widths_mm)

    def set_table_row_height(self, n: int, row: int, height_mm: float) -> int:
        """행 높이를 mm로 설정한다. 성공하면 한/글 액션 수 1."""
        self.get_into_nth_table(n)
        self.goto_addr(_a1(row, 0))
        self.assert_no_dialog()
        if self.px:
            try:
                ok = self.px.set_row_height(height_mm, as_="mm")
            except Exception as exc:
                raise HangulCommandError(f"{n}번 표 {row + 1}행 높이 조절에 실패했습니다: {exc}") from exc
        else:
            try:
                pset = self.com.HParameterSet.HShapeObject
                self.com.HAction.GetDefault("TablePropertyDialog", pset.HSet)
                pset.HSet.SetItem("ShapeType", 3)
                pset.HSet.SetItem("ShapeCellSize", 1)
                pset.ShapeTableCell.Height = self._mm_to_hwpunit(height_mm)
                ok = bool(self.com.HAction.Execute("TablePropertyDialog", pset.HSet))
            except Exception as exc:
                raise HangulCommandError(
                    f"{n}번 표 {row + 1}행 높이 조절에 실패했습니다: {exc}"
                ) from exc
        if not ok:
            raise HangulCommandError(f"{n}번 표 {row + 1}행 높이 조절 액션이 실패했습니다.")
        self.assert_no_dialog()
        return 1

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
        if self.px:
            if not self.px.set_cell_margin(
                left=left, right=right, top=top, bottom=bottom, as_="mm"
            ):
                raise HangulCommandError(
                    "셀 안 여백을 적용하지 못했습니다. 캐럿이 표 셀 안에 있어야 합니다."
                )
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

    def set_table_inside_margin(
        self, left: float, right: float, top: float, bottom: float
    ) -> None:
        """캐럿이 들어 있는 표의 모든 셀 안쪽 여백을 mm 로 일괄 지정."""
        if self.px:
            if not self.px.set_table_inside_margin(
                left=left, right=right, top=top, bottom=bottom, as_="mm"
            ):
                raise HangulCommandError(
                    "표 안 여백을 적용하지 못했습니다. 캐럿이 표 안에 있어야 합니다."
                )
            return
        if not self.is_cell():
            raise HangulCommandError(
                "캐럿이 표 안에 있지 않아 표 안 여백을 적용할 수 없습니다."
            )
        # pyhwpx set_table_inside_margin 소스와 동일: TablePropertyDialog + CellMargin*
        ok = False
        try:
            pset = self.com.HParameterSet.HShapeObject
            self.com.HAction.GetDefault("TablePropertyDialog", pset.HSet)
            pset.CellMarginLeft = self._mm_to_hwpunit(left)
            pset.CellMarginRight = self._mm_to_hwpunit(right)
            pset.CellMarginTop = self._mm_to_hwpunit(top)
            pset.CellMarginBottom = self._mm_to_hwpunit(bottom)
            ok = bool(self.com.HAction.Execute("TablePropertyDialog", pset.HSet))
        except Exception as exc:
            raise HangulCommandError(f"표 안 여백 적용에 실패했습니다: {exc}") from exc
        if not ok:
            raise HangulCommandError("표 안 여백(TablePropertyDialog) 액션이 실패했습니다.")

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

    def _key_indicator(self) -> tuple[Any, ...]:
        try:
            value = self.px.key_indicator() if self.px else self.com.KeyIndicator()
            return tuple(value)
        except Exception:
            return ()

    def _cell_line_count(self, text: str) -> tuple[int, bool]:
        saved = self.get_pos()
        try:
            if not self.run("MoveListBegin"):
                return hard_line_count(text), False
            start = self._key_indicator()
            if not self.run("MoveListEnd"):
                return hard_line_count(text), False
            end = self._key_indicator()
            if len(start) > 5 and len(end) > 5:
                count = int(end[5]) - int(start[5]) + 1
                if count >= 1:
                    return count, True
        except Exception:
            pass
        finally:
            self.set_pos(saved)
        return hard_line_count(text), False

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


def _attach_running_com() -> Any | None:
    """ROT 에 등록된 기존 한/글 인스턴스에 IDispatch 로 붙는다. 없으면 None."""
    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore
    except ImportError:
        return None
    try:
        for rot, moniker in _iter_running_hwp_monikers():
            try:
                obj = rot.GetObject(moniker)
                disp = obj.QueryInterface(pythoncom.IID_IDispatch)
                return win32com.client.Dispatch(disp)
            except Exception:
                continue
    except Exception:
        return None
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