"""Validate public docs and MCP client examples without starting Hangul."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 CI installs tomli.
    import tomli as tomllib  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
TEXT_NAMES = {".gitignore"}
TEXT_SUFFIXES = {".md", ".json", ".toml", ".yml", ".yaml"}
IGNORED_DIRS = {".git", ".venv", "venv", "build", "dist", ".pytest_cache", "__pycache__"}
PRIVATE_PATTERNS = {
    "Windows 사용자 절대 경로": re.compile(r"(?i)[A-Z]:\\Users\\[^\\\s]+"),
    "개인 PC 이름": re.compile(r"(?i)DESKTOP-[A-Z0-9]{5,}"),
    "OpenAI 형식 비밀키": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    "GitHub 형식 토큰": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"),
}
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def public_text_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        relative_parts = path.relative_to(ROOT).parts
        if (
            not path.is_file()
            or any(part in IGNORED_DIRS or part.endswith(".egg-info") for part in relative_parts)
        ):
            continue
        if path.name in TEXT_NAMES or path.suffix.lower() in TEXT_SUFFIXES:
            files.append(path)
    return files


def validate_configs(errors: list[str]) -> tuple[int, int]:
    json_files = sorted((ROOT / "examples").rglob("*.json"))
    toml_files = sorted((ROOT / "examples").rglob("*.toml")) + [ROOT / "pyproject.toml"]
    for path in json_files:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - report all malformed public examples.
            errors.append(f"invalid JSON: {path.relative_to(ROOT)}: {exc}")
    for path in toml_files:
        try:
            tomllib.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - report all malformed public examples.
            errors.append(f"invalid TOML: {path.relative_to(ROOT)}: {exc}")
    return len(json_files), len(toml_files)


def validate_private_literals(files: list[Path], errors: list[str]) -> None:
    for path in files:
        text = path.read_text(encoding="utf-8")
        for label, pattern in PRIVATE_PATTERNS.items():
            if match := pattern.search(text):
                line = text.count("\n", 0, match.start()) + 1
                errors.append(f"{label}: {path.relative_to(ROOT)}:{line}")


def validate_markdown(files: list[Path], errors: list[str]) -> int:
    markdown_files = [path for path in files if path.suffix.lower() == ".md"]
    for path in markdown_files:
        text = path.read_text(encoding="utf-8")
        mermaid_count = text.count("```mermaid")
        closed_mermaid_count = len(re.findall(r"```mermaid\s+.*?```", text, re.DOTALL))
        if mermaid_count != closed_mermaid_count:
            errors.append(f"unclosed Mermaid block: {path.relative_to(ROOT)}")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or target.startswith("#"):
                continue
            relative = parsed.path.replace("%20", " ")
            if relative and not (path.parent / relative).resolve().exists():
                errors.append(
                    f"missing local link: {path.relative_to(ROOT)} -> {raw_target}"
                )
    return len(markdown_files)


def main() -> int:
    errors: list[str] = []
    files = public_text_files()
    json_count, toml_count = validate_configs(errors)
    validate_private_literals(files, errors)
    markdown_count = validate_markdown(files, errors)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        f"validated {json_count} JSON, {toml_count} TOML, "
        f"and {markdown_count} Markdown files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
