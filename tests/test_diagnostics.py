from __future__ import annotations

import os
import subprocess
import sys
import time

from hwpctl import diagnostics
from hwpctl.diagnostics import FontFace, ProcessInfo, SystemProbe, WindowInfo, run_doctor


class FakeProbe(SystemProbe):
    def __init__(
        self,
        *,
        windows_os: bool = True,
        processes: list[ProcessInfo] | None = None,
        windows: list[WindowInfo] | None = None,
        fonts: dict[str, FontFace] | None = None,
        repo: dict | None = None,
        documents: list[dict] | None = None,
    ) -> None:
        self._windows_os = windows_os
        self._processes = processes or []
        self._windows = windows or []
        self._fonts = fonts or {}
        self._repo = repo
        self._documents = documents
        self.document_calls = 0

    def is_windows(self) -> bool:
        return self._windows_os

    def processes(self):
        return self._processes

    def windows(self):
        return self._windows

    def fonts(self):
        return self._fonts

    def repository(self):
        return self._repo

    def documents(self):
        self.document_calls += 1
        return self._documents


def _main_window(hwnd: int = 100, pid: int = 1, *, hung: bool = False) -> WindowInfo:
    return WindowInfo(hwnd=hwnd, pid=pid, class_name="HwpApp", title="문서 - 한글", visible=True, owner=0, hung=hung)


def _dialog(pid: int = 1, title: str = "한글") -> WindowInfo:
    return WindowInfo(hwnd=900, pid=pid, class_name="#32770", title=title, visible=True, owner=100, hung=False)


def _by_name(result: dict, name: str) -> list[dict]:
    return [check for check in result["checks"] if check["name"] == name]


def test_doctor_healthy_environment_lists_documents() -> None:
    probe = FakeProbe(
        processes=[ProcessInfo(1, "Hwp.exe", 1000.0)],
        windows=[_main_window()],
        documents=[{"window_handle": 100, "path": "D:/a.hwpx", "modified": False, "active": True}],
        repo={"branch": "main", "head": "abc", "upstream": "origin/main", "behind": 0, "ahead": 0, "dirty": False},
    )
    result = run_doctor(target_hwnd=100, probe=probe)
    assert result["ok"] is True and result["errors"] == 0
    assert _by_name(result, "pin")[0]["status"] == "ok"
    assert _by_name(result, "documents")[0]["documents"][0]["path"] == "D:/a.hwpx"


def test_doctor_hung_window_and_dialog_block_com_queries() -> None:
    probe = FakeProbe(
        processes=[ProcessInfo(1, "Hwp.exe", 1000.0)],
        windows=[_main_window(hung=True), _dialog(title="자동 저장 복구")],
    )
    result = run_doctor(probe=probe)
    assert result["ok"] is False
    assert _by_name(result, "responding")[0]["status"] == "error"
    assert _by_name(result, "dialogs")[0]["dialogs"][0]["title"] == "자동 저장 복구"
    assert _by_name(result, "documents")[0]["status"] == "skip"
    # 응답 없는 한/글에 COM 조회를 보내면 점검 자체가 멈출 수 있다.
    assert probe.document_calls == 0


def test_doctor_reports_windowless_processes_and_stale_pin() -> None:
    probe = FakeProbe(
        processes=[ProcessInfo(1, "Hwp.exe", 1000.0), ProcessInfo(2, "Hwp.exe", 500.0)],
        windows=[_main_window(hwnd=100, pid=1)],
        documents=[],
    )
    result = run_doctor(target_hwnd=4242, probe=probe)
    assert _by_name(result, "windowless_hangul")[0]["pids"] == [2]
    pin = _by_name(result, "pin")[0]
    assert pin["status"] == "warn" and pin["target_hwnd"] == 4242


def test_doctor_font_missing_or_installed_after_hangul_started() -> None:
    probe = FakeProbe(
        processes=[ProcessInfo(1, "Hwp.exe", 1000.0)],
        windows=[_main_window()],
        fonts={
            "맑은고딕": FontFace("맑은 고딕", "C:/Windows/Fonts/malgun.ttf", 10.0),
            "학교안심알림장otfb": FontFace("학교안심 알림장 OTF B", "x.otf", 2000.0),
        },
        documents=[],
    )
    result = run_doctor(fonts=["맑은 고딕", "학교안심 알림장 OTF B", "학교안심 우주 R"], probe=probe)
    fonts = {check["font"]: check for check in _by_name(result, "font")}
    assert fonts["맑은 고딕"]["status"] == "ok"
    assert fonts["학교안심 알림장 OTF B"]["restart_required"] is True
    assert fonts["학교안심 우주 R"]["installed"] is False
    assert result["errors"] == 2


def test_doctor_warns_when_running_code_is_behind_upstream() -> None:
    probe = FakeProbe(
        repo={"branch": "feature", "head": "abc", "upstream": "origin/main", "behind": 11, "ahead": 1, "dirty": True}
    )
    result = run_doctor(probe=probe)
    repo = _by_name(result, "repository")[0]
    assert repo["status"] == "warn" and repo["behind"] == 11
    assert "11커밋" in repo["message"]


def test_doctor_non_windows_is_an_error() -> None:
    result = run_doctor(probe=FakeProbe(windows_os=False))
    assert result["ok"] is False
    assert result["checks"][0]["name"] == "platform"


class _RecordingPopen:
    calls: list[tuple[list[str], dict]] = []

    def __init__(self, args, **kwargs) -> None:
        type(self).calls.append((list(args), kwargs))
        self.args = list(args)
        self.returncode = 0

    def communicate(self, timeout=None):
        command = self.args[3]
        if command == "rev-list":
            return "0\t0\n", None
        if command == "status":
            return "", None
        return "main\n", None


def test_repository_probe_detaches_git_from_server_stdio(tmp_path, monkeypatch) -> None:
    # MCP stdio 서버의 stdin 을 물려받은 Git for Windows 는 요청 파이프를 붙잡고 멈춘다.
    (tmp_path / ".git").mkdir()
    _RecordingPopen.calls = []
    monkeypatch.setattr(diagnostics.subprocess, "Popen", _RecordingPopen)

    repo = diagnostics._repository_state(tmp_path)

    assert repo is not None and repo["head"] == "main"
    assert _RecordingPopen.calls
    for args, kwargs in _RecordingPopen.calls:
        assert args[:3] == ["git", "-C", str(tmp_path)]
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["stderr"] is subprocess.DEVNULL
        if os.name == "nt":
            assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW


def test_quiet_child_reads_eof_instead_of_parent_stdin() -> None:
    script = "import sys; sys.stdout.write(repr(sys.stdin.read()))"
    assert diagnostics._run_quiet([sys.executable, "-c", script], timeout=30) == "''"


def test_quiet_child_timeout_returns_even_if_pipe_stays_open(monkeypatch) -> None:
    # Windows 에서는 kill 뒤에도 손자 프로세스가 stdout 파이프를 잡고 있으면
    # subprocess.run 이 끝없이 기다린다. 두 번째 대기도 짧게 끊어야 한다.
    events: list[tuple[str, object]] = []

    class StuckPopen:
        def __init__(self, args, **kwargs) -> None:
            self.returncode = None

        def communicate(self, timeout=None):
            events.append(("communicate", timeout))
            raise subprocess.TimeoutExpired("git", timeout)

        def kill(self) -> None:
            events.append(("kill", None))

    monkeypatch.setattr(diagnostics.subprocess, "Popen", StuckPopen)

    assert diagnostics._run_quiet(["git", "status"], timeout=5) is None
    assert events == [("communicate", 5), ("kill", None), ("communicate", 1)]


def test_quiet_child_timeout_is_bounded_for_a_real_process() -> None:
    started = time.monotonic()
    result = diagnostics._run_quiet([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)
    assert result is None
    assert time.monotonic() - started < 10
