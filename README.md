# hwpctl — 한/글 라이브 코파일럿 브리지

열린 **한글 2022** 창을 채팅 클라이언트가 고치게 하는 **단일 작성기**입니다.  
Grok Bot, Cursor, Codex, Gemini CLI, Claude Code 는 설정을 갈아끼우기만 하면 됩니다.  
한/글 전용 로직은 클라이언트에 두지 않습니다.

- 엔진은 `hwpctl` 하나뿐입니다.
- 글자를 타이핑하지 않습니다. `pyhwpx` / `win32com` `HWPFrame.HwpObject` 로 문단·표·셀을 조작합니다.
- 문단·표·셀 명령은 **Undo 한 덩어리**입니다.
- **자동저장 없음.** 원본은 덮어쓰지 않고 `save_as` 로 새 파일에 저장합니다.
- 작성기는 한 번에 하나만. 잠금 파일이 두 클라이언트의 동시 쓰기를 막습니다.

대상/실측 기준: Windows + 한글 2022 `12.0.0.850` + pyhwpx `1.7.2`.
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
| `snapshot` | 제목·본문·표·선택 영역 읽기. 캐럿·선택은 원래대로 복원 |
| `insert_title` | 제목 문단 (가운데, 굵게, 큰 글씨). 서식은 제목에만. Undo 1단위 |
| `insert_paragraph` | 본문 문단. Undo 1단위 |
| `create_table` | 표. `--header-fill gray`, 기본 칸 안여백 3.5/2.0mm. Undo 1단위 |
| `fill_cells` | 셀 값. JSON 배열 또는 `A1=값`. Undo 1단위 |
| `layout_review` | 표 줄바꿈·행 높이·본문 폭·쪽 수 검토/수정. `--dry-run`은 계획만 |
| `set_cell_margin` | 표 칸 **안쪽 여백**(mm). 표 전체·`--range`·현재 셀 |
| `set_col_width` / `get_col_width` | 열 너비를 mm·비율로 설정 / mm로 조회 |
| `set_row_height` / `get_row_height` | 행 높이를 mm로 설정 / 조회 |
| `merge_cells` | `TableCellBlock` 선택 범위의 셀 합치기 |
| `set_valign` | 셀 세로 정렬: `top` / `center` / `bottom` |
| `set_cell_border` | 셀 테두리. `TypeHorz`는 한글 2022 미지원 |
| `insert_chart` | 표 데이터로 **한/글 네이티브 차트** 삽입 (그림 아님) |
| `set_format` | 글꼴·크기·굵게·정렬·셀 색. `--range` 는 요청 칸에만 |
| `set_style` | 현재 문단에 문서 스타일 적용. 예: `개요 1` |
| `replace_selection` | 블록 선택 영역 교체. 선택 없으면 거부 |
| `undo` | 직전 hwpctl 명령을 한/글 Undo 한 덩어리로. 기록 없으면 거부 |
| `page` | 현재 쪽·`PageCount` 읽기 / `--goto N` 이동 / `--break` 쪽 나누기 |
| `page_image` | 고정된 창의 쪽을 이미지로 저장. `--page N`(1부터, 0=현재 쪽), `--out PATH` |
| `inspect_format` | 문단 정렬·글꼴·크기·굵게·색을 읽어 디자인 그룹으로 묶기. `--limit`(기본 40) |
| `set_pagedef` | 용지 크기·여백·가로/세로 방향 |
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
hwpctl layout_review
hwpctl save_as "%USERPROFILE%\Documents\사업계획서-초안.hwpx"
```

서브커맨드 이름은 밑줄입니다 (`insert_title`, `fill_cells`).

### 표 편집 뒤 항상 레이아웃 검토

`create_table`, `fill_cells`, `set_format`, `set_cell_margin`, `insert_chart` 등으로
표를 만들거나 채운 뒤에는 **항상 `layout_review`를 한 번 실행합니다.** 편집 명령과
자동으로 묶지는 않습니다. 한/글 잠금과 Undo 단위를 섞지 않기 위해 별도 명령으로
호출해야 합니다.

```bat
hwpctl layout_review                         :: 문서의 모든 표를 검토하고 기본적으로 수정
hwpctl layout_review --table 0               :: 0번 표만 검토하고 수정
hwpctl layout_review --table 0 --dry-run     :: 수정하지 않고 JSON 계획만 출력
```

셀의 조판 줄 수는 한글 2022의 `MoveLineEnd` 위치 진행과 `KeyIndicator` 셀 주소를
함께 확인해 실측합니다. 명시적 줄바꿈보다 조판 줄 수가 많을 때만 열 너비로 인한
줄바꿈으로 판정합니다. 한글 2022 Automation에는 문자열 조판 폭을 직접 재는 API가
없으므로 필요한 목표 열 너비는 글자 크기와 유니코드 문자 폭으로 추정하며, 열 하나가
본문 폭의 45% 또는 기존 너비의 1.6배를 넘지 않게 제한합니다. 표 폭은 용지 폭에서
좌우·제본·표 바깥 여백을 뺀 범위를 넘기지 않습니다.

---

## 표 칸 안쪽 여백 (셀 안 여백)

글자가 칸 테두리에 붙는 문제는 표 바깥 여백이 아니라 **셀 안쪽 여백** 문제입니다.

- `create_table` 은 새 표의 모든 칸에 기본 안여백 **좌우 3.5mm / 상하 2.0mm** 를 적용합니다.
  한/글 기본값(1.8/0.5mm)보다 넉넉합니다. `--cell-padding "3.0,1.5"` 로 바꾸거나
  `--cell-padding none` 으로 끌 수 있습니다.
- 이미 있는 표는 `set_cell_margin` 으로:

```bat
hwpctl set_cell_margin --table 0                        :: 0번 표 전체 칸, 기본 3.5/2.0mm
hwpctl set_cell_margin --table 0 --left 4 --right 4 --top 2 --bottom 2
hwpctl set_cell_margin --table 0 --range A1:D4          :: 해당 칸들만
```

한글 2022에서 `set_table_inside_margin`은 `True`를 반환해도 실제 값이 바뀌지
않았습니다. 따라서 `create_table`의 기본 여백과 `set_cell_margin --table N`은
모두 표의 실제 셀 주소를 순회하며 각 셀에 `set_cell_margin`을 한 번씩 적용합니다.
Undo 기록에도 적용한 셀 수가 그대로 들어갑니다.

## 한글 2022 실측 서식 명령

MCP/Engine 시그니처(같은 이름의 CLI도 제공):

```python
set_col_width(widths, table=None, column=None, unit="mm")  # unit: mm | ratio
get_col_width(table=None, column=None)                     # 결과 단위: mm
set_row_height(height, table=None, row=None)               # mm, row는 1부터
get_row_height(table=None, row=None)                       # 결과 단위: mm
merge_cells(cell_range, table=None)
set_valign(align, table=None, cell_range="")               # top | center | bottom
set_cell_border(sides="all", line_type="Solid", width="0.12mm",
                color="#000000", table=None, cell_range="")
set_style(style)                                           # 예: "개요 1"
set_pagedef(paper_width=None, paper_height=None, left=None, right=None,
            top=None, bottom=None, header=None, footer=None, gutter=None,
            landscape=None, apply="current")
page(goto=None, break_page=False)
page_image(page=0, out="", resolution=150)
inspect_format(limit=40)
```

- 열·행 치수는 `GetCellWidth` 없이 `TablePropertyDialog`의
  `ShapeTableCell.Width/Height`를 읽고, 설정할 때 `ShapeCellSize=1`을 씁니다.
  `ratio`는 현재 표 전체 폭을 유지하며 모든 열의 비율을 지정합니다.
- 병합은 `TableCellBlock` → `TableCellBlockExtend` → 셀 이동 →
  `TableMergeCell` 순서입니다. `TableMergeCell` 단독 호출은 하지 않습니다.
- 세로 정렬은 `TableVAlignTop/Center/Bottom`이며 결과의 `vert_align`은 각각
  `0/1/2`입니다.
- 테두리는 `CellBorderFill`을 사용합니다. 왼쪽 색 항목은 한글 2022의 실제
  철자인 `BorderCorlorLeft`를 사용합니다. 내부 가로선 `TypeHorz`는 오류로
  거부합니다.
- 쪽 나누기는 `BreakPage`, 쪽 수는 `PageCount`입니다.
- `set_style("개요 1")`은 pyhwpx의 `set_style`을 사용합니다.
  한글 2022에서 COM 예외가 나는 `HwpOutlineType`/`HwpOutlineStyle` 직접 호출은
  하지 않습니다.
- 편집 전후에 한/글 대화상자를 확인하며, 떠 있으면 대신 누르지 않고 한국어
  오류로 중단합니다. SendKeys와 자동저장은 사용하지 않습니다.

CLI 예:

```bat
hwpctl set_col_width --table 0 --widths 1,2,1 --unit ratio
hwpctl get_col_width --table 0
hwpctl set_row_height --table 0 --row 2 --height 12
hwpctl merge_cells --table 0 --range A1:B1
hwpctl set_valign center --table 0 --range A1:C2
hwpctl set_cell_border --table 0 --range A1:C2 --sides all --color #333333
hwpctl set_style "개요 1"
hwpctl set_pagedef --paper-width 210 --paper-height 297 --left 20 --right 20
hwpctl page --break
hwpctl page_image --page 1 --out "%LOCALAPPDATA%\hwpctl\page-1.bmp"
hwpctl inspect_format --limit 40
```

## 쪽 이미지 (`page_image`) · 서식 그룹 (`inspect_format`)

둘 다 **읽기 전용**입니다. 문서를 저장하지 않습니다.

```bat
:: 1쪽을 bmp 로. 경로를 생략하면 %LOCALAPPDATA%\hwpctl\page-1.bmp
hwpctl page_image --page 1

:: 현재 쪽. png/jpg 는 내부에서 bmp 로 만든 뒤 Pillow 로 변환
hwpctl page_image --page 0 --out C:\Temp\now.png

:: 해상도 기본 150 DPI (300보다 빠름)
hwpctl page_image --page 2 --out C:\Temp\p2.bmp --resolution 150
```

- 한글 2022 `12.0.0.850` 에서 `CreatePageImage` 는 **이름 인자**로만 호출합니다.
  `CreatePageImage(path, page)` 위치 인자는 이 PC에서 1KB 스텁만 씁니다.
- COM `pgno` 는 **0부터**. CLI `--page` 는 1부터이므로 `pgno=N-1` 을 넘깁니다.
  `--page 0` 은 현재 쪽 (pyhwpx 관례).
- 쓰기 전에 `FilePathChecker` 를 등록합니다. 보안 모듈 대화 상자가 뜨면 허용하세요.
- `png`/`jpg`/`jpeg` 경로는 먼저 bmp 를 만든 뒤 Pillow 로 변환합니다 (`pyhwpx.create_page_image` 와 동일).

```bat
:: 문서 처음부터 문단을 순회해 같은 서식이 이어지면 한 그룹으로
hwpctl inspect_format
hwpctl inspect_format --limit 80
```

- `MoveDocBegin` 후 각 문단에 캐럿을 두고 `CharShape`/`ParaShape` 를 읽습니다.
- `InitScan`/`GetText` 는 쓰지 않습니다. 이 PC에서 모든 단위를 굴림 13pt 가운데로 잘못 보고합니다.
- 표 안 문단도 포함하고 `in_table: true` 로 표시합니다 (`CurFieldState` 1 또는 17).
- 정렬 맵: AlignType `0=justify 1=left 2=right 3=center 4=distribute`.
- 결과는 `{ ok, command, groups: [{ key, count, samples }] }` JSON 입니다.

저장 없이 시험하려면 빈 문서에서 다음처럼 실행하고, 결과 확인 뒤 `undo`로
직전 명령을 되돌립니다. `save`/`save_as`를 호출하지 않는 한 자동으로 저장되지
않습니다.

```bat
hwpctl open --new
hwpctl create_table --rows 2 --cols 3
hwpctl set_col_width --widths 1,2,1 --unit ratio
hwpctl set_valign center --table 0
hwpctl layout_review --table 0
hwpctl page
hwpctl undo
```

## 한/글 네이티브 차트 (insert_chart)

`insert_chart` 는 **한/글 입력 > 차트** 개체를 넣습니다. PNG 그림 삽입이 아닙니다.

흐름: 데이터 표를 만들고(`create_table` + `fill_cells`) → `insert_chart --table N`.
표(또는 `--range` 범위)의 셀을 선택한 뒤 `InsertChart` 액션을
`ChartGroup` / `ChartIndex` / `ChartDataDialogDisable=1` 파라미터로 실행합니다
(한컴 포럼에서 확인된, 노출된 파라미터 전부입니다 — 생성 후 차트 수정 API 는 없습니다).

```bat
hwpctl insert_chart --table 1 --type line      :: 인생 그래프 = 꺾은선
hwpctl insert_chart --table 0 --type column --range A1:B10
```

- 종류: `line`(꺾은선) / `column`(세로막대) / `bar`(가로막대) / `pie`(원형).
  0=가로막대·1=세로막대·3=원형은 한컴 포럼에서 확인된 값이고, line=2 는 추론값이라
  실기에서 종류가 다르게 나오면 `--type` 대신 `--index` 와 함께 조정하세요.
- **한글 2022 이상 전용.** 2020 이하에는 `ChartDataDialogDisable` 이 없어 데이터
  편집 대화상자가 뜹니다. 대화상자가 뜨면 자동화 실패입니다 — hwpctl 은 한국어
  오류를 내며, 화면의 창을 대신 눌러 주지 않습니다.

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

`undo` 는 hwpctl 이 기록한 명령만 되돌립니다. hwpctl 명령 사이에 한/글에서 직접
편집했다면 그 편집이 먼저 되돌아갈 수 있으니, 수동 편집은 한/글의 Ctrl+Z 를 쓰세요.

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