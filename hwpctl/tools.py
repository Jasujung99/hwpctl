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
    ToolSpec("create_table", "표 생성. 첫 행 배경색 가능. Undo 1단위", False, True),
    ToolSpec("fill_cells", "표 셀에 값 채우기. Undo 1단위", False, True),
    ToolSpec("set_format", "선택/문단/행 서식 (글꼴, 크기, 굵게, 정렬, 셀 색)", False, True),
    ToolSpec("replace_selection", "선택 영역을 텍스트로 교체", False, True),
    ToolSpec("undo", "직전 명령을 한/글 Undo 한 덩어리로 되돌리기", False, True),
    ToolSpec("page", "현재 쪽 읽기 또는 --goto 이동", False, False),
    ToolSpec("save_as", "새 경로로 저장. 원본은 덮어쓰지 않음", False, True),
    ToolSpec("save", "원본 경로에 저장. --overwrite 필수. 자동저장 없음", True, True),
    ToolSpec("close", "문서 닫기. --force 필수", True, True),
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