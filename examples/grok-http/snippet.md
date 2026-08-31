# 일반 HTTP 클라이언트

`hwpctl` HTTP는 기본적으로 **이 Windows PC의 localhost**에만 붙습니다. 같은 PC에서
명령줄을 실행하는 Grok Build 등은 HTTP 대신 stdio 예제를 사용하세요. 외부 서비스가
필요하다면 사용자가 인증·네트워크 노출·문서 접근 위험을 검토하고 별도로 연결해야
합니다. 이 예제는 외부 공개나 터널을 구성하지 않습니다.

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

도구 이름은 CLI 와 같습니다: `status`, `snapshot`, `insert_title`, `create_table`,
`set_cell_margin`, `insert_chart`, `save_as` …

원본을 덮어쓰지 말고 `save_as` 로 새 경로에 저장하세요.
