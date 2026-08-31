# 클라이언트 설정 예제

한/글 코드는 여기 없습니다. 모두 같은 `hwpctl mcp` 프로세스를 가리킵니다.

| 폴더 | 넣을 위치 |
|---|---|
| `cursor/mcp.json` | 프로젝트 `.cursor/mcp.json` 또는 Cursor 사용자 MCP |
| `codex/config.toml` | `~/.codex/config.toml` |
| `claude-code/.mcp.json` | 프로젝트 `.mcp.json` |
| `gemini/settings.json` | `~/.gemini/settings.json` |
| `grok-build/.mcp.json` | Grok Build 등 로컬 명령줄 클라이언트의 프로젝트 `.mcp.json` |
| `grok-http/snippet.md` | 별도 프로세스·원격 클라이언트용 localhost 토큰 서버 |

클라이언트를 바꿀 때 이 파일만 복사하고, `hwpctl` 설치는 그대로 둡니다.

Grok Build처럼 이 PC에서 실행되는 클라이언트는 `grok-build/.mcp.json`의 stdio
설정을 사용합니다. HTTP 예제는 원격 연결이 명시적으로 필요할 때만 사용하세요.
