"""공개 문서가 실제 공개 도구와 어긋나지 않는지 확인한다."""

from __future__ import annotations

from pathlib import Path

from scripts.validate_public_files import documented_tool_names, highlighted_tool_tables
from hwpctl.tools import tool_names


def test_readme_tool_catalog_matches_public_tool_order() -> None:
    readme = Path(__file__).resolve().parents[1] / "docs" / "guide" / "tools.md"
    text = readme.read_text(encoding="utf-8")
    assert documented_tool_names(text) == tool_names()


def test_readme_highlight_tables_use_real_tools_in_both_languages() -> None:
    readme = Path(__file__).resolve().parents[1] / "README.md"
    tables = highlighted_tool_tables(readme.read_text(encoding="utf-8"))
    assert len(tables) == 2
    assert tables[0] == tables[1]
    assert tables[0] and set(tables[0]) <= set(tool_names())


def test_included_new_year_asset_has_generation_provenance_notice() -> None:
    root = Path(__file__).resolve().parents[1]
    relative = "assets/new-year-card/new-year-minhwa-background.png"
    notices = (root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    assert (root / relative).is_file()
    assert relative in notices
    assert "GPT 계열 이미지 생성 모델" in notices

def test_package_version_matches_pyproject() -> None:
    """--version 출력(hwpctl.__version__)과 배포 메타데이터 버전이 어긋나지 않게 한다."""
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]
    from hwpctl import __version__
    root = Path(__file__).resolve().parents[1]
    with (root / "pyproject.toml").open("rb") as stream:
        assert __version__ == tomllib.load(stream)["project"]["version"]
