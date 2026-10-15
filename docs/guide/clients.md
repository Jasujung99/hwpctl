# 클라이언트 연결

[← README](../../README.md) · [문서 목록](../README.md)

서버는 같고, 설정만 다릅니다. 한/글 코드를 클라이언트마다 넣지 마세요.

| 클라이언트 | 붙는 방식 | 예제 |
|---|---|---|
| Cursor | MCP stdio | [`examples/cursor/mcp.json`](../../examples/cursor/mcp.json) |
| Codex | MCP stdio | [`examples/codex/config.toml`](../../examples/codex/config.toml) |
| Claude Code | MCP stdio | [`examples/claude-code/.mcp.json`](../../examples/claude-code/.mcp.json) |
| Gemini CLI | MCP stdio | [`examples/gemini/settings.json`](../../examples/gemini/settings.json) |
| Grok Build / 로컬 Grok CLI | MCP stdio | [`examples/grok-build/.mcp.json`](../../examples/grok-build/.mcp.json) |
| 별도 프로세스·원격 클라이언트 | MCP streamable HTTP + 토큰 | [`examples/grok-http/`](../../examples/grok-http) |

stdio 예 (Cursor·Codex·Claude·Gemini·Grok Build 공통):

```json
{
  "mcpServers": {
    "hwpctl": {
      "command": "C:\\hwpctl\\venv\\Scripts\\hwpctl.exe",
      "args": ["mcp"],
      "env": { "HWPCTL_CLIENT": "cursor" }
    }
  }
}
```

`command`에는 [설치](install.md)에서 만든 전용 가상환경의 `hwpctl.exe` **절대 경로**를 씁니다.
`hwpctl`이 PATH에 있으면 이름만 써도 되지만, 클라이언트마다 PATH가 달라 연결이 어긋나기
쉽습니다. 예제 파일의 `"command": "hwpctl"`도 같은 방식으로 바꿔 넣으세요.

- Claude Code는 명령 한 줄로 등록할 수도 있습니다:
  `claude mcp add hwpctl -- C:\hwpctl\venv\Scripts\hwpctl.exe mcp`
- Cursor: 프로젝트 `.cursor/mcp.json` 또는 사용자 MCP 설정에 위 내용을 넣습니다.
- Codex: `~/.codex/config.toml` 에 `examples/codex/config.toml` 을 복사합니다.
- Claude Code: 프로젝트 `.mcp.json` 또는 `claude mcp add`.
- Gemini CLI: `~/.gemini/settings.json` 의 `mcpServers`.
- Grok Build: 프로젝트 `.mcp.json`에 `examples/grok-build/.mcp.json`을 병합합니다.

바꾼 뒤 클라이언트를 재시작하면 같은 `status` / `insert_title` / `create_table` 도구가 보입니다.

## 선택 사항: HTTP 연결

같은 PC에서 명령줄을 실행하는 Grok Build를 포함한 로컬 클라이언트는 위의 stdio
설정을 사용하면 됩니다. HTTP 모드는 별도 프로세스가 필요하거나, 원격 서비스에 대해
사용자가 보안 영향을 검토하고 명시적으로 연결을 구성할 때만 사용하세요. 이 저장소는
외부 공개나 터널을 기본값으로 가정하지 않습니다.

```bat
set HWPCTL_TOKEN=긴무작위문자열
hwpctl mcp --http --host 127.0.0.1 --port 18765 --token %HWPCTL_TOKEN%
```

- MCP 엔드포인트: `http://127.0.0.1:18765/mcp`
- 헤더: `Authorization: Bearer <토큰>` 또는 `X-Hwpctl-Token: <토큰>`
- 토큰 없으면 401. `127.0.0.1` / `localhost` 만 허용합니다.
