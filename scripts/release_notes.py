"""CHANGELOG.md에서 한 버전의 절만 꺼내 릴리스 노트로 출력한다.

사용: python scripts/release_notes.py 0.1.0
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def section(changelog: str, version: str) -> str:
    pattern = re.compile(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(changelog)
    if match is None:
        raise SystemExit(f"CHANGELOG.md에 [{version}] 절이 없습니다.")
    body = match.group(1).strip()
    if not body:
        raise SystemExit(f"CHANGELOG.md의 [{version}] 절이 비어 있습니다.")
    return body + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: release_notes.py VERSION", file=sys.stderr)
        return 2
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    sys.stdout.write(section(text, argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
