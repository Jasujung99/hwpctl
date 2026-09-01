"""2026년 혁신 소상공인 AI 활용지원 공고 1쪽 HWPX 재구성.

이 모듈은 이미지 한 장을 붙이는 재현기가 아니다. 글꼴, 부분 런, 문단 모양,
실제 표 셀/테두리/채움을 python-hwpx의 공개 API로 작성하는 품질 고정물이다.
2쪽 이후는 의도적으로 만들지 않는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from hwpctl.hwpx.document import close_document, new_document, save_document
from hwpctl.hwpx.write import (
    HWPUNIT_PER_MM,
    apply_paragraph_format,
    create_table_and_fill,
    insert_paragraph,
    set_paragraph_runs,
    set_run_props,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GONGO_PAGE1_OUTPUT = REPO_ROOT / "artifacts" / "gongo" / "rebuild_p1.hwpx"

MYEONGJO_FONT = "휴먼명조"
HEADLINE_FONT = "HY헤드라인M"
CREAM = "#FCF5E7"
RED = "#FF0000"
TABLE_BORDER = "#777777"


def _set_paragraph(
    document: Any,
    text: str,
    *,
    font: str,
    size: float,
    bold: bool = False,
    alignment: str = "LEFT",
    line_spacing_percent: float = 140,
    spacing_before_pt: float | None = None,
    spacing_after_pt: float | None = None,
) -> Any:
    paragraph = insert_paragraph(document, text, inherit_style=False)
    set_run_props(
        document,
        paragraph=paragraph,
        font=font,
        size=size,
        bold=bold,
    )
    apply_paragraph_format(
        document,
        paragraph=paragraph,
        alignment=alignment,
        line_spacing_percent=line_spacing_percent,
        spacing_before_pt=spacing_before_pt,
        spacing_after_pt=spacing_after_pt,
    )
    return paragraph


def _add_rule(
    document: Any,
    *,
    spacing_before_pt: float,
    spacing_after_pt: float,
) -> None:
    paragraph = insert_paragraph(document, " ", inherit_style=False)
    set_run_props(
        document,
        paragraph=paragraph,
        font=MYEONGJO_FONT,
        size=1,
    )
    apply_paragraph_format(
        document,
        paragraph=paragraph,
        alignment="LEFT",
        line_spacing_percent=100,
        spacing_before_pt=spacing_before_pt,
        spacing_after_pt=spacing_after_pt,
        bottom_border=True,
        border_color="#000000",
        border_width="0.12 mm",
    )


def _set_cell_paragraph(
    document: Any,
    paragraph: Any,
    runs: Sequence[Mapping[str, Any]],
    *,
    line_spacing_percent: float,
    spacing_before_pt: float | None = None,
    spacing_after_pt: float | None = None,
) -> None:
    set_paragraph_runs(document, runs, paragraph=paragraph)
    apply_paragraph_format(
        document,
        paragraph=paragraph,
        alignment="LEFT",
        line_spacing_percent=line_spacing_percent,
        spacing_before_pt=spacing_before_pt,
        spacing_after_pt=spacing_after_pt,
    )


def _add_cell_paragraph(
    document: Any,
    cell: Any,
    runs: Sequence[Mapping[str, Any]],
    *,
    line_spacing_percent: float,
    spacing_before_pt: float | None = None,
    spacing_after_pt: float | None = None,
) -> None:
    paragraph = cell.add_paragraph("")
    _set_cell_paragraph(
        document,
        paragraph,
        runs,
        line_spacing_percent=line_spacing_percent,
        spacing_before_pt=spacing_before_pt,
        spacing_after_pt=spacing_after_pt,
    )


def _label(text: str) -> list[dict[str, Any]]:
    return [{"text": text, "font": HEADLINE_FONT, "size": 12, "bold": True}]


def _body(text: str) -> list[dict[str, Any]]:
    return [{"text": text, "font": MYEONGJO_FONT, "size": 10.5}]


def build_gongo_page1(document: Any) -> None:
    """Fill *document* with just the styled first page of the notice."""

    document.page.setup(
        paper_size="A4",
        orientation="PORTRAIT",
        margin_left_mm=20,
        margin_right_mm=20,
        margin_top_mm=22,
        margin_bottom_mm=15,
        header_margin_mm=12,
        footer_margin_mm=12,
    )

    # The blank skeleton paragraph carries secPr in its first run. Keep that
    # control untouched and reuse its separate empty text run for the title.
    title = document.paragraphs[0]
    title_run_index = len(title.runs) - 1
    title.runs[title_run_index].text = "「2026년 혁신 소상공인 AI 활용지원 사업」"
    set_run_props(
        document,
        paragraph=title,
        run_index=title_run_index,
        font=HEADLINE_FONT,
        size=20,
        bold=True,
    )
    apply_paragraph_format(
        document,
        paragraph=title,
        alignment="CENTER",
        line_spacing_percent=140,
    )
    _set_paragraph(
        document,
        "참여 소상공인 모집 공고",
        font=HEADLINE_FONT,
        size=20,
        bold=True,
        alignment="CENTER",
        line_spacing_percent=140,
        spacing_after_pt=10,
    )

    _add_rule(document, spacing_before_pt=5, spacing_after_pt=3)
    _set_paragraph(
        document,
        "중소벤처기업부와 소상공인시장진흥공단은 AI를 활용한 제품개발 및 서비스 도입으로 "
        "소상공인만의 새로운 가치와 차별화된 제품·서비스 창출을 지원하고 있습니다. "
        "「2026년 혁신 소상공인 AI 활용지원 사업」에 참여할 소상공인을 다음과 같이 모집합니다.",
        font=MYEONGJO_FONT,
        size=11.5,
        alignment="JUSTIFY",
        line_spacing_percent=160,
        spacing_after_pt=4,
    )
    _set_paragraph(
        document,
        "2026년 6월 12일",
        font=MYEONGJO_FONT,
        size=11,
        alignment="RIGHT",
        line_spacing_percent=120,
    )
    _set_paragraph(
        document,
        "소상공인시장진흥공단 이사장",
        font=MYEONGJO_FONT,
        size=11,
        alignment="RIGHT",
        line_spacing_percent=120,
        spacing_after_pt=5,
    )
    _add_rule(document, spacing_before_pt=1, spacing_after_pt=6)

    # A two-column first row reproduces the short cream heading. The second
    # row is a real merged table cell, giving the explanation box one border
    # without accidental rules between the six Q&A blocks.
    table = create_table_and_fill(
        document,
        2,
        2,
        header_fill=CREAM,
        header_columns=(0,),
        width_mm=168,
        height_mm=163,
        column_widths_mm=(136, 32),
        border_color=TABLE_BORDER,
        border_width="0.12 mm",
    )
    header_height = round(11.5 * HWPUNIT_PER_MM)
    table.cell(0, 0).set_size(height=header_height)
    table.cell(0, 1).set_size(height=header_height)
    body_cell = table.merge_cells(1, 0, 1, 1)
    body_cell.set_size(height=round(151.5 * HWPUNIT_PER_MM))

    _set_cell_paragraph(
        document,
        table.cell(0, 0).paragraphs[0],
        _label("「혁신 소상공인 AI 활용지원 사업」  간단소개"),
        line_spacing_percent=120,
    )

    body_paragraph = body_cell.paragraphs[0]
    _set_cell_paragraph(
        document,
        body_paragraph,
        _label("❶ 무엇을 지원해주나요?"),
        line_spacing_percent=120,
        spacing_after_pt=1.5,
    )
    _add_cell_paragraph(
        document,
        body_cell,
        _body(
            "☞ 소상공인이 AI를 활용하여 차별화된 제품·서비스를 창출할 수 있도록 "
            "AI 활용모델부터 비즈니스 모델 구현(사업화 지원)까지 단계별 지원합니다."
        ),
        line_spacing_percent=135,
        spacing_after_pt=3,
    )
    _add_cell_paragraph(
        document,
        body_cell,
        _label("❷ 얼마나 지원해주나요?"),
        line_spacing_percent=120,
        spacing_before_pt=1,
        spacing_after_pt=1.5,
    )
    _add_cell_paragraph(
        document,
        body_cell,
        _body(
            "☞ 혁신 소상공인 AI 활용지원 사업은 사업화 자금 최대 4천만원을 지원합니다. "
            "사업화자금은 정부지원금 80%, 자부담금 20%로 구성됩니다."
        ),
        line_spacing_percent=135,
        spacing_after_pt=3,
    )
    _add_cell_paragraph(
        document,
        body_cell,
        _label("❸ 어떻게 신청하나요?"),
        line_spacing_percent=120,
        spacing_before_pt=1,
        spacing_after_pt=1.5,
    )
    _add_cell_paragraph(
        document,
        body_cell,
        [
            {
                "text": (
                    "☞ 소상공인24 홈페이지(sbiz24.kr)→[지원사업조회 및 신청]→"
                    "[소진공 공고조회 및 신청]→ [2026년 혁신 소상공인 AI활용 지원사업] "
                    "검색해서 신청하면 됩니다. 시스템 접수기간은 2026. 6. 12(금)부터 "
                ),
                "font": MYEONGJO_FONT,
                "size": 10.5,
            },
            {
                "text": "7. 3(금) 16시까지",
                "font": MYEONGJO_FONT,
                "size": 10.5,
                "color": RED,
                "underline": True,
                "underline_color": RED,
                "underline_shape": "SOLID",
            },
            {"text": "입니다.", "font": MYEONGJO_FONT, "size": 10.5},
        ],
        line_spacing_percent=135,
        spacing_after_pt=3,
    )
    _add_cell_paragraph(
        document,
        body_cell,
        _label("❹ 궁금한 점이 있어요!"),
        line_spacing_percent=120,
        spacing_before_pt=1,
        spacing_after_pt=1.5,
    )
    _add_cell_paragraph(
        document,
        body_cell,
        _body(
            "☞ 궁금한 점이 있을 때는 주관기관(p11, 문의처)으로 연락 바랍니다. 문의가 많아 "
            "통화가 어려울 수 있으니, 반드시 모집공고를 먼저 확인해주시고 문의해주세요."
        ),
        line_spacing_percent=135,
        spacing_after_pt=3,
    )
    _add_cell_paragraph(
        document,
        body_cell,
        _label("❺ AI 활용모델 구축은 어떻게 진행되나요?"),
        line_spacing_percent=120,
        spacing_before_pt=1,
        spacing_after_pt=1.5,
    )
    _add_cell_paragraph(
        document,
        body_cell,
        _body(
            "☞ 참여 소상공인이 직접 보유한 아이디어와 사업계획을 중심으로 AI 활용모델을 "
            "기획·구체화하며, 전문 AI 멘토기업은 멘토링을 통해 AI 적용방안 검토와 "
            "실행계획 수립을 지원합니다."
        ),
        line_spacing_percent=135,
        spacing_after_pt=3,
    )
    _add_cell_paragraph(
        document,
        body_cell,
        _label("❻ 시중 AI 솔루션을 활용해도 되나요?"),
        line_spacing_percent=120,
        spacing_before_pt=1,
        spacing_after_pt=1.5,
    )
    _add_cell_paragraph(
        document,
        body_cell,
        _body(
            "☞ 단순 구매·구독만을 목적으로 하는 경우 지원취지에 부합하지 않습니다. 다만, "
            "소상공인이 기획한 AI 활용모델 구현을 위해 필요한 경우에 한하여 활용할 수 있습니다."
        ),
        line_spacing_percent=135,
    )

    _set_paragraph(
        document,
        "- 1 -",
        font=MYEONGJO_FONT,
        size=9,
        alignment="CENTER",
        line_spacing_percent=100,
        spacing_before_pt=4,
    )


def rebuild_gongo_page1(path: str | Path = DEFAULT_GONGO_PAGE1_OUTPUT) -> Path:
    """Create the one-page quality fixture and return its saved path."""

    output = Path(path)
    document = new_document()
    try:
        build_gongo_page1(document)
        save_document(document, output)
    finally:
        close_document(document)
    return output
