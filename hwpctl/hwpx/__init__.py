"""한글 없이 ``.hwpx`` 를 다루는 준비 계층.

COM/``hangul.py`` 와 분리한다. 읽기(``hwpx_status`` / ``hwpx_inspect``)는
작성 잠금이 필요 없다. 쓰기 래퍼는 공고 1쪽 품질 고정물 생성에 쓴다.
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
    apply_paragraph_format,
    append_run,
    create_table_and_fill,
    insert_paragraph,
    set_page_setup,
    set_paragraph_runs,
    set_run_props,
)

__all__ = [
    "apply_paragraph_align",
    "apply_paragraph_format",
    "append_run",
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
    "set_page_setup",
    "set_paragraph_runs",
    "set_run_props",
]
