from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from hwpctl.errors import HangulMissingError
from hwpctl.hangul import MISSING_KO, HangulCanvas, require_windows


def test_require_windows_korean_on_linux() -> None:
    if sys.platform == "win32":
        return
    try:
        require_windows()
    except HangulMissingError as exc:
        assert "한/글" in exc.message
        assert "Windows" in exc.message
        return
    raise AssertionError("Linux 에서는 HangulMissingError 가 나야 합니다.")


def test_connect_fails_korean_off_windows() -> None:
    if sys.platform == "win32":
        return
    try:
        HangulCanvas.connect()
    except HangulMissingError as exc:
        assert exc.message == MISSING_KO
        return
    raise AssertionError("expected HangulMissingError")


def test_cli_status_no_stack_dump() -> None:
    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "hwpctl.cli", "status"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if sys.platform == "win32":
        return
    assert proc.returncode == 2
    assert "한/글" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert "Traceback" not in proc.stdout


def test_cli_save_without_overwrite_korean() -> None:
    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "hwpctl.cli", "save"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 4
    assert "--overwrite" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_cli_mcp_list_tools_without_hangul() -> None:
    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "hwpctl.cli", "mcp", "--list-tools"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    names = {t["name"] for t in data["tools"]}
    assert "status" in names
    assert "create_table" in names
    assert "save_as" in names