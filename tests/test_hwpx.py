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

REPO = Path(__file__).resolve().parents[1]

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


def test_hwpx_tools_are_catalogued() -> None:
    names = tool_names()
    assert "hwpx_status" in names
    assert "hwpx_inspect" in names
    assert "hwpx_compare" in names


def test_hwpx_parser() -> None:
    status = parse_args(["hwpx_status"])
    assert status.command == "hwpx_status"
    assert status.path is None
    inspect = parse_args(["hwpx_inspect", "sample.hwpx"])
    assert inspect.command == "hwpx_inspect"
    assert inspect.path.endswith("sample.hwpx")
    compare = parse_args(["hwpx_compare", "sample.hwpx", "--out-dir", "out"])
    assert compare.command == "hwpx_compare"
    assert compare.output_dir == "out"


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
    assert run["underline"] is False
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


def test_compare_page_images_missing_file_korean() -> None:
    with pytest.raises(HwpxError) as exc:
        compare_page_images("/tmp/hwpctl-no-such-compare-356c.hwpx")
    assert "찾을 수 없습니다" in exc.value.message


def test_cli_hwpx_status_without_hangul() -> None:
    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "hwpctl.cli", "hwpx_status"],
        cwd=repo,
        capture_output=True,
        text=True,
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


@pytest.mark.skipif(not hwpx_available(), reason="python-hwpx extra 필요")
def test_write_partial_runs_underline_cream_table(tmp_path: Path) -> None:
    from hwpctl.hwpx.document import close_document, new_document, save_document
    from hwpctl.hwpx.write import (
        CREAM_FILL,
        apply_paragraph_format,
        cream_section_header,
        create_table_and_fill,
        insert_runs,
        set_page_setup,
    )

    doc = new_document()
    try:
        set_page_setup(doc)
        insert_runs(
            doc,
            [
                {"text": "기간은 ", "font": "함초롬바탕", "size": 11},
                {
                    "text": "7. 3(금) 16시까지",
                    "font": "함초롬돋움",
                    "size": 11,
                    "bold": True,
                    "underline": True,
                    "underline_color": "#FF0000",
                    "color": "#FF0000",
                },
                {"text": " 이며 URL 은 ", "font": "함초롬바탕", "size": 11},
                {
                    "text": "www.sbiz24.kr",
                    "font": "함초롬돋움",
                    "size": 11,
                    "underline": True,
                    "underline_color": "#0000FF",
                    "color": "#0000FF",
                },
            ],
            align="JUSTIFY",
            line_spacing_percent=160,
        )
        apply_paragraph_format(doc, alignment="JUSTIFY")
        cream_section_header(doc, "2", "지원대상")
        create_table_and_fill(
            doc,
            2,
            2,
            [["단계", "내용"], ["STEP 1", "구축"]],
            header_fill="#C5D8EA",
            col_widths=[1, 2],
        )
        out = tmp_path / "styled.hwpx"
        save_document(doc, out)
    finally:
        close_document(doc)

    inspected = inspect_hwpx(out)
    assert any(g.get("underline") and g.get("color") == "#FF0000" for g in inspected["run_groups"])
    assert any(g.get("underline") and g.get("color") == "#0000FF" for g in inspected["run_groups"])
    assert any(g.get("fill") == CREAM_FILL for g in inspected["cell_fill_groups"])
    assert inspected["table_count"] >= 2

    compared = compare_page_images(out, output_dir=tmp_path / "cmp")
    assert compared["ok"] is True
    assert compared["hangul_required"] is False
    assert Path(compared["inspect"]).is_file()
    assert any(item["id"] == "red_underline" and item["ok"] for item in compared["checklist"])


@pytest.mark.skipif(not hwpx_available(), reason="python-hwpx extra 필요")
def test_recreate_gongo_pages_1_3(tmp_path: Path) -> None:
    from hwpctl.hwpx.gongo import recreate_gongo

    fixtures = REPO / "fixtures" / "gongo"
    if not (fixtures / "gongo_pages.json").is_file():
        pytest.skip("gongo fixtures 없음")
    out = tmp_path / "rebuild.hwpx"
    built = recreate_gongo(output=out, fixtures=fixtures, pages=(1, 2, 3))
    assert built["ok"] is True
    assert out.is_file()
    inspected = inspect_hwpx(out)
    blob = json.dumps(inspected, ensure_ascii=False)
    assert "간단소개" in blob
    assert "7. 3(금) 16시까지" in blob
    assert "www.sbiz24.kr" in blob
    assert "신청제외" in blob
    assert any(g.get("underline") and g.get("color") == "#FF0000" for g in inspected["run_groups"])
    assert any(g.get("fill") == "#F5E6C8" for g in inspected["cell_fill_groups"])
    compared = compare_page_images(
        out,
        orig_dir=fixtures,
        output_dir=tmp_path / "cmp",
        pages=(1, 2, 3),
    )
    assert compared["ok"] is True
    assert compared["checklist"]
    assert (tmp_path / "cmp" / "report.json").is_file()
