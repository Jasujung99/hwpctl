"""작업 전 환경 점검(``doctor``). 문서·창·캐럿을 바꾸지 않는 읽기 전용 검사다.

긴 작업이 중간에 막힌 원인은 대부분 명령 자체가 아니라 환경이었다: 응답 없는
한/글, 숨은 대화상자, 사라진 고정 창, 한/글 실행 뒤 설치한 글꼴, 저장소보다
뒤처진 hwpctl. 이 모듈은 그 상태를 작업 시작 전에 한 번에 보고한다.

시스템 조회는 ``SystemProbe`` 로 모아 두어 테스트가 가짜 프로브를 주입할 수 있다.
창 제목은 ``InternalGetWindowText`` 로 읽는다. ``GetWindowText`` 는 응답 없는
창에 메시지를 보내 점검 자체가 멈출 수 있기 때문이다.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

HWP_EXE = "hwp.exe"
DIALOG_CLASS = "#32770"
GW_OWNER = 4


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str
    created: float | None  # epoch seconds


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    pid: int
    class_name: str
    title: str
    visible: bool
    owner: int
    hung: bool


@dataclass(frozen=True)
class FontFace:
    name: str
    path: str | None = None
    installed_at: float | None = None  # epoch seconds (파일 생성·수정 시각 중 늦은 값)


@dataclass
class DoctorReport:
    checks: list[dict[str, Any]] = field(default_factory=list)

    def add(self, name: str, status: str, message: str, **detail: Any) -> None:
        entry = {"name": name, "status": status, "message": message}
        entry.update(detail)
        self.checks.append(entry)

    def as_dict(self) -> dict[str, Any]:
        errors = [c for c in self.checks if c["status"] == "error"]
        warnings = [c for c in self.checks if c["status"] == "warn"]
        return {
            "ok": not errors,
            "command": "doctor",
            "errors": len(errors),
            "warnings": len(warnings),
            "checks": self.checks,
        }


# --------------------------------------------------------------------------
# 시스템 프로브 (Windows ctypes/winreg). 비 Windows 에서는 빈 결과.
# --------------------------------------------------------------------------


class SystemProbe:
    """실제 시스템을 읽는다. 각 메서드는 실패해도 예외 대신 빈 값을 돌려준다."""

    def is_windows(self) -> bool:
        return sys.platform == "win32"

    def processes(self) -> list[ProcessInfo]:
        if not self.is_windows():
            return []
        try:
            return list(_toolhelp_processes())
        except Exception:
            return []

    def windows(self) -> list[WindowInfo]:
        if not self.is_windows():
            return []
        try:
            return list(_enum_windows())
        except Exception:
            return []

    def fonts(self) -> dict[str, FontFace]:
        if not self.is_windows():
            return {}
        faces: dict[str, FontFace] = {}
        try:
            for face in _registry_fonts():
                faces.setdefault(_font_key(face.name), face)
        except Exception:
            pass
        try:
            for family in _gdi_font_families():
                faces.setdefault(_font_key(family), FontFace(family))
        except Exception:
            pass
        return faces

    def repository(self) -> dict[str, Any] | None:
        return _repository_state(Path(__file__).resolve().parents[1])

    def documents(self) -> list[dict[str, Any]] | None:
        try:
            from hwpctl.hangul import list_open_documents

            return list_open_documents()
        except Exception:
            return None

    def now(self) -> float:
        return time.time()


def run_doctor(
    *,
    fonts: Iterable[str] | None = None,
    target_hwnd: int | None = None,
    probe: SystemProbe | None = None,
) -> dict[str, Any]:
    """환경 점검 결과를 ``{"ok", "errors", "warnings", "checks": [...]}`` 로 돌려준다."""

    probe = probe or SystemProbe()
    report = DoctorReport()
    requested_fonts = [str(f).strip() for f in (fonts or []) if str(f).strip()]

    if not probe.is_windows():
        report.add("platform", "error", "한/글 자동화는 Windows에서만 동작합니다.")
        return report.as_dict()

    processes = [p for p in probe.processes() if p.name.lower() == HWP_EXE]
    windows = probe.windows()
    hwp_pids = {p.pid for p in processes}
    hwp_windows = [w for w in windows if w.pid in hwp_pids]
    main_windows = [w for w in hwp_windows if w.visible and not w.owner and w.class_name != DIALOG_CLASS]

    _check_processes(report, processes, main_windows)
    blocked = _check_hung(report, main_windows)
    blocked = _check_dialogs(report, hwp_windows, hwp_pids) or blocked
    _check_pin(report, target_hwnd, main_windows)
    _check_fonts(report, requested_fonts, probe.fonts(), processes, main_windows)
    _check_repository(report, probe.repository())

    if main_windows and not blocked:
        documents = probe.documents()
        if documents is None:
            report.add("documents", "warn", "열린 문서를 COM으로 읽지 못했습니다.")
        else:
            report.add(
                "documents",
                "ok" if documents else "warn",
                f"열린 한/글 문서 {len(documents)}개" if documents else "열린 한/글 문서가 없습니다.",
                documents=[
                    {k: d.get(k) for k in ("window_handle", "path", "modified", "active")}
                    for d in documents
                ],
            )
    elif main_windows:
        report.add("documents", "skip", "한/글이 응답하지 않거나 대화상자가 있어 문서 조회를 건너뜁니다.")
    return report.as_dict()


def _check_processes(report: DoctorReport, processes: list[ProcessInfo], main_windows: list[WindowInfo]) -> None:
    with_window = {w.pid for w in main_windows}
    windowless = [p for p in processes if p.pid not in with_window]
    if not processes:
        report.add("hangul", "warn", "실행 중인 한/글이 없습니다. open(new=true) 로 새 창을 여세요.")
        return
    report.add(
        "hangul",
        "ok" if with_window else "warn",
        f"한/글 프로세스 {len(processes)}개, 창이 있는 프로세스 {len(with_window)}개",
        processes=[{"pid": p.pid, "has_window": p.pid in with_window} for p in processes],
    )
    if windowless:
        report.add(
            "windowless_hangul",
            "warn",
            "창 없는 한/글 프로세스가 있습니다. 중단된 COM 활성화의 잔재일 수 있습니다. "
            "작업 중인 문서와 무관하면 종료를 고려하세요.",
            pids=[p.pid for p in windowless],
        )


def _check_hung(report: DoctorReport, main_windows: list[WindowInfo]) -> bool:
    hung = [w for w in main_windows if w.hung]
    if hung:
        report.add(
            "responding",
            "error",
            "응답 없는 한/글 창이 있습니다. 이 상태에서 명령을 보내면 호출이 멈춥니다.",
            windows=[{"hwnd": w.hwnd, "pid": w.pid, "title": w.title} for w in hung],
        )
        return True
    if main_windows:
        report.add("responding", "ok", "한/글 창이 응답합니다.")
    return False


def _check_dialogs(report: DoctorReport, hwp_windows: list[WindowInfo], hwp_pids: set[int]) -> bool:
    dialogs = [w for w in hwp_windows if w.visible and w.class_name == DIALOG_CLASS]
    if dialogs:
        report.add(
            "dialogs",
            "error",
            "한/글 대화상자가 떠 있습니다(예: 복구·보안·저장 안내). 닫은 뒤 작업하세요.",
            dialogs=[{"hwnd": w.hwnd, "pid": w.pid, "title": w.title or "대화상자"} for w in dialogs],
        )
        return True
    if hwp_pids:
        report.add("dialogs", "ok", "떠 있는 한/글 대화상자가 없습니다.")
    return False


def _check_pin(report: DoctorReport, target_hwnd: int | None, main_windows: list[WindowInfo]) -> None:
    if not target_hwnd:
        report.add("pin", "ok", "고정된 창이 없습니다. 첫 명령이 활성 창을 고정합니다.")
        return
    if any(w.hwnd == int(target_hwnd) for w in main_windows):
        report.add("pin", "ok", f"고정된 창(핸들 {target_hwnd})이 살아 있습니다.")
        return
    report.add(
        "pin",
        "warn",
        f"고정된 창(핸들 {target_hwnd})이 없습니다. 일반 명령은 실패하므로 open 으로 다시 고정하세요.",
        target_hwnd=int(target_hwnd),
    )


def _check_fonts(
    report: DoctorReport,
    requested: list[str],
    installed: dict[str, FontFace],
    processes: list[ProcessInfo],
    main_windows: list[WindowInfo],
) -> None:
    if not requested:
        return
    live = {w.pid for w in main_windows}
    started = [p.created for p in processes if p.pid in live and p.created]
    hwp_started = min(started) if started else None
    for name in requested:
        face = installed.get(_font_key(name))
        if face is None:
            report.add(
                "font",
                "error",
                f"글꼴 '{name}'이(가) 설치되어 있지 않습니다. 설치된 글꼴로 바꾸세요.",
                font=name,
                installed=False,
            )
        elif hwp_started and face.installed_at and face.installed_at > hwp_started:
            report.add(
                "font",
                "error",
                f"글꼴 '{name}'은(는) 한/글 실행 뒤에 설치되어 한/글이 인식하지 못합니다. 한/글을 다시 시작하세요.",
                font=name,
                installed=True,
                restart_required=True,
            )
        else:
            report.add("font", "ok", f"글꼴 '{name}' 사용 가능", font=name, installed=True)


def _check_repository(report: DoctorReport, repo: dict[str, Any] | None) -> None:
    if not repo:
        return
    behind = repo.get("behind")
    detail = {k: repo.get(k) for k in ("branch", "head", "upstream", "behind", "ahead", "dirty")}
    if behind:
        report.add(
            "repository",
            "warn",
            f"실행 중인 hwpctl이 {repo.get('upstream')}보다 {behind}커밋 뒤처져 있습니다. "
            "이미 고쳐진 버그를 다시 만날 수 있으니 갱신 후 MCP를 재연결하세요.",
            **detail,
        )
    else:
        report.add("repository", "ok", "hwpctl이 기준 브랜치와 같거나 앞서 있습니다.", **detail)


# --------------------------------------------------------------------------
# 글꼴·저장소 헬퍼
# --------------------------------------------------------------------------


def _font_key(name: str) -> str:
    return "".join(str(name).split()).casefold()


_REGISTRY_SUFFIXES = (" (TrueType)", " (OpenType)", " (All res)", " (VGA res)")


def _registry_fonts() -> Iterable[FontFace]:
    import winreg  # type: ignore

    windir = os.environ.get("WINDIR", r"C:\Windows")
    roots = (
        (winreg.HKEY_LOCAL_MACHINE, Path(windir) / "Fonts"),
        (winreg.HKEY_CURRENT_USER, Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"),
    )
    key_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
    for hive, default_dir in roots:
        try:
            key = winreg.OpenKey(hive, key_path)
        except OSError:
            continue
        with key:
            index = 0
            while True:
                try:
                    value_name, value, _kind = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                label = str(value_name)
                for suffix in _REGISTRY_SUFFIXES:
                    if label.endswith(suffix):
                        label = label[: -len(suffix)]
                        break
                path = Path(str(value))
                if not path.is_absolute():
                    path = default_dir / path
                installed_at = None
                try:
                    stat = path.stat()
                    installed_at = max(stat.st_mtime, stat.st_ctime)
                except OSError:
                    pass
                for part in label.split(" & "):
                    if part.strip():
                        yield FontFace(part.strip(), str(path), installed_at)


def _gdi_font_families() -> Iterable[str]:
    import ctypes
    from ctypes import wintypes

    class LOGFONTW(ctypes.Structure):
        _fields_ = [
            ("lfHeight", wintypes.LONG), ("lfWidth", wintypes.LONG), ("lfEscapement", wintypes.LONG),
            ("lfOrientation", wintypes.LONG), ("lfWeight", wintypes.LONG), ("lfItalic", wintypes.BYTE),
            ("lfUnderline", wintypes.BYTE), ("lfStrikeOut", wintypes.BYTE), ("lfCharSet", wintypes.BYTE),
            ("lfOutPrecision", wintypes.BYTE), ("lfClipPrecision", wintypes.BYTE), ("lfQuality", wintypes.BYTE),
            ("lfPitchAndFamily", wintypes.BYTE), ("lfFaceName", wintypes.WCHAR * 32),
        ]

    families: set[str] = set()
    proc_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.POINTER(LOGFONTW), ctypes.c_void_p, wintypes.DWORD, wintypes.LPARAM)

    def callback(logfont, _metric, _font_type, _param):
        name = logfont.contents.lfFaceName
        if name and not name.startswith("@"):
            families.add(name)
        return 1

    gdi32 = ctypes.windll.gdi32
    user32 = ctypes.windll.user32
    hdc = user32.GetDC(None)
    try:
        query = LOGFONTW()
        query.lfCharSet = 1  # DEFAULT_CHARSET: 모든 문자 집합
        gdi32.EnumFontFamiliesExW(hdc, ctypes.byref(query), proc_type(callback), 0, 0)
    finally:
        user32.ReleaseDC(None, hdc)
    return sorted(families)


def _repository_state(root: Path) -> dict[str, Any] | None:
    if not (root / ".git").exists():
        return None

    def git(*args: str) -> str | None:
        try:
            done = subprocess.run(
                ["git", "-C", str(root), *args],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    head = git("rev-parse", "--short", "HEAD")
    if head is None:
        return None
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if not upstream or branch == "HEAD":
        upstream = "origin/main" if git("rev-parse", "--verify", "--quiet", "origin/main") else None
    behind = ahead = None
    if upstream:
        counts = git("rev-list", "--left-right", "--count", f"HEAD...{upstream}")
        if counts:
            left, right = counts.split()
            ahead, behind = int(left), int(right)
    dirty = git("status", "--porcelain", "--untracked-files=no")
    return {
        "branch": branch,
        "head": head,
        "upstream": upstream,
        "behind": behind,
        "ahead": ahead,
        "dirty": bool(dirty),
    }


# --------------------------------------------------------------------------
# Windows 프로세스·창 열거 (ctypes)
# --------------------------------------------------------------------------


def _toolhelp_processes() -> Iterable[ProcessInfo]:
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if snapshot in (None, wintypes.HANDLE(-1).value):
        return []
    entries: list[ProcessInfo] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == HWP_EXE:
                entries.append(ProcessInfo(entry.th32ProcessID, entry.szExeFile, _process_created(entry.th32ProcessID)))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return entries


def _process_created(pid: int) -> float | None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                        ctypes.byref(kernel), ctypes.byref(user)):
            return None
        ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return (ticks - 116444736000000000) / 10_000_000
    finally:
        kernel32.CloseHandle(handle)


def _enum_windows() -> Iterable[WindowInfo]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.GetWindow.restype = wintypes.HWND
    found: list[WindowInfo] = []
    proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _param):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        title = ctypes.create_unicode_buffer(512)
        user32.InternalGetWindowText(hwnd, title, 512)
        owner = user32.GetWindow(hwnd, GW_OWNER) or 0
        found.append(
            WindowInfo(
                hwnd=int(hwnd or 0),
                pid=int(pid.value),
                class_name=cls.value,
                title=title.value,
                visible=bool(user32.IsWindowVisible(hwnd)),
                owner=int(owner),
                hung=bool(user32.IsHungAppWindow(hwnd)),
            )
        )
        return True

    user32.EnumWindows(proc_type(callback), 0)
    return found
