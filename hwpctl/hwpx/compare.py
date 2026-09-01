"""쪽 이미지 비교 훅. 이 준비 PR 에서는 구현하지 않는다.

다음 단계에서 원본·재현본을 렌더(한/글 ``hwpctl open`` 또는 비-Hancom
렌더러)해 쪽 단위로 대조할 자리이다.
"""

from __future__ import annotations

from typing import Any


def compare_page_images(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    raise NotImplementedError(
        "쪽 이미지 비교는 아직 구현되지 않았습니다. "
        "준비 단계에서는 hwpx_inspect 로 서식 그룹만 읽고, "
        "시각 대조는 다음 단계에서 붙입니다."
    )
