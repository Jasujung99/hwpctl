"""결정적인 참조 비교 보고서 직렬화 도우미."""

from __future__ import annotations

import json
from typing import Any


def canonical_json(payload: dict[str, Any]) -> str:
    """비교 보고서를 경로·실행 시각 없이 안정적인 JSON으로 직렬화한다."""

    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
