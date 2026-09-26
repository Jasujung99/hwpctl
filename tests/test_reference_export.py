"""Synthetic export safety tests; no COM and no private source assets."""
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest
from hwpctl.reference import export_hwpml_readonly, export_pdf_readonly


class App:
    PageCount = 2
    def __init__(self, source, *, failure=False, mutate=False):
        self.source, self.failure, self.mutate = source, failure, mutate
        self.closed = self.quit = False
        self.XHwpDocuments = self
    def RegisterModule(self, *args):
        pass
    def Open(self, path, fmt, options):
        assert Path(path) == self.source and fmt == "HWP" and options == "readonly:true"
        return True
    def GetTextFile(self, *args):
        return '<?xml version="1.0" encoding="UTF-16"?><HWPML>합성</HWPML>'
    def SaveAs(self, path, fmt, options):
        assert Path(path) != self.source and fmt == "PDF"
        if self.mutate:
            self.source.write_bytes(b"unexpected modification")
        if self.failure:
            raise RuntimeError("export failed")
        Path(path).write_bytes(b"%PDF-1.4\nsynthetic stub")
        return True
    def Close(self, save):
        assert save is False
        self.closed = True
    def Quit(self):
        self.quit = True


@pytest.mark.parametrize("kind", ["hwpml", "pdf"])
def test_export_preserves_source_and_refuses_overwrite(tmp_path, kind):
    source = tmp_path / "source.hwp"
    source.write_bytes(b"synthetic")
    output = tmp_path / ("output." + kind)
    app = App(source)
    export = export_hwpml_readonly if kind == "hwpml" else export_pdf_readonly
    evidence = export(source, output, _dispatch=lambda _: app)
    assert evidence["source_unchanged"] and source.read_bytes() == b"synthetic"
    assert app.closed and app.quit
    assert str(source) not in repr(evidence)
    if kind == "hwpml":
        assert ET.fromstring(output.read_bytes()).text == "합성"
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        export(source, output, _dispatch=lambda _: pytest.fail("must not dispatch"))
    assert output.read_bytes() == before


@pytest.mark.parametrize("failure,mutate", [(True, False), (False, True), (True, True)])
def test_failed_pdf_is_not_published_and_owned_app_is_closed(tmp_path, failure, mutate):
    source = tmp_path / "source.hwp"
    source.write_bytes(b"synthetic")
    output = tmp_path / "output.pdf"
    app = App(source, failure=failure, mutate=mutate)
    with pytest.raises(RuntimeError, match="SHA-256" if mutate else "export failed"):
        export_pdf_readonly(source, output, _dispatch=lambda _: app)
    assert not output.exists()
    assert app.closed and app.quit
    assert list(tmp_path.iterdir()) == [source]
