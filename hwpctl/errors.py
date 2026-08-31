"""사용자에게 보여줄 한국어 오류. 스택은 --debug 일 때만."""

from __future__ import annotations


class HwpctlError(Exception):
    """모든 hwpctl 오류의 부모. ``message`` 는 한국어."""

    exit_code = 1

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


class HangulMissingError(HwpctlError):
    """한/글 COM 에 연결할 수 없음."""

    exit_code = 2


class LockBusyError(HwpctlError):
    """다른 클라이언트가 작성 중."""

    exit_code = 3


class DestructiveGuardError(HwpctlError):
    """파괴적 작업에 명시 플래그가 없음."""

    exit_code = 4


class UsageError(HwpctlError):
    """인자·스키마 오류."""

    exit_code = 5


class HangulCommandError(HwpctlError):
    """한/글 액션이 실패함."""

    exit_code = 6