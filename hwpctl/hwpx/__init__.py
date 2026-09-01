"""한글 없이 ``.hwpx`` 를 다루는 계층.

COM/``hangul.py`` 와 분리한다. 읽기·쓰기·쪽 비교는 작성 잠금이 필요 없다.
"""

from __future__ import annotations

from hwpctl.hwpx.compare import compare_page_images
from hwpctl.hwpx.document import (
    close_document,
    hwpx_available,
    hwpx_version,
    new_document,
    open_document,
    require_hwpx,
    save_document,
)
from hwpctl.hwpx.gongo import recreate_gongo
from hwpctl.hwpx.inspect import inspect_hwpx, inspect_owpml_parts
from hwpctl.hwpx.write import (
    CREAM_FILL,
    HEADLINE_FONT,
    MYEONGJO_FONT,
    apply_paragraph_align,
    apply_paragraph_format,
    boxed_block,
    cream_section_header,
    create_table_and_fill,
    ensure_declared_font,
    insert_paragraph,
    insert_runs,
    set_run_props,
)

__all__ = [
    "CREAM_FILL",
    "HEADLINE_FONT",
    "MYEONGJO_FONT",
    "apply_paragraph_align",
    "apply_paragraph_format",
    "boxed_block",
    "close_document",
    "compare_page_images",
    "cream_section_header",
    "create_table_and_fill",
    "ensure_declared_font",
    "hwpx_available",
    "hwpx_version",
    "insert_paragraph",
    "insert_runs",
    "inspect_hwpx",
    "inspect_owpml_parts",
    "new_document",
    "open_document",
    "recreate_gongo",
    "require_hwpx",
    "save_document",
    "set_run_props",
]
