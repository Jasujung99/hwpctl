# hwpctl — 한/글 라이브 코파일럿 브리지

열린 **한글 2022** 창을 채팅 클라이언트가 고치게 하는 **단일 작성기**입니다.  
Grok Bot, Cursor, Codex, Gemini CLI, Claude Code 는 설정을 갈아끼우기만 하면 됩니다.  
한/글 전용 로직은 클라이언트에 두지 않습니다.

- 엔진은 `hwpctl` 하나뿐입니다.
- 글자를 타이핑하지 않습니다. `pyhwpx` / `win32com` `HWPFrame.HwpObject` 로 문단·표·셀을 조작합니다.
- 문단·표·셀 명령은 **Undo 한 덩어리**입니다.
- **자동저장 없음.** 원본은 덮어쓰지 않고 `save_as` 로 새 파일에 저장합니다.
- 작성기는 한 번에 하나만. 잠금 파일이 두 클라이언트의 동시 쓰기를 막습니다.

대상: Windows PC (`DESKTOP-FH9UHKD` 등) + 한글 오피스 2022.  
한글 2024 전용 GSG / `GetCtrlInstID` / `SelectCtrl` 은 쓰지 않습니다.

---

## 설치 (Windows + 한글 2022)

1. [한글 2022](https://www.hancom.com/)가 설치되어 있는지 확인합니다.
2. [Python 3.10+](https://www.python.org/downloads/) 을 설치합니다. 설치 시 **Add Python to PATH** 를 켭니다.
3. 이 저장소를 받은 뒤:

```bat
py -3.12 -m pip install -e ".[windows]"
```

개발·테스트만 할 때(한/글 없는 머신):

```bash
pip install -e ".[dev]"
pytest
```

4. 한글을 한 창 열어 둡니다. `hwpctl` 은 **지금 열린 창(캔버스)** 에 붙습니다.
5. 처음 파일 열기/저장 때 보안 모듈(`FilePathChecker`) 대화 상자가 뜨면 허용합니다. `pyhwpx` 가 모듈을 등록합니다.

연결 확인:

```bat
hwpctl status
```

한/글이 없거나 Windows 가 아니면 스택 없이 한국어로 실패합니다.

```
한/글(한글 오피스)을 찾을 수 없습니다. 이 컴퓨터에 한글 2022가 설치되어 있고 Windows에서 실행 중인지 확인하세요. ...
```

---

## 클라이언트 바꾸기

서버는 같고, 설정만 다릅니다. 한/글 코드를 클라이언트마다 넣지 마세요.

| 클라이언트 | 붙는 방식 | 예제 |
|---|---|---|
| Cursor | MCP stdio | [`examples/cursor/mcp.json`](examples/cursor/mcp.json) |
| Codex | MCP stdio | [`examples/codex/config.toml`](examples/codex/config.toml) |
| Claude Code | MCP stdio | [`examples/claude-code/.mcp.json`](examples/claude-code/.mcp.json) |
| Gemini CLI | MCP stdio | [`examples/gemini/settings.json`](examples/gemini/settings.json) |
| Grok Bot / 원격 | MCP streamable HTTP + 토큰 | [`examples/grok-http/`](examples/grok-http/) |

stdio 예 (Cursor·Codex·Claude·Gemini 공통):

```json
{
  "mcpServers": {
    "hwpctl": {
      "command": "hwpctl",
      "args": ["mcp"],
      "env": { "HWPCTL_CLIENT": "cursor" }
    }
  }
}
```

- Cursor: 프로젝트 `.cursor/mcp.json` 또는 사용자 MCP 설정에 위 내용을 넣습니다.
- Codex: `~/.codex/config.toml` 에 `examples/codex/config.toml` 을 복사합니다.
- Claude Code: 프로젝트 `.mcp.json` 또는 `claude mcp add`.
- Gemini CLI: `~/.gemini/settings.json` 의 `mcpServers`.

바꾼 뒤 클라이언트를 재시작하면 같은 `status` / `insert_title` / `create_table` 도구가 보입니다.

### Grok Bot (HTTP)

Grok Bot 은 원격이라 **이 PC의 localhost 에 바로 닿지 않습니다.**  
로컬에 HTTP 를 띄운 뒤, 사용자가 나중에 터널(SSH, Cloudflare Tunnel 등)로 노출해야 합니다. 이 저장소는 노출을 가정하지 않습니다.

```bat
set HWPCTL_TOKEN=긴무작위문자열
hwpctl mcp --http --host 127.0.0.1 --port 18765 --token %HWPCTL_TOKEN%
```

- MCP 엔드포인트: `http://127.0.0.1:18765/mcp`
- 헤더: `Authorization: Bearer <토큰>` 또는 `X-Hwpctl-Token: <토큰>`
- 토큰 없으면 401. `127.0.0.1` / `localhost` 만 허용합니다.

---

## 명령 / MCP 도구

CLI 와 MCP 는 **같은 함수**를 부릅니다. 성공 시 JSON, 실패 시 stderr 한국어.

| 이름 | 하는 일 |
|---|---|
| `status` | 창 제목, 경로, 수정 여부, 쪽, 한/글 버전 |
| `open` | 새 문서 또는 경로로 열기. 수정본이 있으면 `--discard` |
| `snapshot` | 제목·본문·표·선택 영역 읽기 |
| `insert_title` | 제목 문단 (가운데, 굵게, 큰 글씨). Undo 1단위 |
| `insert_paragraph` | 본문 문단. Undo 1단위 |
| `create_table` | 표. `--header-fill gray` 가능. Undo 1단위 |
| `fill_cells` | 셀 값. JSON 배열 또는 `A1=값`. Undo 1단위 |
| `set_format` | 글꼴·크기·굵게·정렬·셀 색 |
| `replace_selection` | 선택 영역 교체 |
| `undo` | 직전 명령을 한/글 Undo 한 덩어리로 |
| `page` | 현재 쪽 읽기 / `--goto N` 이동 |
| `save_as` | **새 경로** 저장. 원본 유지. 자동저장 없음 |
| `save` | 원본 덮어쓰기. **`--overwrite` 필수** |
| `close` | 닫기. **`--force` 필수** |

도구 목록만 (한/글 불필요):

```bash
hwpctl mcp --list-tools
```

모델이 「사업계획서, 4열 8행 표, 첫 행 회색」을 이렇게 매핑하면 됩니다.

```bat
hwpctl insert_title 사업계획서
hwpctl create_table --rows 8 --cols 4 --header-fill gray
hwpctl fill_cells --table 0 --cells "[[\"항목\",\"내용\",\"담당\",\"기한\"]]"
hwpctl save_as "%USERPROFILE%\Documents\사업계획서-초안.hwpx"
```

서브커맨드 이름은 밑줄입니다 (`insert_title`, `fill_cells`).

---

## 파괴적 작업

아래는 **명시 플래그 없이 거부**합니다.

| 작업 | 플래그 |
|---|---|
| 원본 덮어쓰기 (`save`) | `--overwrite` |
| 문서 닫기 (`close`) | `--force` |
| 수정본을 버리고 다른 파일 열기 | `--discard` |
| `save_as` 로 원본과 같은 경로 | 거부 → `save --overwrite` |

큰 범위 삭제, 표·쪽·그림 구조 변경 API 는 넣지 않았습니다. 넣게 되면 같은 방식으로 플래그를 요구합니다.

---

## 잠금

`%LOCALAPPDATA%\hwpctl\hwpctl.lock` (Windows) 또는 `$XDG_RUNTIME_DIR/hwpctl/hwpctl.lock`.  
경로 재정의: `HWPCTL_LOCK`, `HWPCTL_STATE`.  
클라이언트 이름: `HWPCTL_CLIENT` (오류 메시지에 표시).

MCP 서버가 떠 있어도 잠금은 **명령 단위**입니다. 서버 프로세스가 잠금을 붙잡고 있지 않습니다.

---

## 개발 (한/글 없이)

파서와 잠금은 Linux 에서도 테스트합니다.

```bash
pip install -e ".[dev]"
pytest
hwpctl status
# → 한국어 오류, 종료 코드 2
```

레이아웃:

```
hwpctl/           엔진·CLI·MCP
examples/         클라이언트 설정만 (한/글 코드 없음)
tests/            파서·잠금·한/글 없음
```

라이브 편집은 Windows + 한글 2022 + `pip install -e ".[windows]"` 가 필요합니다.