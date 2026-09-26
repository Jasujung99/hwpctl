"""Preflight first; author only in an exclusively created native session."""
from __future__ import annotations

import gc
import hashlib
import ctypes
from pathlib import Path
import shutil
import tempfile
from typing import Any

from hwpctl.authoring.compiler import compile_spec
from hwpctl.authoring.model import load_spec, parse_spec
from hwpctl.engine import Engine
from hwpctl.errors import UsageError, HangulCommandError
from hwpctl.hangul import HangulCanvas
from hwpctl.lock import writer_transaction


class OwnedEngine(Engine):
    """Never consult or modify the global window pin/Undo state."""

    def __init__(self, canvas, *, allowed, lock_timeout=8):
        super().__init__(lock_timeout=lock_timeout)
        self.canvas = canvas
        self.hwnd = canvas.window_handle()
        self.pid = _window_pid(self.hwnd)
        self.document_identity = _document_identity(canvas.com)
        self.allowed = frozenset(allowed)
        self.undo_steps: list[tuple[str, int]] = []
        if not self.hwnd or not self.pid:
            raise HangulCommandError("Cannot establish owned window/process identity")

    def _connect(self, **kwargs):
        app = self.canvas.com
        if (any(kwargs.values()) or self.canvas.window_handle() != self.hwnd or
                _window_pid(self.hwnd) != self.pid or int(app.XHwpDocuments.Count) != 1 or
                _document_identity(app) != self.document_identity or
                str(app.XHwpDocuments.Active_XHwpDocument.FullName or "").strip()):
            raise HangulCommandError("Owned authoring document/window identity changed")
        self.canvas.assert_no_dialog()
        return self.canvas

    def _record_undo(self, command, hangul_steps):
        self.undo_steps.append((command, hangul_steps))

    def dispatch(self, command, **kwargs):
        if command not in self.allowed:
            raise UsageError("Command is outside the compiled authoring plan")
        return super().dispatch(command, **kwargs)


def _dispatch():
    import win32com.client
    return win32com.client.DispatchEx("HWPFrame.HwpObject")


def _hwp_pids() -> set[int]:
    """Read native process identities without attaching to or activating Hwp."""
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
    kernel.Process32FirstW.restype = wintypes.BOOL
    kernel.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
    kernel.Process32NextW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    snapshot = kernel.CreateToolhelp32Snapshot(0x2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    result = set()
    entry = ProcessEntry()
    entry.dwSize = ctypes.sizeof(ProcessEntry)
    try:
        if not kernel.Process32FirstW(snapshot, ctypes.byref(entry)):
            raise ctypes.WinError(ctypes.get_last_error())
        while True:
            if entry.szExeFile.casefold() == "hwp.exe":
                result.add(int(entry.th32ProcessID))
            if not kernel.Process32NextW(snapshot, ctypes.byref(entry)):
                if ctypes.get_last_error() != 18:
                    raise ctypes.WinError(ctypes.get_last_error())
                break
    finally:
        kernel.CloseHandle(snapshot)
    return result


def _window_pid(hwnd: int) -> int:
    if not hwnd:
        return 0
    import win32process
    return int(win32process.GetWindowThreadProcessId(hwnd)[1])


def _document_identity(app):
    """COM IUnknown equality follows canonical object identity rules."""
    import pythoncom
    document = app.XHwpDocuments.Active_XHwpDocument
    return document._oleobj_.QueryInterface(pythoncom.IID_IUnknown)


def _require_owned_document(app, canvas, *, hwnd, pid, identity, staged):
    if (int(app.XHwpDocuments.Count) != 1 or canvas.window_handle() != hwnd or
            _window_pid(hwnd) != pid or _document_identity(app) != identity):
        raise HangulCommandError("Owned document identity changed before cleanup")
    current = str(app.XHwpDocuments.Active_XHwpDocument.FullName or "").strip()
    if current and (staged is None or Path(current).resolve() != staged.resolve()):
        raise HangulCommandError("Owned document path changed before cleanup")


def build_document(spec: str | dict, output: str, dry_run: bool = False, *,
                   lock_timeout: float = 8, _dispatch_factory=None,
                   _canvas_factory=HangulCanvas, _engine_factory=OwnedEngine) -> dict[str, Any]:
    if type(dry_run) is not bool:
        raise UsageError("dry_run must be boolean")
    model = parse_spec(spec, base_dir=Path.cwd()) if isinstance(spec, dict) else load_spec(spec)
    plan = compile_spec(model)
    destination = Path(output).expanduser().resolve()
    if not output or destination.suffix.lower() not in {".hwp", ".hwpx"}:
        raise UsageError("output must be a new .hwp or .hwpx file")
    sources = {(model.base_dir / item["path"]).resolve() for item in model.assets.values()}
    if not isinstance(spec, dict):
        sources.add(Path(spec).expanduser().resolve())
    def reference_files(value):
        if isinstance(value, dict):
            for item in value.values():
                yield from reference_files(item)
        elif isinstance(value, list):
            for item in value:
                yield from reference_files(item)
        elif isinstance(value, str):
            candidate = (model.base_dir / value).resolve()
            if candidate.is_file():
                yield candidate
    sources.update(reference_files(model.reference))
    if destination in sources or destination.exists():
        raise UsageError("Existing outputs, specifications and assets are never overwritten")
    hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    result = {"ok": True, "command": "build_document", "dry_run": dry_run,
              "spec_sha256": model.digest, "output": str(destination),
              "plan": [command.to_dict() for command in plan], "saved": False,
              "completed": False, "cleanup": {"created": False, "closed": False, "quit": False}}
    if dry_run:
        return result
    app = canvas = engine = None
    owned = False
    owner_identity = owner_hwnd = owner_pid = None
    failure = None
    location = "session.create"
    command_name = "create_owned_session"
    stage = None
    staged = None
    with writer_transaction(timeout=lock_timeout):
        try:
            # Recheck after waiting for another writer; never start native work
            # with stale assets or an output that appeared during preflight.
            if destination.exists() or any(hashlib.sha256(p.read_bytes()).hexdigest() != h for p, h in hashes.items()):
                raise UsageError("Authoring inputs/output changed after preflight")
            before_pids = _hwp_pids()
            app = (_dispatch_factory or _dispatch)()
            result["activation_returned"] = True
            if int(app.XHwpDocuments.Count) != 1:
                raise HangulCommandError("Owned session must contain exactly one new document")
            canvas = _canvas_factory(None, app, "owned-authoring")
            if (canvas.doc_info().path or
                    str(app.XHwpDocuments.Active_XHwpDocument.FullName or "").strip() or
                    str(app.GetTextFile("UNICODE", "") or "").strip()):
                raise HangulCommandError("Owned session is not a new blank document")
            hwnd = canvas.window_handle()
            pid = _window_pid(hwnd)
            if not pid or pid in before_pids or pid not in _hwp_pids():
                raise HangulCommandError("New native process and window ownership could not be proven")
            identity = _document_identity(app)
            owned = True
            owner_identity, owner_hwnd, owner_pid = identity, hwnd, pid
            result["cleanup"]["created"] = True
            result["owned_pid"] = pid
            result["owned_hwnd"] = hwnd
            # Some installations return False even when the module is already
            # registered. SaveAs remains the authoritative check.
            app.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
            engine = _engine_factory(canvas, allowed={c.name for c in plan} | {"save_as"}, lock_timeout=lock_timeout)
            for index, command in enumerate(plan):
                location, command_name = command.location, command.name
                reply = engine.dispatch(command.name, **command.arguments)
                if reply.get("ok") is not True:
                    raise HangulCommandError(f"Command reported failure: {command.name}")
                if reply.get("warnings"):
                    result.setdefault("warnings", []).extend(str(w) for w in reply["warnings"])
                result["executed_commands"] = index + 1
            location, command_name = "output", "save_as"
            destination.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix="hwpctl-build-", dir=destination.parent))
            staged = stage / ("document" + destination.suffix.lower())
            result["staged_output"] = str(staged)
            engine.dispatch("save_as", path=str(staged), format=destination.suffix[1:].upper(), overwrite=False)
            if not staged.is_file() or not staged.stat().st_size:
                raise HangulCommandError("Native save produced no content")
            result["saved"] = True
        except Exception as exc:
            # Store text only: retaining tracebacks retains COM proxies and can
            # cause native RPC diagnostics during the next isolated session.
            failure = {"location": location, "command": command_name,
                       "error_type": type(exc).__name__, "message": str(exc)}
        finally:
            engine = None
            gc.collect()
            if app is not None and owned:
                try:
                    _require_owned_document(app, canvas, hwnd=owner_hwnd, pid=owner_pid,
                                            identity=owner_identity, staged=staged)
                    returned = app.XHwpDocuments.Close(False)
                    if returned is False:
                        raise HangulCommandError("Owned document close returned false")
                    result["cleanup"]["closed"] = True
                    if int(app.XHwpDocuments.Count) != 0:
                        raise HangulCommandError("New document appeared after owned close; quit skipped")
                    returned = app.Quit()
                    if returned is False:
                        raise HangulCommandError("Owned session quit returned false")
                    result["cleanup"]["quit"] = True
                except Exception as exc:
                    result["cleanup"]["error"] = str(exc)
                    failure = failure or {"location": "session.cleanup", "command": "close_owned_session", "message": str(exc)}
                    if not result["cleanup"]["closed"]:
                        result["cleanup"]["skipped_changed_owner"] = True
                app = None
                canvas = None
                gc.collect()
            elif app is not None:
                # A returned COM object may be an existing user instance. Drop
                # our proxy only; never close, quit, or discard its documents.
                result["cleanup"]["skipped_unverified_owner"] = True
                app = None
                canvas = None
                gc.collect()
        try:
            if any(hashlib.sha256(p.read_bytes()).hexdigest() != h for p, h in hashes.items()):
                raise HangulCommandError("Authoring source changed during execution")
            if failure is None:
                location, command_name = "output.publish", "exclusive_publish"
                with staged.open("rb") as source, destination.open("xb") as target:
                    shutil.copyfileobj(source, target)
                result["output_sha256"] = hashlib.sha256(destination.read_bytes()).hexdigest()
                result["completed"] = True
        except Exception as exc:
            failure = failure or {"location": location, "command": command_name, "message": str(exc)}
        if failure is not None:
            result.update(ok=False, failure=failure, artifact_status="incomplete" if stage else "not_saved")
        else:
            # Only our fresh staging directory, never an input or user directory.
            try:
                shutil.rmtree(stage)
            except OSError as exc:
                result["staging_cleanup_error"] = str(exc)
            result.pop("staged_output", None)
            result["artifact_status"] = "complete"
    return result
