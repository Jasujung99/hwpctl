"""Create the one-page HWPX quality fixture without Hancom or LibreOffice."""

from __future__ import annotations

from hwpctl.hwpx.gongo import rebuild_gongo_page1


def main() -> int:
    output = rebuild_gongo_page1()
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
