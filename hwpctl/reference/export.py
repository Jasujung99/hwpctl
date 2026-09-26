"""Explicit analysis exports. Not an editable-document authoring route.

Derived from the local read-only HWPML/PDF exporters. No new CLI/MCP command.
Raw exports and extracted assets remain private; never commit captured text.
"""
from pathlib import Path
from typing import Any, Callable

from hwpctl.reference.capture import _default_dispatch, _readonly_app, _sha256, capture_hwpml_readonly


def _xml_bytes(hwpml: str) -> bytes:
    import re
    declaration = re.match(r'\s*<\?xml[^>]*encoding=["\']([^"\']+)', hwpml)
    return hwpml.encode(declaration.group(1) if declaration else "utf-8")


def _paths(source: str | Path, output: str | Path, suffix: str) -> tuple[Path, Path]:
    source = Path(source).expanduser().resolve()
    output = Path(output).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.suffix.lower() != ".hwp":
        raise ValueError("분석 내보내기의 원본은 .hwp여야 합니다.")
    if output.suffix.lower() != suffix:
        raise ValueError(f"내보내기 확장자는 {suffix}여야 합니다.")
    if output == source or output.exists():
        raise FileExistsError("기존 파일이나 원본을 덮어쓰지 않습니다.")
    return source, output


def export_hwpml_readonly(source: str | Path, output: str | Path, *,
                          _dispatch: Callable[[str], Any] | None = None) -> dict[str, Any]:
    """Export memory capture only after source-integrity checks succeed."""
    source, output = _paths(source, output, ".hwpml")
    captured = capture_hwpml_readonly(source, _dispatch=_dispatch)
    output.parent.mkdir(parents=True, exist_ok=True)
    # GetTextFile may declare UTF-16 in a Python string. Write matching bytes.
    payload = _xml_bytes(captured.hwpml)
    with output.open("xb") as stream:
        stream.write(payload)
    return {**captured.manifest_entry("reference"), "output_bytes": len(payload)}


def export_pdf_readonly(source: str | Path, output: str | Path, *,
                        _dispatch: Callable[[str], Any] | None = None) -> dict[str, Any]:
    """Export to an exclusively reserved staging directory; publish after checks.

    COM PageCount is evidence of COM state, not a physical PDF page count.
    """
    import tempfile
    import shutil
    source, output = _paths(source, output, ".pdf")
    before = _sha256(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hwpctl-reference-", dir=output.parent) as staging:
        pdf = Path(staging) / "capture.pdf"
        with _readonly_app(source, _dispatch or _default_dispatch) as app:
            if not app.SaveAs(str(pdf), "PDF", "lock:false;backup:false;autosave:false"):
                raise RuntimeError("PDF 분석 내보내기에 실패했습니다.")
            pages = int(app.PageCount)
        after = _sha256(source)
        if before != after:
            raise RuntimeError("내보내기 전후 원본 SHA-256이 달라졌습니다.")
        if not pdf.is_file() or pdf.stat().st_size == 0:
            raise RuntimeError("PDF 산출물이 비어 있습니다.")
        with pdf.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise RuntimeError("PDF 산출물 헤더가 올바르지 않습니다.")
            stream.seek(0)
            with output.open("xb") as dest:
                shutil.copyfileobj(stream, dest)
    return {"sha256_before": before, "sha256_after": after,
            "source_unchanged": True, "com_page_count": pages,
            "output_bytes": output.stat().st_size}


def export_reference_bundle_readonly(source: str | Path, output_dir: str | Path, *,
                                     _dispatch: Callable[[str], Any] | None = None) -> dict[str, Any]:
    """Capture HWPML and referenced IMAGE BinItems while the owned app is alive.

    Missing assets are explicit in the manifest. Linked files are not followed.
    An existing output directory (including an empty one) is never reused.
    Publication follows source-hash validation; no visual-equivalence claim.
    """
    import json
    import shutil
    import tempfile
    import xml.etree.ElementTree as ET

    source = Path(source).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".hwp":
        raise ValueError("Expected an existing .hwp source")
    if output.exists():
        raise FileExistsError("Existing bundle directory is never overwritten")
    before = _sha256(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hwpctl-assets-", dir=output.parent) as staging:
        stage = Path(staging)
        (stage / "assets").mkdir()
        assets = []
        with _readonly_app(source, _dispatch or _default_dispatch) as app:
            hwpml = str(app.GetTextFile("HWPML2X", ""))
            root = ET.fromstring(hwpml)
            embedded = {node.get("BinData") for node in root.iter()
                        if node.tag.rsplit("}", 1)[-1].upper() == "BINITEM"
                        and node.get("Type", "").lower() == "embedding"}
            numbers = set()
            for node in root.iter():
                if node.tag.rsplit("}", 1)[-1].upper() == "IMAGE":
                    raw = node.get("BinItem", "")
                    if not raw.isdigit() or int(raw) <= 0:
                        raise ValueError("Invalid IMAGE BinItem; cannot claim asset completeness")
                    numbers.add(int(raw))
            for number in sorted(numbers):
                if str(number) not in embedded:
                    assets.append({"bin_item": number, "extracted": False, "reason": "not_embedded"})
                    continue
                raw_path = str(app.GetBinDataPath(number) or "")
                original = Path(raw_path) if raw_path else None
                if original is None or not original.is_file() or original.resolve() == source:
                    assets.append({"bin_item": number, "extracted": False, "reason": "unavailable"})
                    continue
                suffix = original.suffix.lower()
                if suffix not in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".wmf", ".emf"}:
                    suffix = ".bin"
                relative = f"assets/bin-{number}{suffix}"
                destination = stage / relative
                asset_before = _sha256(original)
                shutil.copyfile(original, destination)
                if asset_before != _sha256(destination) or asset_before != _sha256(original):
                    raise RuntimeError("Embedded asset changed during extraction")
                assets.append({"bin_item": number, "extracted": True, "path": relative,
                               "sha256": asset_before, "bytes": destination.stat().st_size})
            pages = int(app.PageCount)
            (stage / "reference.hwpml").write_bytes(_xml_bytes(hwpml))
        after = _sha256(source)
        if before != after:
            raise RuntimeError("Source SHA-256 changed")
        manifest = {"sha256_before": before, "sha256_after": after, "source_unchanged": True,
                    "com_page_count": pages, "hwpml": "reference.hwpml", "assets": assets,
                    "assets_complete": all(asset["extracted"] for asset in assets)}
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        # Reserve exclusively only after capture succeeds. A disk-copy failure may
        # leave an incomplete directory; manifest is copied LAST as completion record.
        output.mkdir(exist_ok=False)
        shutil.copytree(stage / "assets", output / "assets")
        shutil.copyfile(stage / "reference.hwpml", output / "reference.hwpml")
        shutil.copyfile(stage / "manifest.json", output / "manifest.json")
    return manifest
