#!/usr/bin/env python3
"""한글 없이 공고문 .hwpx 를 조립하고 쪽 비교 산출물을 남긴다.

    pip install -e ".[hwpx]"
    python scripts/recreate_gongo.py
    python scripts/recreate_gongo.py --out artifacts/gongo

한/글 COM 은 쓰지 않는다. 사용자 PC 에서 실물 확인은 나중에
``hwpctl --backend hancom open`` 으로 한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="공고문 HWPX 재현 (한글 불필요)")
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
    args = parser.parse_args(argv)

    from hwpctl.hwpx.compare import compare_page_images
    from hwpctl.hwpx.gongo import ALL_PAGES, recreate_gongo

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    hwpx_path = out_dir / "rebuild_p1_10.hwpx"
    built = recreate_gongo(output=hwpx_path, fixtures=args.fixtures, pages=ALL_PAGES)
    compared = compare_page_images(
        hwpx_path,
        orig_dir=args.fixtures,
        output_dir=out_dir,
        pages=(1, 2, 3),
    )
    payload = {"recreate": built, "compare": compared}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if compared.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
