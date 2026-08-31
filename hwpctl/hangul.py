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

    def list_tables(self, preview_rows: int = 8) -> list[dict[str, Any]]:
        count = self._table_count()
        tables: list[dict[str, Any]] = []
        for i in range(count):
            self.get_into_nth_table(i)
            rows = int(self._call_px("get_row_num") or self._guess_rows())
            cols = int(self._call_px("get_col_num") or self._guess_cols())
            preview: list[list[str]] = []
            for r in range(min(rows, preview_rows)):
                line: list[str] = []
                for c in range(cols):
                    try:
                        self.goto_addr(_a1(r, c))
                        line.append(self.get_selected_text())
                    except HangulCommandError:
                        line.append("")
                preview.append(line)
            tables.append({"index": i, "rows": rows, "cols": cols, "preview": preview})
        return tables

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
        pset = self.com.HParameterSet.HParaShape
        self.com.HAction.GetDefault("ParagraphShape", pset.HSet)
        try:
            pset.AlignType = key
        except Exception:
            pset.HSet.SetItem("AlignType", key)
        self.com.HAction.Execute("ParagraphShape", pset.HSet)

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
        pset = self.com.HParameterSet.HCellBorderFill
        self.com.HAction.GetDefault("CellFill", pset.HSet)
        try:
            pset.FillAttr.Type = 1
            pset.FillAttr.FaceColor = rgb_to_bgr_int(rgb)
        except Exception:
            try:
                pset.HSet.SetItem("FillAttr.FaceColor", rgb_to_bgr_int(rgb))
            except Exception as exc:
                raise HangulCommandError(f"셀 배경을 칠하지 못했습니다: {exc}") from exc
        self.com.HAction.Execute("CellFill", pset.HSet)

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

    # --- 내부 --------------------------------------------------------------

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