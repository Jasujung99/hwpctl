"""비공개 참조 문서를 위한 읽기 전용 구조 비교 계층.

이 패키지는 HWPML 문자열만 받는다. COM으로 한/글을 열거나, 원문을 저장하거나,
출력 문서를 생성하지 않는다. 따라서 실제 참조 문서와 HWPML은 호출자가 비공개
저장소에 보관하고, 이 계층에는 합성 픽스처만 넣을 수 있다.
"""

from __future__ import annotations

from hwpctl.reference.capture import ReferenceCapture, capture_hwpml_readonly
from hwpctl.reference.manifest import canonical_json
from hwpctl.reference.model import NormalizedDocument, normalize_hwpml
from hwpctl.reference.structural import compare_hwpml, compare_structure

__all__ = [
    "NormalizedDocument",
    "ReferenceCapture",
    "canonical_json",
    "capture_hwpml_readonly",
    "compare_hwpml",
    "compare_structure",
    "normalize_hwpml",
]
