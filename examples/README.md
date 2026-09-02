# 클라이언트 설정 예제

`cursor/`, `codex/`, `claude-code/`, `gemini/`, `grok-build/`, `grok-http/`는 MCP
클라이언트 설정 예제입니다. `build_new_year_card.py`는 별도의 **Engine 직접 호출** 예제로,
Windows + 한글 2022에서만 실행하며 새 문서와 새 산출물만 만듭니다.

**stdio MCP는 클라이언트마다 별도의 `hwpctl mcp` 프로세스를 시작합니다.** 서로 다른
Claude/Codex/IDE 클라이언트는 OS 작성 잠금으로만
서로를 보호하므로, 한 프로세스를 공유한다고 가정하면 안 됩니다. 여러 클라이언트가
하나의 서버를 공유해야 하면 사용자 검토 후 localhost HTTP 예제를 사용하세요.

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
