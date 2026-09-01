"""공고문 재현 — fixtures 텍스트를 상속한 서식으로 HWPX 조립.

원본은 ``fixtures/gongo/doc1.hwp`` (바이너리). Linux 에서 검증된
``.hwp``→``.hwpx`` 변환기가 없으면 JSON + 원본 PNG 를 기준으로
처음부터 조립한다. 한/글 COM 은 쓰지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hwpctl.hwpx.document import close_document, new_document, save_document
from hwpctl.hwpx.write import (
    CREAM_FILL,
    GOTHIC_FONT,
    MYEONGJO_FONT,
    TABLE_HEADER_FILL,
    TABLE_LABEL_FILL,
    add_cell_paragraph,
    boxed_block,
    cream_section_header,
    create_table_and_fill,
    drop_leading_empty_paragraph,
    fill_cell_runs,
    insert_paragraph,
    insert_runs,
    set_cell_fill,
    set_page_number_footer,
    set_page_setup,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURES = REPO_ROOT / "fixtures" / "gongo"
CONTENT_WIDTH = 48000  # ~169mm HWPUNIT
STRONG_PAGES = (1, 2, 3)
ALL_PAGES = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 27, 28, 29)

RED = "#FF0000"
BLUE = "#0000FF"


def load_page_texts(fixtures: Path) -> dict[int, str]:
    raw = json.loads((fixtures / "gongo_pages.json").read_text(encoding="utf-8"))
    pages = raw.get("pages") or {}
    return {int(key): str(value) for key, value in pages.items()}


def _plain_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if line:
            lines.append(line)
    return lines


def _build_page1(doc: Any) -> None:
    insert_paragraph(
        doc,
        "「2026년 혁신 소상공인 AI 활용지원 사업」",
        inherit_style=False,
        font=GOTHIC_FONT,
        size=18,
        bold=True,
        align="CENTER",
        line_spacing_percent=140,
        spacing_after_pt=2,
    )
    insert_paragraph(
        doc,
        "참여 소상공인 모집 공고",
        inherit_style=False,
        font=GOTHIC_FONT,
        size=16,
        bold=True,
        align="CENTER",
        line_spacing_percent=140,
        spacing_after_pt=6,
        bottom_border=True,
        border_color="#000000",
        border_width="0.4 mm",
    )
    insert_paragraph(
        doc,
        (
            "중소벤처기업부와 소상공인시장진흥공단은 AI를 활용한 제품개발 및 서비스 도입으로 "
            "소상공인만의 새로운 가치와 차별화된 제품·서비스 창출을 지원하고 있습니다. "
            "「2026년 혁신 소상공인 AI 활용지원 사업」에 참여할 소상공인을 다음과 같이 모집합니다."
        ),
        inherit_style=False,
        font=MYEONGJO_FONT,
        size=11,
        align="JUSTIFY",
        line_spacing_percent=160,
        spacing_before_pt=8,
        spacing_after_pt=10,
    )
    insert_paragraph(
        doc,
        "2026년 6월 12일",
        inherit_style=False,
        font=MYEONGJO_FONT,
        size=11,
        align="RIGHT",
        line_spacing_percent=140,
    )
    insert_paragraph(
        doc,
        "소상공인시장진흥공단 이사장",
        inherit_style=False,
        font=MYEONGJO_FONT,
        size=11,
        bold=True,
        align="RIGHT",
        line_spacing_percent=140,
        spacing_after_pt=6,
        bottom_border=True,
        border_color="#000000",
        border_width="0.4 mm",
    )

    qa_rows: list[list[dict[str, Any]]] = [
        [
            {"text": "❶ 무엇을 지원해주나요?", "font": GOTHIC_FONT, "size": 12, "bold": True},
        ],
        [
            {
                "text": (
                    "☞ 소상공인이 AI를 활용하여 차별화된 제품·서비스를 창출할 수 있도록 "
                    "AI 활용모델부터 비즈니스 모델 구현(사업화 지원)까지 단계별 지원합니다."
                ),
                "font": MYEONGJO_FONT,
                "size": 11,
            }
        ],
        [{"text": "❷ 얼마나 지원해주나요?", "font": GOTHIC_FONT, "size": 12, "bold": True}],
        [
            {
                "text": (
                    "☞ 혁신 소상공인 AI 활용지원 사업은 사업화 자금 최대 4천만원을 지원합니다. "
                    "사업화자금은 정부지원금 80%, 자부담금 20%로 구성됩니다."
                ),
                "font": MYEONGJO_FONT,
                "size": 11,
            }
        ],
        [{"text": "❸ 어떻게 신청하나요?", "font": GOTHIC_FONT, "size": 12, "bold": True}],
        [
            {
                "text": (
                    "☞ 소상공인24 홈페이지(sbiz24.kr)→[지원사업조회 및 신청]→[소진공 공고조회 및 신청]→ "
                    "[2026년 혁신 소상공인 AI활용 지원사업] 검색해서 신청하면 됩니다. "
                    "시스템 접수기간은 2026. 6. 12(금)부터 "
                ),
                "font": MYEONGJO_FONT,
                "size": 11,
            },
            {
                "text": "7. 3(금) 16시까지",
                "font": GOTHIC_FONT,
                "size": 11,
                "bold": True,
                "underline": True,
                "underline_color": RED,
                "color": RED,
            },
            {"text": "입니다.", "font": MYEONGJO_FONT, "size": 11},
        ],
        [{"text": "❹ 궁금한 점이 있어요!", "font": GOTHIC_FONT, "size": 12, "bold": True}],
        [
            {
                "text": "☞ 궁금한 점이 있을 때는 주관기관(p11, 문의처)으로 연락 바랍니다. 문의가 많아 통화가 어려울 수 있으니, 반드시 ",
                "font": MYEONGJO_FONT,
                "size": 11,
            },
            {
                "text": "모집공고를 먼저 확인해주시고",
                "font": MYEONGJO_FONT,
                "size": 11,
                "underline": True,
            },
            {"text": " 문의해주세요.", "font": MYEONGJO_FONT, "size": 11},
        ],
        [
            {
                "text": "❺ AI 활용모델 구축은 어떻게 진행되나요?",
                "font": GOTHIC_FONT,
                "size": 12,
                "bold": True,
            }
        ],
        [
            {
                "text": (
                    "☞ 참여 소상공인이 직접 보유한 아이디어와 사업계획을 중심으로 AI 활용모델을 "
                    "기획·구체화하며, 전문 AI 멘토기업은 멘토링을 통해 AI 적용방안 검토와 실행계획 수립을 지원합니다."
                ),
                "font": MYEONGJO_FONT,
                "size": 11,
            }
        ],
        [{"text": "❻ 시중 AI 솔루션을 활용해도 되나요?", "font": GOTHIC_FONT, "size": 12, "bold": True}],
        [
            {
                "text": (
                    "☞ 단순 구매·구독만을 목적으로 하는 경우 지원취지에 부합하지 않습니다. "
                    "다만, 소상공인이 기획한 AI 활용모델 구현을 위해 필요한 경우에 한하여 활용할 수 있습니다."
                ),
                "font": MYEONGJO_FONT,
                "size": 11,
            }
        ],
    ]
    boxed_block(
        doc,
        "「혁신 소상공인 AI 활용지원 사업」 간단소개",
        qa_rows,
        cream_header=True,
        width=CONTENT_WIDTH,
    )


def _build_page2(doc: Any) -> None:
    cream_section_header(doc, "1", "사업개요", width=CONTENT_WIDTH, page_break_before=True)
    items: list[tuple[str, list[dict[str, Any]]]] = [
        (
            "목적",
            [
                {"text": "□ (목적) ", "font": GOTHIC_FONT, "size": 11, "bold": True},
                {
                    "text": (
                        "인력·자금 등이 부족한 소상공인에게 AI 도입·활용을 지원하여 "
                        "경영 효율화 및 제품·서비스 혁신을 통한 생산성 향상 도모"
                    ),
                    "font": MYEONGJO_FONT,
                    "size": 11,
                },
            ],
        ),
        (
            "지원대상",
            [
                {"text": "□ (지원대상) ", "font": GOTHIC_FONT, "size": 11, "bold": True},
                {
                    "text": "「소상공인기본법」제2조에 따른 소상공인으로 신청일 현재 정상적으로 영업 중인 소상공인",
                    "font": MYEONGJO_FONT,
                    "size": 11,
                },
            ],
        ),
    ]
    for _key, runs in items:
        insert_runs(doc, runs, align="JUSTIFY", line_spacing_percent=160)

    insert_runs(
        doc,
        [
            {"text": "□ (신청기간) ", "font": GOTHIC_FONT, "size": 11, "bold": True},
            {"text": "2026년 6월 12일(금) ~ ", "font": MYEONGJO_FONT, "size": 11},
            {
                "text": "7월 3일(금) 16시까지",
                "font": GOTHIC_FONT,
                "size": 11,
                "bold": True,
                "underline": True,
                "underline_color": RED,
                "color": RED,
            },
        ],
        align="JUSTIFY",
        line_spacing_percent=160,
    )
    insert_runs(
        doc,
        [
            {"text": "□ (사업기간) ", "font": GOTHIC_FONT, "size": 11, "bold": True},
            {"text": "협약 체결일로부터 2026년 12월 31일까지", "font": MYEONGJO_FONT, "size": 11},
        ],
        align="JUSTIFY",
        line_spacing_percent=160,
    )
    insert_runs(
        doc,
        [
            {"text": "□ (신청방법) ", "font": GOTHIC_FONT, "size": 11, "bold": True},
            {"text": "소상공인24 홈페이지 접수 (", "font": MYEONGJO_FONT, "size": 11},
            {
                "text": "www.sbiz24.kr",
                "font": GOTHIC_FONT,
                "size": 11,
                "underline": True,
                "underline_color": BLUE,
                "color": BLUE,
            },
            {"text": ")", "font": MYEONGJO_FONT, "size": 11},
        ],
        align="JUSTIFY",
        line_spacing_percent=160,
    )
    insert_runs(
        doc,
        [
            {"text": "□ (지원규모) ", "font": GOTHIC_FONT, "size": 11, "bold": True},
            {
                "text": "AI 활용모델 구축 1,000개사 선정, 사업화 680개사 선정",
                "font": MYEONGJO_FONT,
                "size": 11,
            },
        ],
        align="JUSTIFY",
        line_spacing_percent=160,
    )
    insert_runs(
        doc,
        [
            {"text": "□ (지원내용) ", "font": GOTHIC_FONT, "size": 11, "bold": True},
            {
                "text": (
                    "소상공인이 AI를 활용하여 차별화된 제품·서비스를 창출할 수 있도록 "
                    "AI 활용모델부터 비즈니스 모델 구현까지 전주기 지원"
                ),
                "font": MYEONGJO_FONT,
                "size": 11,
            },
        ],
        align="JUSTIFY",
        line_spacing_percent=160,
    )
    insert_runs(
        doc,
        [
            {"text": "◦ (활용모델 구축) ", "font": GOTHIC_FONT, "size": 11, "bold": True},
            {
                "text": (
                    "AI 멘토기업과 함께 역량 진단, 원포인트 지원부터 사업 고도화, "
                    "마케팅 등 부문별 AI 활용계획 수립까지 밀착 지원"
                ),
                "font": MYEONGJO_FONT,
                "size": 11,
            },
        ],
        align="JUSTIFY",
        line_spacing_percent=150,
        indent_left_mm=6,
    )
    insert_paragraph(
        doc,
        (
            "* (예시) ① 사업별 워크플로우, KPI 정립 → ② 목적별 로드맵 수립"
            "(데이터 수집, AI 설계·학습, 자동화·고도화 영역 설정) → "
            "③ AI 모델 선택(RAG, 파인튜닝, 맞춤형 에이전트 활용 등)"
        ),
        inherit_style=False,
        font=MYEONGJO_FONT,
        size=9,
        align="JUSTIFY",
        line_spacing_percent=140,
        indent_left_mm=10,
    )
    insert_runs(
        doc,
        [
            {"text": "◦ (BM 구현) ", "font": GOTHIC_FONT, "size": 11, "bold": True},
            {
                "text": "사업장 내 AI 시스템을 구축하고, AI를 활용해 상용시제품 개발, 타겟 마케팅 등 실제 비즈니스 적용까지 지원",
                "font": MYEONGJO_FONT,
                "size": 11,
            },
        ],
        align="JUSTIFY",
        line_spacing_percent=150,
        indent_left_mm=6,
        spacing_after_pt=8,
    )

    table = create_table_and_fill(
        doc,
        4,
        3,
        [
            ["단계", "STEP 1 : AI 활용모델 구축", "STEP 2 : AI 비즈니스 모델 구현"],
            ["목적", "AI 기반 생산성 제고 방안 마련", "차별화된 제품·서비스 창출"],
            ["대상", "(공모) 소상공인 1,000개사", "(선정) 680개사 내외"],
            ["지원내용", "", ""],
        ],
        fills=[
            [TABLE_LABEL_FILL, TABLE_HEADER_FILL, TABLE_HEADER_FILL],
            [TABLE_LABEL_FILL, None, None],
            [TABLE_LABEL_FILL, None, None],
            [TABLE_LABEL_FILL, None, None],
        ],
        col_widths=[1.2, 4.4, 4.4],
        width=CONTENT_WIDTH,
    )
    for col, runs in (
        (
            1,
            [
                {"text": "■ 활용모델 구축 ", "font": GOTHIC_FONT, "size": 10, "bold": True},
                {"text": "[1개월]", "font": GOTHIC_FONT, "size": 10, "bold": True, "color": BLUE},
            ],
        ),
        (
            2,
            [
                {"text": "■ 사업모델 구현 (최대 4천만원) ", "font": GOTHIC_FONT, "size": 10, "bold": True},
                {"text": "[3개월]", "font": GOTHIC_FONT, "size": 10, "bold": True, "color": BLUE},
            ],
        ),
    ):
        fill_cell_runs(doc, table, 3, col, runs, align="LEFT", line_spacing_percent=140)
        add_cell_paragraph(
            doc,
            table,
            3,
            col,
            (
                "- 소상공인 트랙 : AI 역량 진단, 프롬프트 최적화 등 원포인트 컨설팅, AI 로드맵 수립"
                if col == 1
                else "- AI 시스템 : 자동화 비용, AI 튜닝, 솔루션 등 AI 활용 체계 구축"
            ),
            font=MYEONGJO_FONT,
            size=9,
            align="LEFT",
        )
        if col == 2:
            add_cell_paragraph(
                doc,
                table,
                3,
                col,
                "- 비지니스 적용 : 시제품 개발, 타겟마케팅, 공정 최적화 등",
                font=MYEONGJO_FONT,
                size=9,
                align="LEFT",
            )


def _build_page3(doc: Any) -> None:
    cream_section_header(doc, "2", "지원대상", width=CONTENT_WIDTH, page_break_before=True)
    insert_paragraph(
        doc,
        "□ 신청자격",
        inherit_style=False,
        font=GOTHIC_FONT,
        size=12,
        bold=True,
        align="LEFT",
        line_spacing_percent=160,
        spacing_before_pt=8,
    )
    insert_paragraph(
        doc,
        "◦ 「소상공인기본법」제2조에 따른 소상공인으로 신청일 현재 정상적으로 영업 중인 소상공인",
        inherit_style=False,
        font=MYEONGJO_FONT,
        size=11,
        align="JUSTIFY",
        line_spacing_percent=160,
        indent_left_mm=4,
    )
    insert_paragraph(
        doc,
        "- 공동대표가 운영하는 사업체의 경우, 주대표 1인만 신청 가능",
        inherit_style=False,
        font=MYEONGJO_FONT,
        size=11,
        align="JUSTIFY",
        line_spacing_percent=150,
        indent_left_mm=10,
    )
    insert_paragraph(
        doc,
        "* 선정 후 프로그램 활동 시 공동대표 교차 참석 가능하며, 프로그램은 기업단위로 제공",
        inherit_style=False,
        font=MYEONGJO_FONT,
        size=9,
        align="JUSTIFY",
        indent_left_mm=12,
    )
    insert_runs(
        doc,
        [
            {"text": "** 단, 발표평가 시 ", "font": MYEONGJO_FONT, "size": 9},
            {"text": "주대표자 참석 필수", "font": MYEONGJO_FONT, "size": 9, "bold": True},
            {"text": "  ※ ", "font": MYEONGJO_FONT, "size": 9},
            {"text": "공동대표 대참 불가", "font": MYEONGJO_FONT, "size": 9, "bold": True},
        ],
        align="JUSTIFY",
        indent_left_mm=12,
        spacing_after_pt=8,
    )
    insert_paragraph(
        doc,
        "□ 신청제외 대상",
        inherit_style=False,
        font=GOTHIC_FONT,
        size=12,
        bold=True,
        align="LEFT",
        line_spacing_percent=160,
    )

    exclusions: list[list[dict[str, Any]] | str] = [
        [
            {"text": "① 소상공인 정책자금 ", "font": MYEONGJO_FONT, "size": 10},
            {"text": "지원제외 업종", "font": MYEONGJO_FONT, "size": 10, "bold": True},
            {"text": "을 영위하는 경우", "font": MYEONGJO_FONT, "size": 10},
        ],
        "* 지원제외 대상 업종 [참고2] 확인",
        (
            "② 금융기관 등으로부터 채무불이행으로 규제 중이거나 부도, 화의, 법정관리 등 "
            "정상적으로 금융거래가 곤란한 경우"
        ),
        (
            "* 신청마감일까지 신용회복위원회 프리·개인워크아웃 제도에서 채무조정합의서를 체결한 경우, "
            "법원 개인회생제도에서 변제계획인가 받은 경우, 파산면책 선고자, 회생인가를 받은 기업은 신청가능"
        ),
        [
            {
                "text": "** 단, 추후 사업비 신청 시 지급보증보험증권 발급이 불가능한 경우 사업비 지급 불가",
                "font": MYEONGJO_FONT,
                "size": 10,
                "underline": True,
            }
        ],
        "③ 국세 또는 지방세 체납으로 규제중인 경우(법인인 경우, 대표자 포함)",
        (
            "* 단, 신청마감일까지 국세징수법 제105조 1항에 따라 강제징수의 유예를 받은 자 또는 "
            "지방세징수법 제105조 1항에 따라 체납처분의 유예를 받은 자, 국세·지방세 등의 "
            "특수채무 변제 후 증빙이 가능한자는 신청(지원) 가능"
        ),
        "④ 중소벤처기업부 등 정부지원사업 참여 제한 등 제재 조치를 받고 있는 경우",
        "⑤ 신청일 현재 사업자등록이 되어 있지 않거나, ‘휴·폐업’ 중인 경우",
        "⑥ 고용노동부가 공개하는 체불사업주 명단에 포함된 경우",
        (
            "* 사업에 참여하는 기관(참여기업, 공동개발기관 등) 및 기업의 대표자, 과제책임자, "
            "공동책임자가 공고일 기준으로 고용노동부가 공개하는 체불사업주 명단에 포함된 경우"
        ),
        "⑦ 비영리 개인사업자·법인, 단체 또는 조합",
        "⑧ 기타 중소벤처기업부 장관이 참여제한의 사유가 있다고 인정하는 경우",
    ]
    boxed_block(doc, None, exclusions, cream_header=False, width=CONTENT_WIDTH)
    insert_paragraph(
        doc,
        "* 평가·선정 과정에서 신청제외 대상으로 확인될 경우, 탈락 또는 선정취소 될 수 있음",
        inherit_style=False,
        font=MYEONGJO_FONT,
        size=9,
        align="LEFT",
        spacing_before_pt=4,
    )


_SCAFFOLD_HEADERS: dict[int, tuple[str, str]] = {
    4: ("3", "지원내용"),
    5: ("3", "지원내용 (계속)"),
    6: ("3", "지원내용 (계속)"),
    7: ("4", "신청방법"),
    8: ("4", "신청방법 (계속)"),
    9: ("5", "선정절차"),
    10: ("6", "유의사항"),
    27: ("참7", "AI 사업화 주요 사례"),
    28: ("참8", "제3자 부당개입 주의 안내"),
    29: ("참9", "개인정보 수집·이용 안내"),
}


def _build_scaffold_page(doc: Any, page: int, text: str) -> None:
    number, title = _SCAFFOLD_HEADERS.get(page, (str(page), f"{page}쪽"))
    cream_section_header(doc, number, title, width=CONTENT_WIDTH, page_break_before=True)
    insert_paragraph(
        doc,
        f"[재현 골격] 원본 {page}쪽. 1–3쪽과 같은 크림 헤더·본문 서식을 상속한다. "
        "표·도식의 세부는 다음 반복에서 맞춘다.",
        inherit_style=False,
        font=GOTHIC_FONT,
        size=9,
        color="#666666",
        align="LEFT",
        spacing_after_pt=6,
    )
    for line in _plain_lines(text)[:28]:
        insert_paragraph(
            doc,
            line,
            inherit_style=False,
            font=MYEONGJO_FONT,
            size=10,
            align="JUSTIFY",
            line_spacing_percent=150,
            spacing_after_pt=2,
        )


def recreate_gongo(
    *,
    output: str | Path,
    fixtures: str | Path | None = None,
    pages: tuple[int, ...] = ALL_PAGES,
) -> dict[str, Any]:
    """공고문 1–10·27–29쪽을 ``.hwpx`` 로 조립하고 경로를 돌려준다."""

    fixtures_dir = Path(fixtures or DEFAULT_FIXTURES)
    if not (fixtures_dir / "gongo_pages.json").is_file():
        raise FileNotFoundError(f"fixtures 를 찾을 수 없습니다: {fixtures_dir}")
    texts = load_page_texts(fixtures_dir)
    dest = Path(output)
    dest.parent.mkdir(parents=True, exist_ok=True)

    doc = new_document()
    try:
        set_page_setup(doc)
        set_page_number_footer(doc)
        wanted = tuple(pages)
        if 1 in wanted:
            _build_page1(doc)
        if 2 in wanted:
            _build_page2(doc)
        if 3 in wanted:
            _build_page3(doc)
        for page in wanted:
            if page in STRONG_PAGES:
                continue
            _build_scaffold_page(doc, page, texts.get(page, ""))
        drop_leading_empty_paragraph(doc)
        save_document(doc, dest)
    finally:
        close_document(doc)

    return {
        "ok": True,
        "path": str(dest),
        "pages": list(wanted),
        "strong_pages": [p for p in wanted if p in STRONG_PAGES],
        "scaffold_pages": [p for p in wanted if p not in STRONG_PAGES],
        "fixtures": str(fixtures_dir),
        "backend": "hwpx",
        "hangul_required": False,
        "conversion": (
            "바이너리 .hwp → .hwpx 변환은 이 환경에서 쓰지 않았습니다. "
            "gongo_pages.json 과 orig_p1–p3.png 를 기준으로 처음부터 조립했습니다."
        ),
    }
