"""한글 없이 ``.hwpx`` 를 다루는 준비 계층.

COM/``hangul.py`` 와 분리한다. 읽기(``hwpx_status`` / ``hwpx_inspect``)는
작성 잠금이 필요 없다. 쓰기 래퍼는 다음 단계에서 공고문 재현에 쓰인다.
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
from hwpctl.hwpx.inspect import inspect_hwpx, inspect_owpml_parts
from hwpctl.hwpx.write import (
    apply_paragraph_align,
    create_table_and_fill,
    insert_paragraph,
    set_run_props,
)

__all__ = [
    "apply_paragraph_align",
    "close_document",
    "compare_page_images",
    "create_table_and_fill",
    "hwpx_available",
    "hwpx_version",
    "insert_paragraph",
    "inspect_hwpx",
    "inspect_owpml_parts",
    "new_document",
    "open_document",
    "require_hwpx",
    "save_document",
    "set_run_props",
]
