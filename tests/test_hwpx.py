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


def test_compare_page_images_is_stub() -> None:
    with pytest.raises(NotImplementedError) as exc:
        compare_page_images("a.hwpx", "b.hwpx")
    assert "쪽 이미지" in str(exc.value)


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
def test_writer_round_trip_keeps_rich_run_paragraph_and_table_styles(tmp_path: Path) -> None:
    from hwpctl.hwpx.document import (
        close_document,
        new_document,
        open_document,
        save_document,
    )
    from hwpctl.hwpx.write import (
        append_run,
        apply_paragraph_format,
        create_table_and_fill,
        insert_paragraph,
        set_run_props,
    )

    doc = new_document()
    try:
        paragraph = insert_paragraph(doc, "일반 본문", inherit_style=False)
        set_run_props(
            doc,
            paragraph=paragraph,
            font="휴먼명조",
            size=11.5,
            color="#202020",
        )
        append_run(
            doc,
            " 마감 시각",
            paragraph=paragraph,
            font="휴먼명조",
            size=11.5,
            color="#FF0000",
            underline=True,
            underline_shape="SOLID",
            underline_color="#FF0000",
        )
        base = insert_paragraph(doc, "원본 서식", inherit_style=False)
        base_style = set_run_props(
            doc,
            paragraph=base,
            font="휴먼명조",
            size=11.5,
            bold=True,
            underline=True,
        )
        inherited = insert_paragraph(doc, "상속 런", inherit_style=False)
        set_run_props(
            doc,
            paragraph=inherited,
            base_char_pr_id=base_style["char_pr_id"],
            color="#002060",
        )
        apply_paragraph_format(
            doc,
            paragraph=paragraph,
            alignment="JUSTIFY",
            line_spacing_percent=160,
        )
        create_table_and_fill(
            doc,
            2,
            2,
            [["항목", "값"], ["A", "1"]],
            header_fill="#FCF5E7",
            width_mm=168,
            height_mm=20,
            column_widths_mm=(136, 32),
            border_color="#777777",
            border_width="0.12 mm",
        )
        out = tmp_path / "rich-round-trip.hwpx"
        save_document(doc, out)
    finally:
        close_document(doc)

    round_tripped = tmp_path / "rich-round-tripped.hwpx"
    reopened = open_document(out)
    try:
        save_document(reopened, round_tripped)
    finally:
        close_document(reopened)

    inspected = inspect_hwpx(round_tripped)
    assert "휴먼명조" in inspected["definitions"]["fonts"].values()
    body_group = next(
        group
        for group in inspected["paragraph_groups"]
        if "일반 본문" in group["sample_text"]
    )
    assert body_group["align"] == "JUSTIFY"
    assert body_group["line_spacing_percent"] == 160

    deadline_group = next(
        group for group in inspected["run_groups"] if "마감 시각" in group["sample_text"]
    )
    assert deadline_group["font"] == "휴먼명조"
    assert deadline_group["size_pt"] == 11.5
    assert deadline_group["color"] == "#FF0000"
    assert deadline_group["underline"] is True
    assert deadline_group["underline_color"] == "#FF0000"
    inherited_run = next(
        run for run in inspected["runs"] if run["text"] == "상속 런"
    )
    assert inherited_run["font"] == "휴먼명조"
    assert inherited_run["size_pt"] == 11.5
    assert inherited_run["bold"] is True
    assert inherited_run["color"] == "#002060"
    assert inherited_run["underline"] is True

    cream_cells = next(
        group
        for group in inspected["cell_fill_groups"]
        if group["fill"] == "#FCF5E7"
    )
    assert cream_cells["borders"]["left"] == {
        "type": "SOLID",
        "width": "0.12 mm",
        "color": "#777777",
    }
    table = next(table for table in inspected["tables"] if table["width_mm"] == 168.0)
    assert table["cell_widths_hwpunit"][:2] == [38551, 9071]


@pytest.mark.skipif(not hwpx_available(), reason="python-hwpx extra 필요")
def test_page_setup_writes_hangul_portrait_orientation_token(tmp_path: Path) -> None:
    from hwpctl.hwpx.document import (
        close_document,
        new_document,
        open_document,
        save_document,
    )
    from hwpctl.hwpx.write import HWPX_PORTRAIT, set_page_setup

    doc = new_document()
    try:
        set_page_setup(
            doc,
            paper_size="A4",
            orientation="PORTRAIT",
            margin_left_mm=20,
            margin_right_mm=20,
        )
        out = tmp_path / "a4-portrait.hwpx"
        save_document(doc, out)
    finally:
        close_document(doc)

    reopened = open_document(out)
    round_tripped = tmp_path / "a4-portrait-round-tripped.hwpx"
    try:
        save_document(reopened, round_tripped)
    finally:
        close_document(reopened)

    inspected = inspect_hwpx(round_tripped)
    section = inspected["section_page_properties"][0]
    assert section["sec_pr_count"] == 1
    assert section["page_pr_count"] == 1
    page = section["pages"][0]
    # Hangul's OWPML flag is WIDELY for 세로; PORTRAIT is not a legal
    # `pagePr/@landscape` value even though it looks more intuitive.
    assert page["landscape_attr"] == HWPX_PORTRAIT == "WIDELY"
    assert page["width_hwpunit"] == 59528
    assert page["height_hwpunit"] == 84189
    assert page["width_hwpunit"] < page["height_hwpunit"]


@pytest.mark.skipif(not hwpx_available(), reason="python-hwpx extra 필요")
def test_page_setup_writes_hangul_landscape_orientation_token(tmp_path: Path) -> None:
    from hwpctl.hwpx.document import close_document, new_document, save_document
    from hwpctl.hwpx.write import HWPX_LANDSCAPE, set_page_setup

    doc = new_document()
    try:
        set_page_setup(doc, paper_size="A4", orientation="LANDSCAPE")
        out = tmp_path / "a4-landscape.hwpx"
        save_document(doc, out)
    finally:
        close_document(doc)

    page = inspect_hwpx(out)["section_page_properties"][0]["pages"][0]
    # HWPX keeps A4's physical dimensions; Hangul rotates it from this
    # NARROWLY token rather than from a width/height swap.
    assert page["landscape_attr"] == HWPX_LANDSCAPE == "NARROWLY"
    assert page["width_hwpunit"] == 59528
    assert page["height_hwpunit"] == 84189
    assert page["width_hwpunit"] < page["height_hwpunit"]


@pytest.mark.skipif(not hwpx_available(), reason="python-hwpx extra 필요")
def test_gongo_page1_rebuild_has_hangul_openable_style_truth(tmp_path: Path) -> None:
    from hwpctl.hwpx.gongo import rebuild_gongo_page1

    out = rebuild_gongo_page1(tmp_path / "rebuild_p1.hwpx")
    inspected = inspect_hwpx(out)

    assert out.is_file()
    assert inspected["table_count"] == 1
    section = inspected["section_page_properties"][0]
    assert section["sec_pr_count"] == 1
    page = section["pages"][0]
    assert page["landscape_attr"] == "WIDELY"
    assert page["width_hwpunit"] == 59528
    assert page["height_hwpunit"] == 84189
    assert set(("휴먼명조", "HY헤드라인M")).issubset(
        set(inspected["definitions"]["fonts"].values())
    )
    title = next(
        group
        for group in inspected["run_groups"]
        if group["sample_text"].startswith("「2026년 혁신 소상공인 AI 활용지원 사업")
        and group["font"] == "HY헤드라인M"
    )
    assert title["size_pt"] == 20.0
    assert title["bold"] is True

    intro = next(
        group
        for group in inspected["paragraph_groups"]
        if "중소벤처기업부와 소상공인시장진흥공단" in group["sample_text"]
    )
    assert intro["align"] == "JUSTIFY"
    assert intro["line_spacing_percent"] == 160
    assert any(
        group["align"] == "RIGHT" and "2026년 6월 12일" in group["sample_text"]
        for group in inspected["paragraph_groups"]
    )

    deadline = next(
        group
        for group in inspected["run_groups"]
        if "7. 3(금) 16시까지" in group["sample_text"]
    )
    assert deadline["color"] == "#FF0000"
    assert deadline["underline"] is True
    assert deadline["underline_color"] == "#FF0000"
    application_text = next(
        run for run in inspected["runs"] if "소상공인24 홈페이지" in run["text"]
    )
    assert application_text["color"] == "#000000"
    assert application_text["underline"] is False
    assert application_text["bold"] is False
    question_label = next(
        run for run in inspected["runs"] if run["text"] == "❶ 무엇을 지원해주나요?"
    )
    assert question_label["font"] == "HY헤드라인M"
    assert question_label["bold"] is True

    cream_cells = next(
        group
        for group in inspected["cell_fill_groups"]
        if group["fill"] == "#FCF5E7"
    )
    assert cream_cells["count"] == 1
    assert cream_cells["borders"]["top"]["type"] == "SOLID"
    table = inspected["tables"][0]
    assert table["width_mm"] == 168.0
    assert table["cell_widths_hwpunit"][:2] == [38551, 9071]


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
