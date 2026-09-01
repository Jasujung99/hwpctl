"""CLI 와 MCP 가 공유하는 고수준 도구 목록.

모델이 「사업계획서, 4열 8행 표, 첫 행 회색」을 두세 번의 호출로 매핑하도록
도구를 작게 유지한다. 한/글 전용 로직은 여기 없고 엔진에만 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    name: str
    summary: str
    destructive: bool
    write: bool


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec("status", "열린 한/글 창·문서 경로·수정 여부·버전", False, False),
    ToolSpec("open", "새 문서 또는 경로로 열기. 수정본이 있으면 --discard 필요", False, True),
    ToolSpec("snapshot", "제목·본문·표·선택 영역을 읽기", False, False),
    ToolSpec("insert_title", "제목 문단 삽입 (가운데, 굵게, 큰 글씨). Undo 1단위", False, True),
    ToolSpec("insert_paragraph", "본문 문단 삽입. Undo 1단위", False, True),
    ToolSpec("create_table", "표 생성. 첫 행 배경색·기본 칸 안여백(3.5/2.0mm). Undo 1단위", False, True),
    ToolSpec("fill_cells", "표 셀에 값 채우기. Undo 1단위", False, True),
    ToolSpec(
        "layout_review",
        "표를 채운 뒤 항상 호출: 줄바꿈·행 높이·본문 폭·쪽 수 검토 및 수정",
        False,
        True,
    ),
    ToolSpec("set_cell_margin", "표 칸 안쪽 여백(mm). 표 전체·범위·현재 셀", False, True),
    ToolSpec("set_col_width", "표 열 너비를 mm 또는 비율로 지정. Undo 1단위", False, True),
    ToolSpec("get_col_width", "현재 열 또는 지정 표의 열 너비(mm) 읽기", False, False),
    ToolSpec("set_row_height", "현재 행 또는 지정 행 높이(mm). Undo 1단위", False, True),
    ToolSpec("get_row_height", "현재 행 또는 지정 행 높이(mm) 읽기", False, False),
    ToolSpec("merge_cells", "셀블록 범위를 합치기. Undo 1단위", False, True),
    ToolSpec("set_valign", "셀 세로 정렬(top/center/bottom). Undo 1단위", False, True),
    ToolSpec("set_cell_border", "셀 테두리(CellBorderFill). TypeHorz 미지원", False, True),
    ToolSpec("insert_chart", "선택한 표 데이터로 한/글 네이티브 차트 삽입 (PNG 아님)", False, True),
    ToolSpec("set_format", "선택/문단/행 서식 (글꼴, 크기, 굵게, 정렬, 셀 색)", False, True),
    ToolSpec("set_style", "현재 문단에 문서 스타일 적용. Undo 1단위", False, True),
    ToolSpec("replace_selection", "선택 영역을 텍스트로 교체", False, True),
    ToolSpec("undo", "직전 명령을 한/글 Undo 한 덩어리로 되돌리기", False, True),
    ToolSpec("page", "현재 쪽 읽기, --goto 이동, --break 쪽 나누기", False, True),
    ToolSpec("set_pagedef", "용지 크기·여백·가로/세로 지정. Undo 1단위", False, True),
    ToolSpec("save_as", "새 경로로 저장. 원본은 덮어쓰지 않음", False, True),
    ToolSpec("save", "원본 경로에 저장. --overwrite 필수. 자동저장 없음", True, True),
    ToolSpec("close", "문서 닫기. --force 필수", True, True),
    ToolSpec(
        "hwpx_status",
        "python-hwpx 설치 여부와 .hwpx 요약. 한글·COM·잠금 불필요",
        False,
        False,
    ),
    ToolSpec(
        "hwpx_inspect",
        ".hwpx 문단·런·셀 서식 그룹 읽기(상속용). 한글·COM·잠금 불필요",
        False,
        False,
    ),
)


def tool_names() -> list[str]:
    return [t.name for t in TOOLS]


def tool_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "summary": t.summary,
            "destructive": t.destructive,
            "write": t.write,
        }
        for t in TOOLS
    ]