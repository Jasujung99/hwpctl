"""비공개 참조 문서를 위한 읽기 전용 구조 비교 계층.

정규화·비교 함수는 HWPML 문자열만 받으며 COM을 사용하지 않는다.
별도 ``capture_hwpml_readonly``는 Windows에서 격리된 COM으로 참조를 읽고
원본 해시 보존을 확인한다. 실제 참조 문서와 HWPML은 호출자가 비공개로
보관하고, 이 패키지의 공개 테스트에는 합성 픽스처만 넣는다.
"""

from __future__ import annotations

from hwpctl.reference.capture import ReferenceCapture, capture_hwpml_readonly
from hwpctl.reference.manifest import canonical_json
from hwpctl.reference.export import export_hwpml_readonly, export_pdf_readonly, export_reference_bundle_readonly
from hwpctl.reference.analysis import ReferenceAnalysis, analyze_hwpml
from hwpctl.reference.grid import GridEvidence, solve_grid_tracks
from hwpctl.reference.model import NormalizedDocument, normalize_hwpml
from hwpctl.reference.structural import compare_hwpml, compare_structure

__all__ = [
    "ReferenceAnalysis",
    "analyze_hwpml",
    "GridEvidence",
    "solve_grid_tracks",
    "export_reference_bundle_readonly",
    "export_hwpml_readonly",
    "export_pdf_readonly",
    "NormalizedDocument",
    "ReferenceCapture",
    "canonical_json",
    "capture_hwpml_readonly",
    "compare_hwpml",
    "compare_structure",
    "normalize_hwpml",
]
