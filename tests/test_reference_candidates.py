"""Synthetic promotion evidence: no private documents or source geometry."""
from fractions import Fraction
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from hwpctl.reference import analyze_hwpml, solve_grid_tracks, export_reference_bundle_readonly
from hwpctl.units import mm_to_hwpunit, hwpunit_to_mm, hwpunit_to_points


@pytest.mark.parametrize("value", [0, -12.017, 21.013, 297])
def test_units_round_once(value):
    assert abs(hwpunit_to_mm(mm_to_hwpunit(value)) - value) <= 25.4 / 14400
    assert hwpunit_to_points(100) == 1


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "12"])
def test_units_reject_non_numeric_or_non_finite(value):
    with pytest.raises(ValueError):
        mm_to_hwpunit(value)


def test_exact_grid_with_merged_cells_and_fractional_solution():
    result = solve_grid_tracks(3, [(0, 2, 301), (1, 2, 501), (0, 3, 601)])
    assert result.status == "exact"
    assert result.tracks_hwp == (100, 201, 300)
    assert all(isinstance(value, Fraction) for value in result.tracks_hwp)


def test_underdetermined_is_not_equal_distribution():
    result = solve_grid_tracks(3, [(0, 1, 100), (1, 2, 500)])
    assert result.status == "underdetermined"
    assert result.tracks_hwp == (100, None, None)


@pytest.mark.parametrize("facts", [[(0, 1, 100), (0, 1, 101)], [(0, 1, 200), (0, 2, 100)]])
def test_inconsistent_or_negative_tracks_are_not_rescaled(facts):
    assert solve_grid_tracks(2, facts).status == "inconsistent"


@pytest.mark.parametrize("facts", [[(-1, 1, 100)], [(0, 3, 100)], [(0, 1, 0)], [(True, 1, 100)]])
def test_bad_grid_inputs_fail(facts):
    with pytest.raises(ValueError):
        solve_grid_tracks(2, facts)


def test_analyzer_is_static_and_preserves_text():
    result = analyze_hwpml('<HWPML><BODY><SECTION><P><TEXT><CHAR>합성</CHAR></TEXT></P></SECTION></BODY></HWPML>')
    assert result.document.visible_text == "합성"
    assert result.section_count == 1 and result.table_count == 0
    result.require_supported()


def test_analyzer_accepts_exact_multisection_and_nested_table_structure():
    inner = '<TABLE RowCount="1" ColCount="1"><ROW><CELL RowAddr="0" ColAddr="0" RowSpan="1" ColSpan="1" Width="50"/></ROW></TABLE>'
    outer = (
        '<TABLE RowCount="1" ColCount="1"><ROW><CELL RowAddr="0" ColAddr="0" '
        'RowSpan="1" ColSpan="1" Width="100"><PARALIST><P><TEXT>'
        + inner + '</TEXT></P></PARALIST></CELL></ROW></TABLE>'
    )
    xml = (
        '<HWPML><BODY><SECTION><P><TEXT>before'
        + outer + 'middle' + outer + 'after</TEXT></P></SECTION>'
        '<SECTION><P><TEXT>second</TEXT></P></SECTION></BODY></HWPML>'
    )
    result = analyze_hwpml(xml)
    assert result.section_count == 2
    assert result.table_count == 4
    assert all(grid.status == "exact" for grid in result.table_grids)
    assert result.document.visible_text == "beforemiddleaftersecond"
    assert len(result.document.sections[0].blocks[0].tables) == 2
    result.require_supported()


def test_analyzer_reports_loss_before_authoring():
    xml = '<HWPML><BODY><SECTION><P><TEXT CharShape="99"><FIELD/><TABLE ColCount="2"><ROW><CELL ColAddr="0" ColSpan="2" Width="100"/></ROW></TABLE><TABLE ColCount="2"/></TEXT></P></SECTION><SECTION/></BODY></HWPML>'
    result = analyze_hwpml(xml)
    assert result.table_count == 2
    assert result.section_count == 2
    assert len(result.document.sections) == 2
    assert len(result.document.sections[0].blocks[0].tables) == 2
    assert {"control:FIELD", "unresolved:CharShape", "grid_underdetermined"} <= set(result.blockers)
    assert "section_count_not_one" not in result.blockers
    assert "multiple_or_nested_tables" not in result.blockers
    with pytest.raises(ValueError, match="explicit handling"):
        result.require_supported()


class AssetApp:
    PageCount = 1
    def __init__(self, source, asset, *, mutate=False, missing=False, linked=False):
        self.source, self.asset = source, asset
        self.mutate, self.missing, self.linked = mutate, missing, linked
        self.XHwpDocuments = self
        self.closed = self.quit = False
    def RegisterModule(self, *args):
        pass
    def Open(self, path, fmt, options):
        assert options == "readonly:true"
        return True
    def GetTextFile(self, *args):
        kind = "Link" if self.linked else "Embedding"
        return f'<HWPML><BINITEM BinData="1" Type="{kind}"/><IMAGE BinItem="1"/><IMAGE BinItem="1"/></HWPML>'
    def GetBinDataPath(self, number):
        assert number == 1 and not self.closed and not self.linked
        if self.mutate:
            self.source.write_bytes(b"changed")
        return "" if self.missing else str(self.asset)
    def Close(self, save):
        assert not save
        self.closed = True
    def Quit(self):
        self.quit = True


@pytest.mark.parametrize("missing,linked", [(False, False), (True, False), (False, True)])
def test_asset_bundle_hashes_and_missing_evidence(tmp_path, missing, linked):
    source, asset, output = tmp_path / "source.hwp", tmp_path / "synthetic.png", tmp_path / "bundle"
    source.write_bytes(b"synthetic HWP fixture")
    asset.write_bytes(b"synthetic asset bytes")
    app = AssetApp(source, asset, missing=missing, linked=linked)
    manifest = export_reference_bundle_readonly(source, output, _dispatch=lambda _: app)
    assert app.closed and app.quit
    assert manifest["source_unchanged"]
    assert manifest["assets_complete"] == (not missing and not linked)
    assert len(manifest["assets"]) == 1
    assert str(tmp_path) not in repr(manifest)
    ET.parse(output / "reference.hwpml")
    assert (output / "manifest.json").exists()
    with pytest.raises(FileExistsError):
        export_reference_bundle_readonly(source, output)


def test_changed_source_never_publishes_bundle(tmp_path):
    source, asset, output = tmp_path / "source.hwp", tmp_path / "asset.png", tmp_path / "bundle"
    source.write_bytes(b"original")
    asset.write_bytes(b"synthetic")
    app = AssetApp(source, asset, mutate=True)
    with pytest.raises(RuntimeError, match="SHA-256"):
        export_reference_bundle_readonly(source, output, _dispatch=lambda _: app)
    assert not output.exists() and app.closed and app.quit


def test_existing_empty_bundle_is_not_reused(tmp_path):
    source, output = tmp_path / "source.hwp", tmp_path / "bundle"
    source.write_bytes(b"original")
    output.mkdir()
    with pytest.raises(FileExistsError):
        export_reference_bundle_readonly(source, output, _dispatch=lambda _: pytest.fail("must not dispatch"))


def test_inspector_does_not_label_fixed_hu_spacing_as_percent():
    from hwpctl.hwpx.inspect import _parse_para_pr
    root = ET.fromstring('<head><paraPr id="0"><lineSpacing type="FIXED" value="1200" unit="HWPUNIT"/></paraPr></head>')
    spacing = _parse_para_pr(root)["0"]
    assert spacing["line_spacing_percent"] is None
    assert spacing["line_spacing_value"] == 1200
    assert spacing["line_spacing_unit"] == "HWPUNIT"
