# Grok Bot / 일반 HTTP 클라이언트

Grok Bot 은 원격입니다. `hwpctl` HTTP 는 **이 Windows PC의 localhost** 에만 붙습니다.  
봇이 바로 도달한다고 가정하지 마세요. 나중에 SSH 터널이나 Cloudflare Tunnel 로 노출하는 것은 사용자 몫입니다.

## 로컬에서 서버 켜기

```bat
set HWPCTL_TOKEN=여기에-긴-무작위-토큰
hwpctl mcp --http --host 127.0.0.1 --port 18765 --token %HWPCTL_TOKEN%
```

- MCP (streamable HTTP): `http://127.0.0.1:18765/mcp`
- 상태: `http://127.0.0.1:18765/health` (토큰 없음)
- 인증: `Authorization: Bearer %HWPCTL_TOKEN%` 또는 `X-Hwpctl-Token: %HWPCTL_TOKEN%`

토큰이 없거나 localhost 가 아니면 서버가 뜨지 않습니다.

## 클라이언트 쪽 스케치

```http
POST /mcp HTTP/1.1
Host: 127.0.0.1:18765
Authorization: Bearer 여기에-긴-무작위-토큰
Accept: application/json, text/event-stream
Content-Type: application/json
```

도구 이름은 CLI 와 같습니다: `status`, `snapshot`, `insert_title`, `create_table`, `save_as` …

원본을 덮어쓰지 말고 `save_as` 로 새 경로에 저장하세요.