#!/usr/bin/env python3
"""한글 없이 공고문 1쪽 .hwpx 를 조립하고 inspect 기준 비교 산출물을 남긴다.

    pip install -e ".[hwpx]"
    python scripts/recreate_gongo.py
    python scripts/recreate_gongo.py --out artifacts/gongo
    python scripts/recreate_gongo.py --pages 1,2,3

한/글 COM 은 쓰지 않는다. 품질은 hwpx_inspect(OWPML) 로 재고,
Pillow 비교 시트는 참고용이다. 4쪽 이후는 이 스크립트가 만들지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_pages(raw: str) -> tuple[int, ...]:
    pages = tuple(int(part.strip()) for part in raw.split(",") if part.strip())
    if not pages:
        raise SystemExit("--pages 에 쪽 번호가 없습니다.")
    if any(page >= 4 for page in pages):
        raise SystemExit("이 품질 패스는 4쪽 이후를 조립하지 않습니다. 1–3쪽만 지정하세요.")
    return pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="공고문 HWPX 1쪽 품질 재현 (한글 불필요)")
    parser.add_argument(
        "--out",
        default=str(ROOT / "artifacts" / "gongo"),
        help="산출물 디렉터리",
    )
    parser.add_argument(
        "--fixtures",
        default=str(ROOT / "fixtures" / "gongo"),
        help="gongo_pages.json · orig_p*.png 위치",
    )
    parser.add_argument(
        "--pages",
        default="1",
        help="조립할 쪽. 기본 1. 선택적으로 1,2,3",
    )
    args = parser.parse_args(argv)
    pages = _parse_pages(args.pages)

    from hwpctl.hwpx.compare import compare_page_images
    from hwpctl.hwpx.gongo import recreate_gongo

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = "rebuild_p1.hwpx" if pages == (1,) else f"rebuild_p{pages[0]}_{pages[-1]}.hwpx"
    hwpx_path = out_dir / name
    built = recreate_gongo(output=hwpx_path, fixtures=args.fixtures, pages=pages)
    compare_pages = tuple(page for page in pages if page <= 3)
    compared = compare_page_images(
        hwpx_path,
        orig_dir=args.fixtures,
        output_dir=out_dir,
        pages=compare_pages,
    )
    payload = {"recreate": built, "compare": compared}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if compared.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
