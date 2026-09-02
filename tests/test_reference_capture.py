"""COM 없이 읽기 전용 HWPML 캡처의 안전 계약을 검증한다."""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpctl.reference.capture import capture_hwpml_readonly


class _Documents:
    def __init__(self, events: list[object]) -> None:
        self.events = events

    def Close(self, save: bool) -> None:  # noqa: N802 - COM method name
        self.events.append(("close", save))


class _App:
    PageCount = 7

    def __init__(self, events: list[object], *, mutate: Path | None = None) -> None:
        self.events = events
        self.mutate = mutate
        self.XHwpDocuments = _Documents(events)

    def RegisterModule(self, name: str, checker: str) -> None:  # noqa: N802 - COM method name
        self.events.append(("register", name, checker))

    def Open(self, path: str, format_name: str, options: str) -> bool:  # noqa: N802 - COM method name
        self.events.append(("open", path, format_name, options))
        return True

    def GetTextFile(self, kind: str, options: str) -> str:  # noqa: N802 - COM method name
        self.events.append(("get_text", kind, options))
        if self.mutate is not None:
            self.mutate.write_bytes(b"changed")
        return "<HWPML/>"

    def Quit(self) -> None:  # noqa: N802 - COM method name
        self.events.append("quit")


def test_capture_uses_a_readonly_separate_app_and_returns_path_free_evidence(tmp_path: Path) -> None:
    source = tmp_path / "reference.hwp"
    source.write_bytes(b"reference")
    events: list[object] = []

    capture = capture_hwpml_readonly(source, _dispatch=lambda prog_id: _App(events))

    assert capture.hwpml == "<HWPML/>"
    assert capture.com_page_count == 7
    assert capture.source_unchanged is True
    assert ("open", str(source.resolve()), "HWP", "readonly:true") in events
    assert ("close", False) in events
    assert events[-1] == "quit"
    manifest = capture.manifest_entry("test-reference")
    assert str(source) not in repr(manifest)
    assert manifest["source_unchanged"] is True


def test_capture_stops_when_the_source_hash_changes(tmp_path: Path) -> None:
    source = tmp_path / "reference.hwp"
    source.write_bytes(b"reference")
    events: list[object] = []

    with pytest.raises(RuntimeError, match="SHA-256"):
        capture_hwpml_readonly(source, _dispatch=lambda prog_id: _App(events, mutate=source))

    assert ("close", False) in events
    assert events[-1] == "quit"
