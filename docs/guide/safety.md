# 안전 장치: 파괴적 작업과 잠금

[← README](../../README.md) · [문서 목록](../README.md)

## 파괴적 작업

아래는 **명시 플래그 없이 거부**합니다.

| 작업 | 플래그 |
|---|---|
| 원본 덮어쓰기 (`save`) | `--overwrite` |
| 다른 기존 파일을 `save_as` 로 덮어쓰기 | `--overwrite` |
| 문서 닫기 (`close`) | `--force` |
| 수정본을 버리고 다른 파일 열기 | `--discard` |
| `save_as` 로 원본과 같은 경로 | 거부 → `save --overwrite` |

큰 범위 삭제, 표·쪽·그림 구조 변경 API 는 넣지 않았습니다. 넣게 되면 같은 방식으로 플래그를 요구합니다.

## 잠금과 Undo

`%LOCALAPPDATA%\hwpctl\hwpctl.lock` (Windows) 또는 `$XDG_RUNTIME_DIR/hwpctl/hwpctl.lock`.  
경로 재정의: `HWPCTL_LOCK`, `HWPCTL_STATE`.  
클라이언트 이름: `HWPCTL_CLIENT` (오류 메시지에 표시).

MCP 서버가 떠 있어도 잠금은 **명령 단위**입니다. 서버 프로세스가 잠금을 붙잡고 있지 않습니다.

`undo` 는 hwpctl 이 기록한 명령만 되돌립니다. hwpctl 명령 사이에 한/글에서 직접
편집했다면 그 편집이 먼저 되돌아갈 수 있으니, 수동 편집은 한/글의 Ctrl+Z 를 쓰세요.
