"""--backend auto|hwpx|hancom 선택. 한/글 COM 과는 별개."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from hwpctl.backend import backend_status, normalize_backend, resolve_backend
from hwpctl.errors import UsageError
from hwpctl.parser import parse_args


def test_normalize_and_resolve_auto_is_hwpx_off_windows() -> None:
    assert normalize_backend("AUTO") == "auto"
    assert normalize_backend("hwpx") == "hwpx"
    if sys.platform != "win32":
        assert resolve_backend("auto") == "hwpx"
        assert resolve_backend(None) == "hwpx"
    assert resolve_backend("hancom") == "hancom"
    assert resolve_backend("hwpx") == "hwpx"
    status = backend_status("auto")
    assert status["requested"] == "auto"
    assert status["platform"]
    if sys.platform != "win32":
        assert status["resolved"] == "hwpx"
        assert status["hangul_required"] is False


def test_unknown_backend_korean() -> None:
    with pytest.raises(UsageError) as exc:
        normalize_backend("libreoffice")
    assert "auto" in exc.value.message


def test_parser_backend_flag() -> None:
    ns = parse_args(["--backend", "hwpx", "hwpx_status"])
    assert ns.backend == "hwpx"
    ns = parse_args(["hwpx_status", "--backend", "hancom"])
    assert ns.backend == "hancom"
    ns = parse_args(["hwpx_compare", "a.hwpx", "--orig-dir", "fixtures/gongo"])
    assert ns.command == "hwpx_compare"
    assert ns.orig_dir.endswith("gongo")


def test_cli_hwpx_status_reports_backend() -> None:
    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "hwpctl.cli", "--backend", "auto", "hwpx_status"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["selected_backend"]["requested"] == "auto"
    if sys.platform != "win32":
        assert data["selected_backend"]["resolved"] == "hwpx"
    assert data["hangul_required"] is False
    assert data["lock_required"] is False
