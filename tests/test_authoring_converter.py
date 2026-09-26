"""Independent synthetic references for the conservative conversion contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from hwpctl.authoring.converter import reference_to_spec
from hwpctl.errors import UsageError


HEAD = """<HEAD><MAPPINGTABLE><CHARSHAPELIST><CHARSHAPE Id="1" Height="1000" TextColor="#112233"/></CHARSHAPELIST>
<PARASHAPELIST><PARASHAPE Id="1" Align="Left"/></PARASHAPELIST></MAPPINGTABLE></HEAD>"""


def hwpml(body: str) -> str:
    return f'<HWPML>{HEAD}<BODY>{body}</BODY></HWPML>'


def para(content: str) -> str:
    return f'<P ParaShape="1"><TEXT CharShape="1">{content}</TEXT></P>'


def table(cells: str, *, rows: int = 1, cols: int = 1, attrs: str = "") -> str:
    return f'<TABLE RowCount="{rows}" ColCount="{cols}"{attrs}><ROW>{cells}</ROW></TABLE>'


def cell(row: int, col: int, width: int, height: int, content: str, *, attrs: str = "") -> str:
    return (f'<CELL RowAddr="{row}" ColAddr="{col}" Width="{width}" Height="{height}"{attrs}>'
            f'<PARALIST>{content}</PARALIST></CELL>')


def _write(tmp_path: Path, text: str, name: str = "synthetic.hwpml") -> Path:
    source = tmp_path / name
    source.write_text(text, encoding="utf-8")
    return source


def test_two_sections_and_mixed_inline_object_order_dry_run(tmp_path: Path) -> None:
    first = table(cell(0, 0, 300, 200, para("one")))
    second = table(cell(0, 0, 600, 400, para("two")))
    source = _write(tmp_path, hwpml(f'<SECTION>{para("A" + first + "B" + second + "C")}</SECTION>'
                                      f'<SECTION>{para("last")}</SECTION>'))
    output = tmp_path / "converted"

    result = reference_to_spec(source, output, dry_run=True)

    assert result["ok"] and result["executable"] and result["output_dir"] is None
    assert not output.exists()
    spec = result["spec"]
    assert len(spec["sections"]) == 2
    parts = spec["sections"][0]["content"][0]["content"]
    assert [node["kind"] for node in parts] == ["run", "table", "run", "table", "run"]
    assert [node["text"] for node in parts if node["kind"] == "run"] == ["A", "B", "C"]
    assert parts[1]["cells"]["A1"]["content"][0]["runs"][0]["text"] == "one"
    assert parts[3]["cells"]["A1"]["content"][0]["runs"][0]["text"] == "two"
    assert result["report"]["section_count"] == 2
    assert all(node["source"].startswith("hwpml:section[") for node in parts)


def test_hwpml_page_definition_inside_section_control_is_not_dropped(tmp_path: Path) -> None:
    from hwpctl.units import hwpunit_to_mm

    declaration = ('<SECDEF><PAGEDEF Width="59528" Height="84189">'
                   '<PAGEMARGIN Left="5669" Right="5669" Top="5669" Bottom="5669"/>'
                   '</PAGEDEF></SECDEF>')
    source = _write(tmp_path, hwpml(f'<SECTION>{para(declaration + "body")}</SECTION>'))

    result = reference_to_spec(source, tmp_path / "nested-page", dry_run=True)

    assert result["ok"], result["report"]["losses"]
    section = result["spec"]["sections"][0]
    assert section["page"] == {
        "paper_width": hwpunit_to_mm(59528),
        "paper_height": hwpunit_to_mm(84189),
        "left": hwpunit_to_mm(5669), "right": hwpunit_to_mm(5669),
        "top": hwpunit_to_mm(5669), "bottom": hwpunit_to_mm(5669),
    }
    assert section["content"][0]["runs"][0]["text"] == "body"


def test_multiple_page_definitions_in_one_section_fail_closed(tmp_path: Path) -> None:
    definitions = '<PAGEDEF Width="59528" Height="84189"/>' * 2
    source = _write(tmp_path, hwpml(f'<SECTION>{para(definitions + "body")}</SECTION>'))

    result = reference_to_spec(source, tmp_path / "ambiguous-page", dry_run=True)

    assert not result["ok"] and not result["executable"]
    assert any("multiple page definitions" in item["detail"] for item in result["report"]["losses"])


def test_vertical_merge_exact_hu_and_cell_margin_presence(tmp_path: Path) -> None:
    # The second track is determined by the merged cell and first row, not by
    # a first-row or outer-box proportion.
    merged = cell(0, 0, 300, 600, para("merged"), attrs=' RowSpan="2" HasMargin="0"')
    # Build two rows manually to retain the anchor at B2.
    top = cell(0, 1, 600, 200, para("top"))
    bottom = cell(1, 1, 600, 400, para("bottom"))
    xml = f'<TABLE RowCount="2" ColCount="2" RepeatHeader="0"><ROW>{merged}{top}</ROW><ROW>{bottom}</ROW></TABLE>'
    source = _write(tmp_path, hwpml(f'<SECTION>{para(xml)}</SECTION>'))

    result = reference_to_spec(source, tmp_path / "out", dry_run=True)

    assert result["ok"], result["report"]["losses"]
    table_node = result["spec"]["sections"][0]["content"][0]["content"][0]
    assert table_node["merges"] == ["A1:A2"]
    assert table_node["properties"]["repeat_header"] is False
    assert table_node["cells"]["A1"]["has_margin"] is False
    assert "has_margin" not in table_node["cells"]["B1"]
    detail = next(entry["detail"] for entry in result["report"]["entries"]
                  if entry["source"].endswith("/TABLE[0]") and '"columns"' in entry.get("detail", ""))
    assert '"columns": [300, 600]' in detail
    assert '"rows": [200, 400]' in detail


def test_nested_table_and_cell_order(tmp_path: Path) -> None:
    inner = table(cell(0, 0, 100, 120, para("inside")))
    outer = table(cell(0, 0, 900, 500, para("before" + inner + "after")))
    source = _write(tmp_path, hwpml(f'<SECTION>{para("start" + outer + "end")}</SECTION>'))

    result = reference_to_spec(source, tmp_path / "nested", dry_run=True)

    assert result["ok"], result["report"]["losses"]
    outer_node = result["spec"]["sections"][0]["content"][0]["content"][1]
    children = outer_node["cells"]["A1"]["content"][0]["content"]
    assert [node["kind"] for node in children] == ["run", "table", "run"]
    assert children[1]["cells"]["A1"]["content"][0]["runs"][0]["text"] == "inside"


def test_underdetermined_grid_blocks_without_output(tmp_path: Path) -> None:
    merged = cell(0, 0, 900, 200, para("span"), attrs=' ColSpan="2"')
    source = _write(tmp_path, hwpml(f'<SECTION>{para(table(merged, cols=2))}</SECTION>'))
    result = reference_to_spec(source, tmp_path / "blocked")
    assert not result["ok"] and not result["executable"] and result["spec"] is None
    assert result["report"]["status"] == "blocked"
    assert "underdetermined" in str(result["report"]["losses"])
    assert not (tmp_path / "blocked").exists()


def test_unrecognized_control_and_unresolved_style_report_location(tmp_path: Path) -> None:
    source = _write(tmp_path, hwpml('<SECTION><P ParaShape="404"><TEXT CharShape="1">A<FIELD/>B</TEXT></P></SECTION>'))
    result = reference_to_spec(source, tmp_path / "blocked", dry_run=True)
    assert not result["ok"]
    assert any("unresolved paragraph style" in entry["detail"] for entry in result["report"]["losses"])
    assert any("unsupported inline control FIELD" in entry["detail"] for entry in result["report"]["losses"])
    assert all(entry["source"].startswith("hwpml:section[0]") for entry in result["report"]["losses"])


def test_character_fill_and_tab_stop_references_are_not_silently_dropped(tmp_path: Path) -> None:
    head = ('<HEAD><MAPPINGTABLE><BORDERFILLLIST><BORDERFILL Id="2">'
            '<WINDOWBRUSH FaceColor="#FF00FF"/></BORDERFILL></BORDERFILLLIST>'
            '<CHARSHAPELIST><CHARSHAPE Id="1" BorderFillIDRef="2"/></CHARSHAPELIST>'
            '<PARASHAPELIST><PARASHAPE Id="1" TabPrIDRef="3"/></PARASHAPELIST>'
            '</MAPPINGTABLE></HEAD>')
    source = _write(tmp_path, f'<HWPML>{head}<BODY><SECTION>{para("a<TAB/>b")}</SECTION></BODY></HWPML>')

    result = reference_to_spec(source, tmp_path / "blocked-style", dry_run=True)

    assert not result["ok"] and not result["executable"]
    details = [entry["detail"] for entry in result["report"]["losses"]]
    assert any("character border/fill" in detail for detail in details)
    assert any("tab-stop reference" in detail for detail in details)


def test_ordinary_run_explicitly_turns_off_preceding_bold_style(tmp_path: Path) -> None:
    head = ('<HEAD><MAPPINGTABLE><CHARSHAPELIST>'
            '<CHARSHAPE Id="1" Height="1000" TextColor="#112233"><BOLD/></CHARSHAPE>'
            '<CHARSHAPE Id="2" Height="1000" TextColor="#112233"/>'
            '</CHARSHAPELIST><PARASHAPELIST><PARASHAPE Id="1" Align="Left"/>'
            '</PARASHAPELIST></MAPPINGTABLE></HEAD>')
    source = _write(tmp_path, '<HWPML>' + head + '<BODY><SECTION><P ParaShape="1">'
                    '<TEXT CharShape="1">heavy</TEXT><TEXT CharShape="2">normal</TEXT>'
                    '</P></SECTION></BODY></HWPML>')

    result = reference_to_spec(source, tmp_path / "mixed", dry_run=True)

    assert result["ok"], result["report"]["losses"]
    runs = result["spec"]["sections"][0]["content"][0]["runs"]
    assert runs[0]["bold"] is True
    assert runs[1]["bold"] is False
    assert runs[1]["italic"] is False
    assert runs[1]["underline"] is False


def test_special_spacing_controls_are_reported_as_loss(tmp_path: Path) -> None:
    source = _write(tmp_path, hwpml(f'<SECTION>{para("a<NBSPACE/>b<FWSPACE/>c<FIXEDWIDTHSPACE/>d")}</SECTION>'))

    result = reference_to_spec(source, tmp_path / "spacing", dry_run=True)

    assert not result["ok"] and not result["executable"]
    details = [item["detail"] for item in result["report"]["losses"]]
    assert all(any(name in detail for detail in details)
               for name in ("NBSPACE", "FWSPACE", "FIXEDWIDTHSPACE"))


def test_success_publishes_fresh_spec_and_refuses_overwrite(tmp_path: Path) -> None:
    source = _write(tmp_path, hwpml(f'<SECTION>{para("synthetic")}</SECTION>'))
    output = tmp_path / "published"
    first = reference_to_spec(source, output)
    assert first["ok"] and Path(first["spec"]) == output / "spec.json"
    spec = json.loads((output / "spec.json").read_text(encoding="utf-8"))
    assert spec["sections"][0]["content"][0]["runs"][0]["text"] == "synthetic"
    assert json.loads((output / "report.json").read_text(encoding="utf-8"))["status"] == "ready"
    assert source.read_text(encoding="utf-8") == hwpml(f'<SECTION>{para("synthetic")}</SECTION>')
    with pytest.raises(UsageError, match="new directory"):
        reference_to_spec(source, output)


def test_capture_bundle_embedded_picture_and_digest(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "assets").mkdir(parents=True)
    image = b"synthetic png bytes"
    (bundle / "assets" / "bin-1.png").write_bytes(image)
    picture_paragraph = para('before<PICTURE Width="300" Height="200"><IMAGE BinItem="1"/></PICTURE>after')
    xml = hwpml(f"<SECTION>{picture_paragraph}</SECTION>")
    (bundle / "reference.hwpml").write_text(xml, encoding="utf-8")
    manifest = {"source_unchanged": True, "hwpml": "reference.hwpml", "assets": [
        {"bin_item": 1, "extracted": True, "path": "assets/bin-1.png", "sha256": hashlib.sha256(image).hexdigest()}]}
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "published"

    result = reference_to_spec(bundle, output)

    assert result["ok"], result["report"]["losses"]
    assert (output / "assets" / "bin-1.png").read_bytes() == image
    spec = json.loads((output / "spec.json").read_text(encoding="utf-8"))
    assert spec["assets"]["bin-1"]["sha256"] == hashlib.sha256(image).hexdigest()
    assert [item["kind"] for item in spec["sections"][0]["content"][0]["content"]] == ["run", "picture", "run"]


def test_hwpx_section_order_from_manifest(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.hwpx"
    manifest = ('<package><manifest><item id="header" href="Contents/header.xml"/>'
                '<item id="section0" href="Contents/section0.xml"/>'
                '<item id="section1" href="Contents/section1.xml"/></manifest>'
                '<spine><itemref idref="header"/><itemref idref="section1"/><itemref idref="section0"/></spine></package>')
    head = '<head><fontface lang="HANGUL"><font id="0" face="Synthetic" type="TTF"/></fontface><charPr id="0"/><paraPr id="0"/></head>'
    one = '<sec><p paraPrIDRef="0"><run charPrIDRef="0"><t>first</t></run></p></sec>'
    two = '<sec><p paraPrIDRef="0"><run charPrIDRef="0"><t>second</t></run></p></sec>'
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("Contents/content.hpf", manifest)
        archive.writestr("Contents/header.xml", head)
        archive.writestr("Contents/section0.xml", one)
        archive.writestr("Contents/section1.xml", two)
    result = reference_to_spec(source, tmp_path / "converted", dry_run=True)
    assert result["ok"], result["report"]["losses"]
    assert [section["content"][0]["runs"][0]["text"] for section in result["spec"]["sections"]] == ["second", "first"]


def test_hwpml_dtd_rejected_before_any_output(tmp_path: Path) -> None:
    source = _write(tmp_path, '<!DOCTYPE HWPML [<!ENTITY x "unsafe">]><HWPML><BODY><SECTION/></BODY></HWPML>')
    with pytest.raises(UsageError, match="DTD"):
        reference_to_spec(source, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_hwpml_floating_picture_preserves_explicit_anchor_and_offsets(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "assets").mkdir(parents=True)
    payload = b"owned synthetic image data"
    (bundle / "assets" / "bin-1.png").write_bytes(payload)
    picture = ('<PICTURE><SHAPEOBJECT TextWrap="BehindText" TextFlow="BothSides">'
               '<SIZE Width="2840" Height="1420" WidthRelTo="Absolute" HeightRelTo="Absolute"/>'
               '<POSITION TreatAsChar="false" HorzRelTo="Page" VertRelTo="Paper" '
               'HorzAlign="Left" VertAlign="Top" HorzOffset="568" VertOffset="852" '
               'FlowWithText="false" AllowOverlap="true"/>'
               '<OUTSIDEMARGIN Left="0" Right="0" Top="0" Bottom="0"/>'
               '</SHAPEOBJECT><IMAGE BinItem="1"/></PICTURE>')
    (bundle / "reference.hwpml").write_text(hwpml(f'<SECTION>{para(picture)}</SECTION>'), encoding="utf-8")
    (bundle / "manifest.json").write_text(json.dumps({"source_unchanged": True, "hwpml": "reference.hwpml",
        "assets": [{"bin_item": 1, "extracted": True, "path": "assets/bin-1.png",
                    "sha256": hashlib.sha256(payload).hexdigest()}]}), encoding="utf-8")

    result = reference_to_spec(bundle, tmp_path / "converted", dry_run=True)

    assert result["ok"], result["report"]["losses"]
    item = result["spec"]["sections"][0]["content"][0]["content"][0]
    assert item["width_mm"] == pytest.approx(10.0188888889)
    assert item["position"] == {"mode": "floating", "horizontal_relative_to": "page",
                                "vertical_relative_to": "paper", "horizontal_align": "left",
                                "vertical_align": "top", "x_mm": pytest.approx(2.0037777778),
                                "y_mm": pytest.approx(3.0056666667), "wrap": "behind_text",
                                "flow_with_text": False, "allow_overlap": True,
                                "outside_margin_mm": [0, 0, 0, 0]}


def test_exact_cell_borders_and_radial_gradient_are_authored(tmp_path: Path) -> None:
    head = HEAD.replace('</MAPPINGTABLE>',
        '<BORDERFILLLIST><BORDERFILL Id="7">'
        '<LEFTBORDER Type="Solid" Width="0.12mm" Color="#112233"/>'
        '<RIGHTBORDER Type="None"/><TOPBORDER Type="Solid" Width="0.2mm" Color="#445566"/>'
        '<BOTTOMBORDER Type="None"/><FILLBRUSH>'
        '<GRADATION Type="Radial" Angle="90" CenterX="50" CenterY="25" Step="75" '
        'StepCenter="50" ColorNum="2" Alpha="0">'
        '<COLOR Value="#123456"/><COLOR Value="#ABCDEF"/></GRADATION>'
        '</FILLBRUSH></BORDERFILL></BORDERFILLLIST></MAPPINGTABLE>')
    one = cell(0, 0, 600, 400, para("tone"), attrs=' BorderFill="7"')
    source = _write(tmp_path, f'<HWPML>{head}<BODY><SECTION>{para(table(one))}</SECTION></BODY></HWPML>')

    result = reference_to_spec(source, tmp_path / "out", dry_run=True)

    assert result["ok"], result["report"]["losses"]
    cell_spec = result["spec"]["sections"][0]["content"][0]["content"][0]["cells"]["A1"]
    assert cell_spec["borders"] == [
        {"sides": "left", "line_type": "Solid", "width": "0.12mm", "color": "#112233"},
        {"sides": "right", "line_type": "None", "width": "0.12mm", "color": "#000000"},
        {"sides": "top", "line_type": "Solid", "width": "0.2mm", "color": "#445566"},
        {"sides": "bottom", "line_type": "None", "width": "0.12mm", "color": "#000000"},
    ]
    assert cell_spec["fill"] == {"type": "radial_gradient", "angle": 90,
                                 "stops": ["#123456", "#ABCDEF"], "center_x": 50,
                                 "center_y": 25, "step": 75, "step_center": 50}


def test_editable_rectangle_and_text_box_preserve_order(tmp_path: Path) -> None:
    frame = ('<SHAPEOBJECT><SIZE Width="2840" Height="1420" WidthRelTo="Absolute" '
             'HeightRelTo="Absolute"/><POSITION TreatAsChar="true"/></SHAPEOBJECT>')
    line = '<LINESHAPE Style="Solid" Width="34" Color="#001122"/>'
    fill = '<FILLBRUSH><WINDOWBRUSH FaceColor="#ABCDEF" Alpha="0"/></FILLBRUSH>'
    rect_attrs = 'Ratio="0" X0="0" Y0="0" X1="2840" Y1="0" X2="2840" Y2="1420" X3="0" Y3="1420"'
    rect = f'<RECTANGLE {rect_attrs}>{frame}<DRAWINGOBJECT>{line}{fill}</DRAWINGOBJECT></RECTANGLE>'
    box = (f'<RECTANGLE {rect_attrs}>{frame}<DRAWINGOBJECT>{line}{fill}'
           f'<DRAWTEXT Editable="true"><TEXTMARGIN Left="0" Right="0" Top="0" Bottom="0"/>'
           f'<PARALIST>{para("editable")}</PARALIST></DRAWTEXT></DRAWINGOBJECT></RECTANGLE>')
    source = _write(tmp_path, hwpml(f'<SECTION>{para("A" + rect + "B" + box + "C")}</SECTION>'))

    result = reference_to_spec(source, tmp_path / "out", dry_run=True)

    assert result["ok"], result["report"]["losses"]
    parts = result["spec"]["sections"][0]["content"][0]["content"]
    assert [part["kind"] for part in parts] == ["run", "shape", "run", "text_box", "run"]
    assert parts[1]["shape_kind"] == "rectangle"
    assert parts[1]["fill"]["color"] == "#ABCDEF"
    assert parts[3]["paragraphs"][0]["runs"][0]["text"] == "editable"


def test_nonrepresentable_gradient_and_chart_fail_closed(tmp_path: Path) -> None:
    head = HEAD.replace('</MAPPINGTABLE>',
        '<BORDERFILLLIST><BORDERFILL Id="7"><FILLBRUSH>'
        '<GRADATION Type="Linear" Angle="90" Step="50" ColorNum="2">'
        '<COLOR Value="#000000"/><COLOR Value="#FFFFFF"/>'
        '</GRADATION></FILLBRUSH></BORDERFILL></BORDERFILLLIST></MAPPINGTABLE>')
    one = cell(0, 0, 600, 400, para("tone"), attrs=' BorderFill="7"')
    chart_paragraph = para(table(one) + '<CHART TableRef="1"/>')
    xml = f'<HWPML>{head}<BODY><SECTION>{chart_paragraph}</SECTION></BODY></HWPML>'
    source = _write(tmp_path, xml)

    result = reference_to_spec(source, tmp_path / "out")

    assert not result["ok"] and result["spec"] is None
    assert not (tmp_path / "out").exists()
    details = [entry["detail"] for entry in result["report"]["losses"]]
    assert any("linear gradient center/step differs" in item for item in details)
    assert any("HWPML 3.0 has no CHART element" in item for item in details)


def test_hwpx_direct_editable_rectangle_without_rasterization(tmp_path: Path) -> None:
    source = tmp_path / "drawing.hwpx"
    manifest = ('<package><manifest><item id="header" href="Contents/header.xml"/>'
                '<item id="section0" href="Contents/section0.xml"/></manifest>'
                '<spine><itemref idref="header"/><itemref idref="section0"/></spine></package>')
    header = '<head><charPr id="0"/><paraPr id="0"/></head>'
    rectangle = ('<hp:rect ratio="0" id="17" zOrder="0" numberingType="NONE" lock="0" '
                 'dropcapstyle="None" href="" groupLevel="0" instid="17">'
                 '<hp:offset x="0" y="0"/><hp:orgSz width="2840" height="1420"/>'
                 '<hp:curSz width="2840" height="1420"/><hp:flip horizontal="0" vertical="0"/>'
                 '<hp:rotationInfo angle="0" centerX="1420" centerY="710" rotateimage="1"/>'
                 '<hp:renderingInfo><hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
                 '<hc:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
                 '<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/></hp:renderingInfo>'
                 '<hp:lineShape style="SOLID" width="34" color="#112233" endCap="FLAT" '
                 'headStyle="NORMAL" tailStyle="NORMAL" headfill="1" tailfill="1" '
                 'headSz="SMALL_SMALL" tailSz="SMALL_SMALL" outlineStyle="NORMAL" alpha="0"/>'
                 '<hc:fillBrush><hc:winBrush faceColor="#ABCDEF" hatchColor="#FFFFFF"/></hc:fillBrush>'
                 '<hp:shadow type="NONE" color="#B2B2B2" offsetX="0" offsetY="0" alpha="0"/>'
                 '<hc:pt0 x="0" y="0"/><hc:pt1 x="2840" y="0"/>'
                 '<hc:pt2 x="2840" y="1420"/><hc:pt3 x="0" y="1420"/>'
                 '<hp:sz width="2840" height="1420" widthRelTo="ABSOLUTE" heightRelTo="ABSOLUTE" protect="0"/>'
                 '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
                 'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" '
                 'vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
                 '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
                 '</hp:rect>')
    section = ('<hs:sec xmlns:hs="urn:sect" xmlns:hp="urn:para" xmlns:hc="urn:core">'
               f'<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0"><hp:t>before</hp:t>{rectangle}'
               '<hp:t>after</hp:t></hp:run></hp:p></hs:sec>')
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("Contents/content.hpf", manifest)
        archive.writestr("Contents/header.xml", header)
        archive.writestr("Contents/section0.xml", section)

    result = reference_to_spec(source, tmp_path / "out", dry_run=True)

    assert result["ok"], result["report"]["losses"]
    parts = result["spec"]["sections"][0]["content"][0]["content"]
    assert [item["kind"] for item in parts] == ["run", "shape", "run"]
    assert parts[1]["shape_kind"] == "rectangle"
    assert parts[1]["line"] == {"type": "solid", "color": "#112233", "width_mm": 0.12}
    assert parts[1]["fill"] == {"type": "solid", "color": "#ABCDEF"}


def test_hwpx_table_raw_hu_and_explicit_inheritance_fields(tmp_path: Path) -> None:
    source = tmp_path / "table.hwpx"
    manifest = ('<package><manifest><item id="header" href="Contents/header.xml"/>'
                '<item id="section0" href="Contents/section0.xml"/></manifest>'
                '<spine><itemref idref="header"/><itemref idref="section0"/></spine></package>')
    header = ('<head><charPr id="0"/><paraPr id="0"/><borderFill id="1" threeD="0" shadow="0" '
              'centerLine="NONE" breakCellSeparateLine="0"><slash type="NONE" Crooked="0" isCounter="0"/>'
              '<backSlash type="NONE" Crooked="0" isCounter="0"/>'
              '<leftBorder type="SOLID" width="0.12 mm" color="#000000"/>'
              '<rightBorder type="SOLID" width="0.12 mm" color="#000000"/>'
              '<topBorder type="SOLID" width="0.12 mm" color="#000000"/>'
              '<bottomBorder type="SOLID" width="0.12 mm" color="#000000"/>'
              '<diagonal type="SOLID" width="0.1 mm" color="#000000"/></borderFill></head>')
    table_xml = ('<hp:tbl id="10" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
                 'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" '
                 'repeatHeader="0" rowCnt="1" colCnt="1" cellSpacing="0" borderFillIDRef="1" noAdjust="0">'
                 '<hp:sz width="7200" height="3600" widthRelTo="ABSOLUTE" heightRelTo="ABSOLUTE" protect="0"/>'
                 '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
                 'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" '
                 'horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
                 '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
                 '<hp:inMargin left="510" right="510" top="141" bottom="141"/>'
                 '<hp:tr><hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" '
                 'dirty="0" borderFillIDRef="1"><hp:subList id="" textDirection="HORIZONTAL" '
                 'lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" linkListNextIDRef="0" '
                 'textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
                 '<hp:p paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
                 '<hp:run charPrIDRef="0"><hp:t>42</hp:t></hp:run></hp:p></hp:subList>'
                 '<hp:cellAddr colAddr="0" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
                 '<hp:cellSz width="7200" height="3600"/><hp:cellMargin left="0" right="0" '
                 'top="0" bottom="0"/></hp:tc></hp:tr></hp:tbl>')
    section = ('<hs:sec xmlns:hs="urn:sect" xmlns:hp="urn:para">'
               f'<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0">{table_xml}</hp:run></hp:p></hs:sec>')
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("Contents/content.hpf", manifest)
        archive.writestr("Contents/header.xml", header)
        archive.writestr("Contents/section0.xml", section)

    result = reference_to_spec(source, tmp_path / "out", dry_run=True)

    assert result["ok"], result["report"]["losses"]
    table_spec = result["spec"]["sections"][0]["content"][0]["content"][0]
    assert table_spec["column_widths_mm"] == [pytest.approx(25.4)]
    assert table_spec["row_heights_mm"] == [pytest.approx(12.7)]
    assert table_spec["default_margin_mm"] == [pytest.approx(1.7991666667), pytest.approx(1.7991666667),
                                               pytest.approx(0.4974166667), pytest.approx(0.4974166667)]
    assert table_spec["properties"] == {"repeat_header": False, "cell_spacing_mm": 0.0,
                                        "page_break": "cell"}
    assert table_spec["cells"]["A1"]["has_margin"] is False
    assert table_spec["cells"]["A1"]["margin_mm"] == [0, 0, 0, 0]


def test_hwpx_chart_part_reports_missing_table_relationship_not_success(tmp_path: Path) -> None:
    source = tmp_path / "chart.hwpx"
    manifest = ('<package><manifest><item id="header" href="Contents/header.xml"/>'
                '<item id="section0" href="Contents/section0.xml"/>'
                '<item id="chart1" href="Chart/chart1.xml"/></manifest>'
                '<spine><itemref idref="header"/><itemref idref="section0"/></spine></package>')
    # ChartML caches do not contain the source HWP table identifier/cell range.
    chart = ('<c:chartSpace xmlns:c="urn:chart"><c:chart><c:plotArea><c:lineChart>'
             '<c:ser><c:idx val="0"/><c:cat><c:strRef><c:strCache/></c:strRef></c:cat>'
             '<c:val><c:numRef><c:numCache/></c:numRef></c:val></c:ser>'
             '</c:lineChart></c:plotArea></c:chart></c:chartSpace>')
    section = ('<hs:sec xmlns:hs="urn:sect" xmlns:hp="urn:para">'
               '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0">'
               '<hp:chart chartIDRef="Chart/chart1.xml"><hp:sz width="3000" height="2000"/>'
               '<hp:pos treatAsChar="1"/></hp:chart></hp:run></hp:p></hs:sec>')
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("Contents/content.hpf", manifest)
        archive.writestr("Contents/header.xml", '<head><charPr id="0"/><paraPr id="0"/></head>')
        archive.writestr("Contents/section0.xml", section)
        archive.writestr("Chart/chart1.xml", chart)

    result = reference_to_spec(source, tmp_path / "out", dry_run=True)

    assert not result["ok"] and result["spec"] is None
    assert not (tmp_path / "out").exists()
    assert any("type=['LINECHART'], series=1" in entry["detail"] and "does not encode a source table/range" in entry["detail"]
               for entry in result["report"]["losses"])


def test_hwpx_floating_picture_uses_raw_hu_not_page_proportions(tmp_path: Path) -> None:
    source = tmp_path / "picture.hwpx"
    manifest = ('<package><manifest><item id="header" href="Contents/header.xml"/>'
                '<item id="section0" href="Contents/section0.xml"/>'
                '<item id="image1" href="BinData/image1.png"/></manifest>'
                '<spine><itemref idref="header"/><itemref idref="section0"/></spine></package>')
    picture = ('<hp:pic id="7" zOrder="0" numberingType="PICTURE" textWrap="SQUARE" '
               'textFlow="BOTH_SIDES" reverse="0" lock="0" dropcapstyle="None" href="" '
               'groupLevel="0" instid="7">'
               '<hp:offset x="0" y="0"/><hp:orgSz width="2840" height="1420"/>'
               '<hp:curSz width="2840" height="1420"/><hp:flip horizontal="0" vertical="0"/>'
               '<hp:rotationInfo angle="0" centerX="1420" centerY="710" rotateimage="1"/>'
               '<hp:renderingInfo><hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
               '<hc:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
               '<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/></hp:renderingInfo>'
               '<hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="2840" y="0"/>'
               '<hc:pt2 x="2840" y="1420"/><hc:pt3 x="0" y="1420"/></hp:imgRect>'
               '<hp:imgClip left="0" right="2840" top="0" bottom="1420"/>'
               '<hp:inMargin left="0" right="0" top="0" bottom="0"/>'
               '<hp:imgDim dimwidth="2840" dimheight="1420"/>'
               '<hc:img binaryItemIDRef="image1" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
               '<hp:effects/><hp:sz width="2840" height="1420" widthRelTo="ABSOLUTE" '
               'heightRelTo="ABSOLUTE" protect="0"/>'
               '<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="0" allowOverlap="1" '
               'holdAnchorAndSO="0" vertRelTo="PAGE" horzRelTo="PAGE" vertAlign="TOP" '
               'horzAlign="LEFT" vertOffset="852" horzOffset="568"/>'
               '<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:shapeComment/></hp:pic>')
    section = ('<hs:sec xmlns:hs="urn:sect" xmlns:hp="urn:para" xmlns:hc="urn:core">'
               f'<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0">{picture}</hp:run></hp:p></hs:sec>')
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("Contents/content.hpf", manifest)
        archive.writestr("Contents/header.xml", '<head><charPr id="0"/><paraPr id="0"/></head>')
        archive.writestr("Contents/section0.xml", section)
        archive.writestr("BinData/image1.png", b"synthetic png fixture")

    result = reference_to_spec(source, tmp_path / "out", dry_run=True)

    assert result["ok"], result["report"]["losses"]
    picture_spec = result["spec"]["sections"][0]["content"][0]["content"][0]
    assert picture_spec["kind"] == "picture"
    assert picture_spec["position"]["x_mm"] == pytest.approx(2.0037777778)
    assert picture_spec["position"]["y_mm"] == pytest.approx(3.0056666667)
    assert picture_spec["position"]["flow_with_text"] is False
    assert picture_spec["position"]["allow_overlap"] is True
