"""비공개 HWP 참조본을 수정 없이 메모리 HWPML로 읽는 Windows 보조기.

이 코드는 문서 작성 API가 아니다. 실제 원문/HWPML은 호출자가 비공개 위치에
보관하고, 이 함수가 돌려주는 HWPML도 디스크에 쓰지 않는 것이 원칙이다.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ReferenceCapture:
    """원문을 노출하지 않는 읽기 전용 캡처의 증적과 메모리 HWPML."""

    hwpml: str
    sha256_before: str
    sha256_after: str
    bytes: int
    com_page_count: int

    @property
    def source_unchanged(self) -> bool:
        return self.sha256_before == self.sha256_after

    def manifest_entry(self, reference_id: str) -> dict[str, Any]:
        """경로·원문을 제외한 비공개 manifest용 증적을 돌려준다."""

        return {
            "reference_id": reference_id,
            "sha256_before": self.sha256_before,
            "sha256_after": self.sha256_after,
            "bytes": self.bytes,
            "com_page_count": self.com_page_count,
            "source_unchanged": self.source_unchanged,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _default_dispatch(prog_id: str) -> Any:
    try:
        import win32com.client  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise RuntimeError("읽기 전용 HWP 캡처에는 Windows COM(pywin32)이 필요합니다.") from exc
    return win32com.client.DispatchEx(prog_id)


def _safe_close(app: Any) -> None:
    try:
        app.XHwpDocuments.Close(False)
    finally:
        app.Quit()


def capture_hwpml_readonly(
    source: str | Path,
    *,
    _dispatch: Callable[[str], Any] | None = None,
) -> ReferenceCapture:
    """HWP를 별도 한/글 인스턴스에서 ``readonly:true``로 열어 HWPML을 읽는다.

    원본의 SHA-256을 열기 전후로 검사하며, 값이 달라지면 호출자에게 HWPML을
    건네지 않고 즉시 실패한다. 이 함수는 ``Save``/``SaveAs``를 호출하지 않는다.
    ``_dispatch``는 COM 없는 단위 테스트를 위한 주입 지점이다.
    """

    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"참조 문서를 찾을 수 없습니다: {path}")

    before = _sha256(path)
    dispatch = _dispatch or _default_dispatch
    app = None
    hwpml = ""
    com_page_count = 0
    try:
        app = dispatch("HWPFrame.HwpObject")
        app.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        if not app.Open(str(path), "HWP", "readonly:true"):
            raise RuntimeError("한/글이 참조 문서를 읽기 전용으로 열지 못했습니다.")
        hwpml = str(app.GetTextFile("HWPML2X", ""))
        # 이 값은 headless COM 세션의 즉시 상태일 뿐, PDF의 물리 렌더 쪽수는
        # 아니다. 최종 시각 검증은 PDF 페이지 트리/pdfinfo를 기준으로 한다.
        com_page_count = int(app.PageCount)
    finally:
        if app is not None:
            _safe_close(app)

    after = _sha256(path)
    if before != after:
        raise RuntimeError("읽기 전용 캡처 뒤 원본 SHA-256이 달라졌습니다. 작업을 중단합니다.")
    return ReferenceCapture(
        hwpml=hwpml,
        sha256_before=before,
        sha256_after=after,
        bytes=path.stat().st_size,
        com_page_count=com_page_count,
    )


__all__ = ["ReferenceCapture", "capture_hwpml_readonly"]
