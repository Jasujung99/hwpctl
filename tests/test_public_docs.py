"""공개 문서가 실제 공개 도구와 어긋나지 않는지 확인한다."""

from __future__ import annotations

from pathlib import Path

from scripts.validate_public_files import documented_tool_names
from hwpctl.tools import tool_names


def test_readme_tool_catalog_matches_public_tool_order() -> None:
    readme = Path(__file__).resolve().parents[1] / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert documented_tool_names(text) == tool_names()


def test_included_new_year_asset_has_generation_provenance_notice() -> None:
    root = Path(__file__).resolve().parents[1]
    relative = "assets/new-year-card/new-year-minhwa-background.png"
    notices = (root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    assert (root / relative).is_file()
    assert relative in notices
    assert "GPT 계열 이미지 생성 모델" in notices
