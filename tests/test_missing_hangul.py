from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from hwpctl import cli
from hwpctl.errors import HangulMissingError
from hwpctl.hangul import MISSING_KO, HangulCanvas, require_windows


@pytest.mark.skipif(sys.platform == "win32", reason="Linux/비-Windows 오류 계약 전용")
def test_require_windows_korean_on_linux() -> None:
    try:
        require_windows()
    except HangulMissingError as exc:
        assert "한/글" in exc.message
        assert "Windows" in exc.message
        return
    raise AssertionError("Linux 에서는 HangulMissingError 가 나야 합니다.")


@pytest.mark.skipif(sys.platform == "win32", reason="Linux/비-Windows 오류 계약 전용")
def test_connect_fails_korean_off_windows() -> None:
    try:
        HangulCanvas.connect()
    except HangulMissingError as exc:
        assert exc.message == MISSING_KO
        return
    raise AssertionError("expected HangulMissingError")


@pytest.mark.skipif(sys.platform == "win32", reason="Linux/비-Windows 오류 계약 전용")
def test_cli_status_no_stack_dump() -> None:
    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "hwpctl.cli", "status"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 3  # argparse 사용 오류(2)와 구분되는 코드 (#15)
    assert "한/글" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert "Traceback" not in proc.stdout


def test_cli_missing_hangul_uses_exit_code_3_on_every_platform(monkeypatch, capsys) -> None:
    """OS와 무관하게 도메인 오류는 argparse 오류(2)가 아닌 exit 3이어야 한다."""

    def fail_engine(_args):
        raise HangulMissingError("한/글 연결을 찾지 못했습니다.")

    monkeypatch.setattr(cli, "_run_engine", fail_engine)

    assert cli.main(["status"]) == 3
    captured = capsys.readouterr()
    assert "한/글" in captured.err
    assert "Traceback" not in captured.err


def test_cli_save_without_overwrite_korean() -> None:
    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "hwpctl.cli", "save"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 5
    assert "--overwrite" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_cli_mcp_list_tools_without_hangul() -> None:
    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "hwpctl.cli", "mcp", "--list-tools"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    names = {t["name"] for t in data["tools"]}
    assert "status" in names
    assert "list_documents" in names
    assert "create_table" in names
    assert "save_as" in names
    assert "hwpx_status" in names
    assert "hwpx_inspect" in names


def test_cli_reconfigures_json_pipe_to_utf8_for_unsupported_char(
    monkeypatch,
) -> None:
    """CP949 기본 파이프여도 JSON wire encoding은 항상 UTF-8이어야 한다."""
    output_bytes = io.BytesIO()
    error_bytes = io.BytesIO()
    stdout = io.TextIOWrapper(output_bytes, encoding="cp949")
    stderr = io.TextIOWrapper(error_bytes, encoding="cp949")
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    monkeypatch.setattr(cli.sys, "stderr", stderr)
    monkeypatch.setattr(cli, "_run_hwpx", lambda _args: {"preview": "◦ 한글"})

    assert cli.main(["hwpx_status"]) == 0
    stdout.flush()
    stderr.flush()
    payload = json.loads(output_bytes.getvalue().decode("utf-8"))
    assert payload["preview"] == "◦ 한글"
