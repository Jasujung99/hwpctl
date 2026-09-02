"""한글·COM 없이 동작하는 HWPX 준비 계층 테스트."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from hwpctl.errors import HwpxError, HwpxMissingError, UsageError
from hwpctl.hwpx.commands import dispatch_hwpx, hwpx_status
from hwpctl.hwpx.compare import compare_page_images
from hwpctl.hwpx.document import MISSING_KO, hwpx_available, hwpx_version, require_hwpx
from hwpctl.hwpx.inspect import inspect_hwpx, inspect_owpml_parts
from hwpctl.parser import parse_args
from hwpctl.tools import tool_names

HEADER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head"
         xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core">
  <hh:refList>
    <hh:fontfaces itemCnt="1">
      <hh:fontface lang="HANGUL" fontCnt="1">
        <hh:font id="0" face="함초롬돋움" type="TTF" isEmbedded="0"/>
      </hh:fontface>
    </hh:fontfaces>
    <hh:borderFills itemCnt="1">
      <hh:borderFill id="4">
        <hc:fillBrush>
          <hc:winBrush faceColor="#D9D9D9" hatchColor="#000000" alpha="0"/>
        </hc:fillBrush>
      </hh:borderFill>
    </hh:borderFills>
    <hh:charProperties itemCnt="1">
      <hh:charPr id="7" height="2000" textColor="#333333">
        <hh:fontRef hangul="0" latin="0"/>
        <hh:bold/>
      </hh:charPr>
    </hh:charProperties>
    <hh:paraProperties itemCnt="1">
      <hh:paraPr id="3">
        <hh:align horizontal="CENTER" vertical="CENTER"/>
      </hh:paraPr>
    </hh:paraProperties>
  </hh:refList>
</hh:head>
"""

SECTION_XML = """<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"
        xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
  <hp:p id="1" paraPrIDRef="3" styleIDRef="2">
    <hp:run charPrIDRef="7"><hp:t>공고 제목</hp:t></hp:run>
  </hp:p>
  <hp:p id="2" paraPrIDRef="3" styleIDRef="2">
    <hp:run charPrIDRef="7">
      <hp:tbl>
        <hp:tr>
          <hp:tc borderFillIDRef="4">
            <hp:subList>
              <hp:p paraPrIDRef="3" styleIDRef="0">
                <hp:run charPrIDRef="7"><hp:t>항목</hp:t></hp:run>
              </hp:p>
            </hp:subList>
          </hp:tc>
        </hp:tr>
      </hp:tbl>
    </hp:run>
  </hp:p>
</hs:sec>
"""


def _write_ppm(path: Path, width: int, height: int, rgb: list[int]) -> None:
    assert len(rgb) == width * height * 3
    path.write_bytes(
        f"P6\n{width} {height}\n255\n".encode("ascii") + bytes(rgb)
    )


def test_hwpx_tools_are_catalogued() -> None:
    names = tool_names()
    assert "hwpx_status" in names
    assert "hwpx_inspect" in names


def test_hwpx_parser() -> None:
    status = parse_args(["hwpx_status"])
    assert status.command == "hwpx_status"
    assert status.path is None
    inspect = parse_args(["hwpx_inspect", "sample.hwpx"])
    assert inspect.command == "hwpx_inspect"
    assert inspect.path.endswith("sample.hwpx")


def test_inspect_owpml_groups_from_mock_xml() -> None:
    groups = inspect_owpml_parts(HEADER_XML, [SECTION_XML])
    assert groups["paragraph_count"] == 3
    assert groups["table_count"] == 1

    para = groups["paragraph_groups"][0]
    assert para["para_pr_id"] == "3"
    assert para["align"] == "CENTER"
    assert para["count"] >= 2
    assert "공고" in para["sample_text"]

    run = groups["run_groups"][0]
    assert run["char_pr_id"] == "7"
    assert run["font"] == "함초롬돋움"
    assert run["size_pt"] == 20.0
    assert run["bold"] is True
    assert run["color"] == "#333333"

    cell = groups["cell_fill_groups"][0]
    assert cell["border_fill_id"] == "4"
    assert cell["fill"] == "#D9D9D9"


def test_hwpx_status_without_file() -> None:
    payload = hwpx_status()
    assert payload["ok"] is True
    assert payload["hangul_required"] is False
    assert payload["lock_required"] is False
    assert payload["autosave"] is False
    assert "python_hwpx" in payload
    assert payload["python_hwpx"]["extra"] == "hwpx"


def test_inspect_missing_file_korean() -> None:
    with pytest.raises(HwpxError) as exc:
        inspect_hwpx("/tmp/hwpctl-no-such-file-356c.hwpx")
    assert "찾을 수 없습니다" in exc.value.message


def test_inspect_hwp_rejected_korean(tmp_path: Path) -> None:
    binary = tmp_path / "legacy.hwp"
    binary.write_bytes(b"not-a-zip")
    with pytest.raises(HwpxError) as exc:
        inspect_hwpx(binary)
    assert ".hwp" in exc.value.message
    assert ".hwpx" in exc.value.message


def test_compare_page_images_explicit_list_metrics_and_artifacts(tmp_path: Path) -> None:
    reference_first = tmp_path / "reference-1.ppm"
    reference_second = tmp_path / "reference-2.ppm"
    candidate_first = tmp_path / "candidate-1.ppm"
    candidate_second = tmp_path / "candidate-2.ppm"
    _write_ppm(reference_first, 2, 1, [0, 0, 0, 20, 40, 60])
    _write_ppm(reference_second, 1, 1, [1, 2, 3])
    _write_ppm(candidate_first, 2, 1, [0, 0, 0, 25, 50, 65])
    _write_ppm(candidate_second, 1, 1, [1, 2, 3])

    payload = compare_page_images(
        [reference_first, reference_second],
        [candidate_first, candidate_second],
        output_dir=tmp_path / "artifacts",
        emit_diff=True,
        emit_overlay=True,
    )

    assert payload["ok"] is False
    assert payload["page_count_match"] is True
    assert payload["dimensions_match"] is True
    assert payload["comparable_page_count"] == 2
    assert payload["changed_pixels"] == 1
    assert payload["mean_absolute_error"] == pytest.approx(20 / 9)
    assert payload["max_delta"] == 10

    first = payload["pages"][0]
    assert first["status"] == "different"
    assert first["changed_pixels"] == 1
    assert first["mean_absolute_error"] == pytest.approx(20 / 6)
    assert first["max_delta"] == 10
    assert Path(first["diff_path"]).read_bytes().endswith(bytes([0, 0, 0, 5, 10, 5]))
    assert Path(first["overlay_path"]).read_bytes().endswith(bytes([0, 0, 0, 22, 45, 62]))
    assert payload["pages"][1]["status"] == "identical"


def test_compare_page_images_directories_report_count_and_dimension_mismatches(
    tmp_path: Path,
) -> None:
    reference_dir = tmp_path / "reference"
    candidate_dir = tmp_path / "candidate"
    reference_dir.mkdir()
    candidate_dir.mkdir()
    _write_ppm(reference_dir / "page-2.ppm", 1, 1, [1, 2, 3])
    _write_ppm(reference_dir / "page-10.ppm", 2, 1, [4, 5, 6, 7, 8, 9])
    _write_ppm(candidate_dir / "page-2.ppm", 1, 1, [1, 2, 3])
    _write_ppm(candidate_dir / "page-10.ppm", 1, 1, [4, 5, 6])
    _write_ppm(candidate_dir / "page-11.ppm", 1, 1, [9, 9, 9])

    payload = compare_page_images(reference_dir, candidate_dir)

    assert payload["ok"] is False
    assert payload["reference_page_count"] == 2
    assert payload["candidate_page_count"] == 3
    assert payload["page_count_match"] is False
    assert payload["dimensions_match"] is False
    assert payload["dimension_mismatch_pages"] == [2]
    assert payload["pages"][0]["reference_path"].endswith("page-2.ppm")
    assert payload["pages"][0]["status"] == "identical"
    assert payload["pages"][1]["status"] == "dimension_mismatch"
    assert payload["pages"][2]["status"] == "missing_reference"


def test_compare_page_images_requires_output_directory_for_artifacts(tmp_path: Path) -> None:
    reference = tmp_path / "reference.ppm"
    candidate = tmp_path / "candidate.ppm"
    _write_ppm(reference, 1, 1, [0, 0, 0])
    _write_ppm(candidate, 1, 1, [0, 0, 0])

    with pytest.raises(ValueError, match="output_dir"):
        compare_page_images(reference, candidate, emit_diff=True)


def test_cli_hwpx_status_without_hangul() -> None:
    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "hwpctl.cli", "hwpx_status"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0
    assert "Traceback" not in proc.stderr
    data = json.loads(proc.stdout)
    assert data["command"] == "hwpx_status"
    assert data["hangul_required"] is False
    assert data["lock_required"] is False


def test_cli_hwpx_inspect_missing_korean() -> None:
    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "hwpctl.cli", "hwpx_inspect", "missing.hwpx"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 9
    assert "찾을 수 없습니다" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_hwpx_commands_do_not_take_writer_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args, **_kwargs):  # noqa: ANN001
        raise AssertionError("SingleWriterLock 은 HWPX 읽기에 쓰면 안 됩니다.")

    monkeypatch.setattr("hwpctl.lock.SingleWriterLock", boom)
    payload = dispatch_hwpx("hwpx_status")
    assert payload["ok"] is True


def test_dispatch_unknown_hwpx_command() -> None:
    with pytest.raises(UsageError):
        dispatch_hwpx("hwpx_rewrite")


@pytest.mark.skipif(not hwpx_available(), reason="python-hwpx extra 필요")
def test_generate_and_inspect_tiny_hwpx(tmp_path: Path) -> None:
    from hwpctl.hwpx.document import close_document, new_document, save_document
    from hwpctl.hwpx.write import create_table_and_fill, insert_paragraph, set_run_props

    doc = new_document()
    try:
        insert_paragraph(doc, "준비 단계 제목", inherit_style=False)
        set_run_props(doc, bold=True, size=16, color="#222222", font="함초롬돋움")
        create_table_and_fill(
            doc,
            2,
            2,
            [["항목", "값"], ["A", "1"]],
            header_fill="#D9D9D9",
        )
        out = tmp_path / "tiny-fixture.hwpx"
        save_document(doc, out)
    finally:
        close_document(doc)

    inspected = inspect_hwpx(out)
    assert inspected["ok"] is True
    assert inspected["hangul_required"] is False
    assert inspected["table_count"] >= 1
    assert inspected["paragraph_count"] >= 1
    assert any(group.get("bold") for group in inspected["run_groups"])
    assert any(group.get("fill") == "#D9D9D9" for group in inspected["cell_fill_groups"])
    assert hwpx_version() is not None

    status = hwpx_status(str(out))
    assert status["path"].endswith("tiny-fixture.hwpx")
    assert status["table_count"] >= 1


@pytest.mark.skipif(not hwpx_available(), reason="python-hwpx extra 필요")
def test_cli_hwpx_inspect_generated_file(tmp_path: Path) -> None:
    from hwpctl.hwpx.document import close_document, new_document, save_document
    from hwpctl.hwpx.write import insert_paragraph

    doc = new_document()
    try:
        insert_paragraph(doc, "CLI 검사")
        out = tmp_path / "cli.hwpx"
        save_document(doc, out)
    finally:
        close_document(doc)

    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "hwpctl.cli", "hwpx_inspect", str(out)],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["command"] == "hwpx_inspect"
    assert data["lock_required"] is False
    assert "CLI 검사" in json.dumps(data, ensure_ascii=False)


def test_require_hwpx_message_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hwpctl.hwpx.document.hwpx_available", lambda: False)
    with pytest.raises(HwpxMissingError) as exc:
        require_hwpx()
    assert "python-hwpx" in exc.value.message
    assert MISSING_KO == exc.value.message
