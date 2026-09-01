"""한/글에서 양면 인쇄용 접이식 신년 카드 양식을 만든다.

새 문서만 열고 기존 문서는 닫거나 저장하지 않는다. 결과는 output/ 아래의
새 .hwpx 파일이며, 같은 이름의 파일이 이미 있으면 덮어쓰지 않고 종료한다.

인쇄: 파일의 1쪽(겉면)과 2쪽(안쪽)을 양면 인쇄한 뒤, 가는 테두리의 바깥선을
따라 자르고 가운데 세로선을 접는다. 프린터마다 뒤집힘 방향이 달라 시험 인쇄
한 장을 먼저 권장한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hwpctl.engine import Engine

ASSET = ROOT / "assets" / "new-year-card" / "new-year-minhwa-background.png"
OUTPUT = ROOT / "output" / "근하신년_접이식_카드_양식-v2.hwpx"

CARD_WIDTH_MM = 138.5
# 빈 문단·표 테두리까지 고려해 190mm 본문 높이보다 충분히 작게 잡는다.
CARD_HEIGHT_MM = 170.0


def call(engine: Engine, command: str, **kwargs: object) -> dict[str, object]:
    result = engine.dispatch(command, **kwargs)
    print(json.dumps({"step": command, "result": result}, ensure_ascii=False))
    return result

def make_card_table(engine: Engine, index: int) -> None:
    call(
        engine,
        "create_table",
        rows=1,
        cols=2,
        header=False,
        cell_margin="0,0",
    )
    call(engine, "set_col_width", widths=[CARD_WIDTH_MM, CARD_WIDTH_MM], table=index)
    call(engine, "set_row_height", height=CARD_HEIGHT_MM, table=index, row=1)
    call(
        engine,
        "set_cell_border",
        table=index,
        cell_range="A1:B1",
        sides="all",
        line_type="Solid",
        width="0.12mm",
        color="#B8AE9E",
    )


def main() -> None:
    if not ASSET.is_file():
        raise SystemExit(f"카드 배경 이미지를 찾지 못했습니다: {ASSET}")
    if OUTPUT.exists():
        raise SystemExit(f"기존 산출물을 덮어쓰지 않습니다: {OUTPUT}")

    engine = Engine(lock_timeout=15.0)

    # new=True 이므로 기존 문서는 버리지 않는다. discard=True 는 새 문서를 만들기 전
    # 활성 문서의 modified 보호 검사를 통과시키는 데만 쓰이며, 닫기/저장은 호출하지 않는다.
    call(engine, "open", new=True, discard=True)
    call(
        engine,
        "set_pagedef",
        paper_width=210.0,
        paper_height=297.0,
        left=10.0,
        right=10.0,
        top=10.0,
        bottom=10.0,
        landscape=True,
        apply="current",
    )

    # 빈 문서에서 미리 쪽을 나눠, 표 안에서 BreakPage를 실행할 위험을 없앤다.
    call(engine, "page", break_page=True)

    # 1쪽: 겉면. 왼쪽은 인사말, 오른쪽은 그림 표지다.
    call(engine, "page", goto=1)
    make_card_table(engine, 0)
    call(
        engine,
        "fill_cells",
        table=0,
        cells={"A1": "근하신년\n새해 복 많이 받으세요"},
    )
    call(
        engine,
        "set_cell_margin",
        table=0,
        cell_range="A1",
        left=12.0,
        right=12.0,
        top=18.0,
        bottom=18.0,
    )
    call(
        engine,
        "set_format",
        table=0,
        cell_range="A1",
        bold=True,
        font="맑은 고딕",
        size=21.0,
        align="center",
        color="#8D241B",
    )
    call(engine, "set_valign", table=0, cell_range="A1", align="center")
    call(engine, "insert_image", path=str(ASSET), table=0, cell="B1", size_option=3)

    # 2쪽: 안쪽. 오른쪽 B1은 수신자가 직접 바꿀 수 있는 메시지 영역이다.
    inside_page = call(engine, "page", goto=2)
    make_card_table(engine, 1)
    call(engine, "insert_image", path=str(ASSET), table=1, cell="A1", size_option=3)
    call(
        engine,
        "fill_cells",
        table=1,
        cells={
            "B1": (
                "[여기에 전하고 싶은 새해 인사를 입력하세요]\n\n"
                "새해에도 건강과 행복이 가득하시길 바랍니다.\n\n"
                "보내는 이  ____________________"
            )
        },
    )
    call(
        engine,
        "set_cell_margin",
        table=1,
        cell_range="B1",
        left=15.0,
        right=15.0,
        top=22.0,
        bottom=22.0,
    )
    call(
        engine,
        "set_format",
        table=1,
        cell_range="B1",
        font="맑은 고딕",
        size=15.0,
        align="center",
        color="#3D342B",
    )
    call(engine, "set_valign", table=1, cell_range="B1", align="center")

    call(engine, "save_as", path=str(OUTPUT))
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(OUTPUT),
                "page_count": inside_page.get("page_count", 2),
                "table_count": 2,
                "open_in_hangul": True,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
