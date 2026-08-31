# CODE-ISSUES — hwpctl 코드 리뷰 (2차 패스)

> ## 패치 현황 (3차 패스)
>
> 아래 항목은 수정 완료. 나머지(중간 #5, #7, #9~#14 / 낮음 전부)는 미착수.
>
> - **#3 [패치됨]** COM 폴백 `goto_addr` — 미확인 액션 `TableRowBegin` 제거, 표준 조합
>   `TableColBegin`+`TableColPageUp` 사용, 모든 `Run()` 반환값 검사, `KeyIndicator` 로
>   도착 셀 주소 검증. `select_cell_text` 는 `is_cell()` 이 아닐 때 `SelectAll` 을 거부
>   (문서 전체 덮어쓰기 경로 차단). `get_into_nth_table` COM 경로에 `FindCtrl()` 추가.
>   `is_cell()` 은 셀필드(`CurFieldState` 17)도 인식(#8 의 한 줄, 가드 동작에 필요).
>   테스트: `tests/test_hangul_com.py` (스텁 COM 으로 실패·검증·거부 경로 재현).
> - **#1 [패치됨]** `insert_title` — 삽입 전 글자/문단 모양을 저장하고 제목 뒤 새 문단에서
>   복원(서식 누출 차단). Undo 기록을 하드코딩 1 대신 실제 실행 액션 수(기본 5:
>   CharShape·ParaShape·InsertText·복원 2회)로 기록. 결과에 `hangul_actions` 노출.
>   버그를 고정하던 `test_insert_title_one_insert` 는 5단계·복원 순서를 단언하는
>   회귀 테스트로 교체.
> - **#2 [패치됨]** `replace_selection` — `get_selected_text` 빈 문자열 판정 폐기.
>   `GetSelectedPos()` 첫 요소(is_block, pyhwpx 문서 확인)를 쓰는 `has_selection()` 으로
>   블록 선택을 판정하고, 판정 불가 시 교체 거부(안전 방향). `snapshot.selection` 도
>   실제 블록일 때만 채움. 테스트: `test_replace_selection_requires_real_block`.
> - **#4 [패치됨]** `connect()` — 실행 중 인스턴스를 ROT 로 먼저 확인해, `open` 이 아닌
>   명령은 한/글을 새로 띄우지 않고 `NO_WINDOW_KO` 오류. win32com 폴백은 `Dispatch`
>   (새 인스턴스 생성) 대신 ROT 바인딩으로 기존 창에 붙음. 창 고정: `open` 이
>   `WindowHandle` 을 state 에 기록하고 이후 명령은 동일 창인지 검증, 불일치 시
>   한국어 오류. `close` 는 고정 해제. 테스트: `test_window_pinning_rejects_other_window`.
>
> 남은 확인 사항(실기 필요): COM 백엔드에서 `CharShape`/`ParaShape` 속성 대입이 Undo
> 1단위인지, `TableColPageUp` 동작, ROT 바인딩 — 한글 2022 실기에서 검증 권장.

범위: `hwpctl/`, `tests/`, `examples/`. 실제 파일을 읽고 확인한 문제만 기록했다.
pyhwpx 동작은 공식 문서(https://martiniifun.github.io/pyhwpx/core.html)와 대조했고,
MCP SDK 동작은 설치된 `mcp==1.29.1` 소스를 직접 확인했다.
이 패스에서는 수정하지 않았다.

표기: **[심각]** 라이브 한/글 창에서 데이터 손상·명령 오동작 / **[중간]** 조건부 오동작·워크플로 파손 / **[낮음]** 품질·엣지 케이스.

---

## 심각

### 1. `insert_title` — Undo 단위 오계산 + 서식 누출
- 위치: `hwpctl/engine.py` `Engine.insert_title`
- 내용: `set_font(bold=True, height_pt=size)` → `set_align("center")` → `insert_text(...)` 로 한/글 액션이 **3개**(CharShape, ParagraphShape, InsertText) 실행되는데 `_record_undo("insert_title", 1)` 로 **1**만 기록한다.
- 라이브 영향 (두 가지):
  1. `hwpctl undo` 가 InsertText 만 되돌리고 굵게/20pt/가운데 서식은 남는다. 이후 undo_stack 전체가 실제 한/글 Undo 히스토리와 어긋나 다음 `undo` 부터 엉뚱한 편집을 되돌린다.
  2. 제목 뒤에 붙는 `\r\n` 문단이 제목 서식을 상속하므로, 다음 `insert_paragraph` 본문이 전부 **굵게·20pt·가운데 정렬**로 들어간다. 서식 복원(또는 새 문단에서 기본 서식 재설정)이 없다.
- 제안: 제목 삽입 전 현재 CharShape/ParaShape 를 저장했다가 삽입 후 복원하고, `_record_undo` 에 실제 액션 수(서식 복원 포함)를 기록. 또는 스타일("개요/제목") 적용 방식으로 전환.
- 참고: `tests/test_engine.py::test_insert_title_one_insert` 가 `undo_stack == [1]` 을 단언해 이 버그를 **정답으로 고정**하고 있다(아래 20번).

### 2. `replace_selection` — 선택 여부 판정이 신뢰 불가
- 위치: `hwpctl/engine.py` `Engine.replace_selection` + `hwpctl/hangul.py` `HangulCanvas.get_selected_text`
- 내용: 가드가 `get_selected_text() == ""` 로 선택 유무를 판단한다. 그런데
  - pyhwpx 문서 명시: `get_selected_text` 는 "본문일 때는 선택영역 **또는 현재 단어**를 리턴". 선택이 없어도 캐럿이 단어 위에 있으면 비어 있지 않다.
  - win32com 폴백은 `GetTextFile("UNICODE", "saveblock:true")` 인데 블록이 없으면 문서 전체가 반환될 수 있다.
- 라이브 영향: 선택이 없는데 가드를 통과 → `insert_text` 가 아무것도 교체하지 않고 캐럿 위치에 텍스트를 **추가 삽입**한다. 모델은 "교체 성공(replaced: true)"으로 보고받는다.
- 제안: `hwp.SelectionMode` 또는 `get_selected_pos()` 로 실제 블록 선택 상태를 확인한 뒤 교체. 교체는 선택 삭제+삽입이 Undo 몇 단위인지도 확인해 `_record_undo` 에 반영.

### 3. win32com 폴백 `goto_addr` — 조용한 실패 → 문서 전체 덮어쓰기 경로
- 위치: `hwpctl/hangul.py` `HangulCanvas.goto_addr` (COM 분기), `select_cell_text`, `Engine.fill_cells`
- 내용: COM 분기는 `Run("TableColBegin")`, `Run("TableRowBegin")` 후 `TableRightCell`/`TableLowerCell` 반복으로 이동한다. 문제 두 가지:
  1. `"TableRowBegin"` 은 한/글 액션 테이블에서 확인되지 않는 ID 다(문서 덤프에도 없음). `run()` 은 `HAction.Run` 이 False 를 반환해도 **예외 없이 무시**하므로, 액션이 없거나 캐럿이 표 밖이면 조용히 이동에 실패한다.
  2. 그 상태에서 `fill_cells` 가 `select_cell_text()` = `Run("SelectAll")` 를 호출한다. 캐럿이 본문에 있으면 SelectAll 은 **문서 전체 선택**이고, 이어지는 `insert_text(값)` 이 문서 전체를 셀 값 하나로 교체한다.
- 라이브 영향: pyhwpx 미설치(순수 win32com) 환경에서 `fill_cells` 가 열린 문서 본문을 통째로 날릴 수 있다. Undo 로 복구는 가능하지만 "파괴적 작업은 플래그 필수" 원칙을 우회하는 최악의 경로다.
- 제안: COM 분기 `goto_addr` 에서 각 `run()` 반환값을 검사해 False 면 즉시 `HangulCommandError`. `select_cell_text` 전에 `is_cell()` 확인. 액션 ID 는 실제 2022 ActionTable 로 검증(셀 주소 이동은 pyhwpx 없이라면 `KeyIndicator` 로 현재 주소를 확인하는 방식이 안전).

### 4. `connect()` — status 가 한/글을 새로 실행하고, 대상 창이 고정되지 않음
- 위치: `hwpctl/hangul.py` `HangulCanvas.connect` (+ 모든 `Engine` 명령이 매 호출 `canvas_factory()` 실행)
- 내용: pyhwpx 문서 명시 — "`hwp = Hwp()` 명령어를 실행하면 아래아한글이 **자동으로 열립니다**. 기존에 창이 있으면 **가장 마지막에 접근했던 창**과 연결됩니다."
  1. 한/글이 안 떠 있으면 `hwpctl status`(읽기 명령)조차 새 한/글 프로세스를 띄운다. "열린 창이 없습니다" 라고 보고해야 할 상황에서 부작용이 생긴다.
  2. 명령마다 새로 연결하므로 `open --new` 로 새 인스턴스를 만든 뒤, 다음 명령이 "마지막 접근 창"에 붙어 **다른 창**을 편집할 수 있다. 사용자가 다른 한/글 창을 클릭한 사이에 명령이 오면 대상이 바뀐다.
- 라이브 영향: 단일 작성기 잠금은 지켜지지만 "어느 창에 쓰는가"가 비결정적이다. 여러 창이 열린 실사용 PC에서 잘못된 문서를 편집할 수 있다.
- 제안: 최초 연결 시 창 핸들/DocumentID 를 state.json 에 기록하고 이후 명령에서 동일 창인지 검증(불일치 시 한국어 오류). 읽기 명령은 실행 중 인스턴스가 없으면 실행하지 말고 "열린 한/글 창이 없습니다" 로 실패.

---

## 중간

### 5. MCP 서버 — 동기 도구가 이벤트 루프를 통째로 블로킹
- 위치: `hwpctl/mcp_server.py` (도구 전부 동기 `def`) + `hwpctl/lock.py` `acquire` 의 `time.sleep(0.05)`
- 확인: 설치된 `mcp==1.29.1` 의 `Tool.run` → `call_fn_with_arg_validation` 은 동기 함수를 **이벤트 루프 스레드에서 직접 호출**한다(worker thread 아님, 소스 확인).
- 라이브 영향: COM 호출 + 최대 `lock_timeout`(기본 8초) 동안 서버 전체가 멈춘다. streamable HTTP 로 두 클라이언트가 붙으면 한쪽 명령 동안 다른 쪽 요청·ping 이 전부 지연되고, 잠금 대기(`time.sleep`)까지 루프 위에서 돈다.
- 제안: 도구를 `async def` 로 바꾸고 내부에서 `anyio.to_thread.run_sync(...)` 로 엔진 호출. (그 경우 Windows COM 은 워커 스레드에서 `pythoncom.CoInitialize()` 필요 — 스레드 진입 시 초기화 코드 추가.)

### 6. win32com 폴백 `set_align` — AlignType 에 문자열 대입
- 위치: `hwpctl/hangul.py` `HangulCanvas.set_align` (COM 분기)
- 내용: `pset.AlignType = "Center"` / `SetItem("AlignType", "Center")`. 자동화 API 의 ParaShape `AlignType` 은 숫자 열거값이고, 문자열→숫자 변환은 pyhwpx `set_para` 가 내부에서 해주는 것이다(문서의 Literal 타입은 pyhwpx 래퍼 시그니처).
- 라이브 영향: win32com 백엔드에서 정렬이 예외 또는 무시로 끝난다. `insert_title` 의 가운데 정렬이 COM 폴백에서 동작하지 않는다.
- 제안: `self.com.HAlign("Center")` 로 변환한 정수를 대입하거나 열거값(예: Center) 을 직접 사용.

### 7. win32com 폴백 `cell_fill` — 파라미터 아이템 이름이 틀렸을 가능성 높음
- 위치: `hwpctl/hangul.py` `HangulCanvas.cell_fill` (COM 분기)
- 내용: `FillAttr.Type = 1`, `FillAttr.FaceColor = ...` 를 쓰는데, CellBorderFill 파라미터셋의 채우기 아이템은 통상 `FillAttr.type = BrushType(...)` + `FillAttr.WinBrushFaceColor` 다. 실패 시 폴백인 `SetItem("FillAttr.FaceColor", ...)` 도 중첩 셋에 점(.) 경로로 접근할 수 없어 무의미하다.
- 라이브 영향: COM 폴백에서 "첫 행 회색"이 조용히 적용되지 않거나(무시) 예외. `create_table --header-fill gray` 의 핵심 시나리오가 폴백 경로에서 깨진다.
- 제안: `WinBrushFaceColor`/`WinBrushHatchColor`/`WinBrushFaceStyle` + `type` 조합으로 수정하고 실기에서 검증. 실패 시 조용히 넘어가지 말고 한국어 오류.

### 8. `is_cell()` COM 폴백 — 셀필드(17)를 놓침
- 위치: `hwpctl/hangul.py` `HangulCanvas.is_cell`
- 내용: `CurFieldState == 1` 만 참으로 본다. pyhwpx 문서: 셀 안 1, **셀필드 안 17** (누름틀 18). 셀필드가 걸린 표(양식 문서에 흔함)에서는 셀 안에 있어도 False.
- 라이브 영향: `create_table` 의 `if not canvas.is_cell(): get_into_nth_table(0)` 분기가 오판 → 9번 문제와 결합해 엉뚱한 표에 헤더 색을 칠한다.
- 제안: `in (1, 17)` 로 판정(18 포함 여부는 정책 결정).

### 9. `create_table` header_fill 폴백 — 문서의 "0번 표"에 칠함
- 위치: `hwpctl/engine.py` `Engine.create_table`
- 내용: 표 생성 직후 `is_cell()` 이 False 면 `get_into_nth_table(0)` 으로 들어가는데, 0번은 **문서에서 첫 번째** 표이지 방금 만든 표가 아니다.
- 라이브 영향: 이미 표가 있는 문서에서 새 표 대신 문서 맨 앞 표의 첫 행이 회색이 된다.
- 제안: 생성 직후에는 마지막 표(`_table_ctrls()[-1]`) 를 대상으로 하거나, 생성 직후 캐럿이 셀 안임을 보장 못 하면 오류로 중단.

### 10. `snapshot` — 읽기 명령이 캐럿·선택을 파괴
- 위치: `hwpctl/engine.py` `Engine.snapshot` → `hwpctl/hangul.py` `list_tables`
- 내용: `list_tables` 가 모든 표에 들어가 셀마다 `goto_addr` 를 실행한다. 스냅샷 후 사용자의 캐럿 위치와 선택 영역이 사라진다. 캐럿 저장/복원(`get_pos`/`set_pos`)이 없다.
- 라이브 영향: 자연스러운 흐름인 "snapshot 으로 확인 → replace_selection 으로 교체"가 항상 실패한다(스냅샷이 선택을 지웠으므로). 또 셀 수 × COM 왕복이라 큰 표에서 잠금을 오래 점유한다.
- 제안: 시작 시 `get_pos()` 저장, 종료 시 `set_pos()` 복원. 표 미리보기는 `table_to_df`/`GetTextFile(HTML)` 등 캐럿 이동 없는 방법 검토, 최소한 미리보기 셀 수 상한.

### 11. `undo` — 수동 편집과 어긋나는 전역 스택
- 위치: `hwpctl/engine.py` `Engine.undo`, `_record_undo` + `hwpctl/lock.py` `WriterState`
- 내용: undo_stack 은 문서·창 구분 없이 state.json 하나에 쌓인다. 사용자가 한/글에서 직접 타이핑한 뒤 `hwpctl undo` 를 부르면 기록된 N 단계가 **사용자의 수동 편집**을 되돌린다. 스택이 비면 무조건 1단계 undo 를 실행해 마지막 수동 편집을 지운다.
- 라이브 영향: "라이브 코파일럿" 시나리오(사용자와 봇이 같은 창을 번갈아 만짐)에서 undo 가 사용자 작업을 삼킨다.
- 제안: 명령 실행 시 문서 수정 카운터나 마지막 명령 시각+`is_modified` 스냅샷을 함께 기록하고, 불일치하면 "수동 편집이 감지되어 자동 undo 를 중단합니다" 오류. 스택이 비면 실행 거부.

### 12. `set_format --range` — 다중 행 범위를 조용히 무시, 부분 범위를 행 전체로 확대
- 위치: `hwpctl/engine.py` `Engine.set_format`
- 내용: `A1:B2` 처럼 여러 행이면 `_same_row` 가 False → 선택 없이 `addrs[0]` 셀만 서식 적용(오류도 없음). `A1:B1` 처럼 한 행이면 `select_row()` 로 **행 전체**(C1, D1 포함)를 선택해 요청보다 넓게 칠한다.
- 라이브 영향: 모델이 "A1:B2 회색" 을 요청하면 A1 만 바뀌고 성공으로 보고. "A1:B1 만" 요청하면 D1 까지 바뀐다.
- 제안: 다중 행이면 명시적 UsageError, 부분 행이면 셀 단위 반복 적용(또는 `goto_addr(select_cell=True)` + 블록 확장으로 정확한 범위 선택).

### 13. `fill_cells` — 셀 교체의 Undo 단위 가정 미검증
- 위치: `hwpctl/engine.py` `Engine.fill_cells`
- 내용: 셀당 `SelectAll` + `InsertText` 를 1 Undo 로 가정하고 `written` 개수를 기록한다. 선택 상태에서 InsertText 가 삭제+삽입 2단위로 기록되면 `undo` 가 절반만 되돌린다. (1번과 같은 계열 — 실기 검증 필요.)
- 제안: 실제 한글 2022 에서 Undo 횟수를 측정해 상수화하거나, 셀 채우기 전후 `is_modified`/문서 상태 기반으로 undo 단계를 세는 방식으로 교체.

### 14. MCP — HwpctlError 외 예외(COM 오류)가 영어 스택 문자열로 노출
- 위치: `hwpctl/mcp_server.py` `_call` (HwpctlError 만 잡음)
- 내용: `pywintypes.com_error` 등은 그대로 전파되어 FastMCP 가 `Error executing tool ...: <원문 예외>` 형태(isError)로 반환한다. "한국어 오류, 스택 덤프 금지" 정책이 MCP 경로에서 깨진다.
- 제안: `_call` 에서 `except Exception` 을 추가해 `{"ok": False, "error": "한/글 명령 처리 중 오류: ..."}` 한국어 요약으로 변환(원문은 로그로).

---

## 낮음

### 15. 종료 코드 충돌 — argparse 사용 오류(2) == 한/글 없음(2)
- 위치: `hwpctl/cli.py` `main` + `hwpctl/errors.py` `HangulMissingError.exit_code = 2`
- 내용: 잘못된 인자도, 한/글 미설치도 종료 코드 2. 스크립트에서 구분 불가.
- 제안: HangulMissing 을 3 이상으로 옮기고 나머지 재배치.

### 16. `--debug`/`--lock-timeout` 이 서브커맨드 앞에만 허용
- 위치: `hwpctl/parser.py` `build_parser` (루트 파서에만 정의)
- 내용: `hwpctl status --debug` 는 "unrecognized arguments" 로 실패. 사용자는 대부분 뒤에 붙인다.
- 제안: 공통 부모 파서(parents=)로 각 서브파서에도 등록.

### 17. `status --json` 플래그가 값 없는 더미
- 위치: `hwpctl/parser.py` (`p_status.add_argument("--json", action="store_true", default=True, ...)`)
- 내용: 항상 True 인 숨김 플래그로 동작엔 문제없지만 죽은 코드다. 다른 서브커맨드에는 없어 일관성도 없다.
- 제안: 삭제하거나 전 명령 공통 옵션으로 승격.

### 18. Windows 잠금 파일 — "a+" 모드로 인해 대기자가 스페이스를 계속 추가
- 위치: `hwpctl/lock.py` `_lock_fd` (win32 분기)
- 내용: "a+" 는 열자마자 위치가 EOF 라 `fh.read(1)` 이 항상 "" → 재시도 루프마다 `fh.write(" ")` 가 잠긴 파일 끝에 스페이스를 덧붙인다(바이트 0 잠금과 무관한 오프셋이라 성공). 기능은 유지되지만 파일이 자라고, 보유자 JSON 뒤에 공백이 붙는다. 또 msvcrt 잠금은 강제 잠금이라 `_read_holder` 가 바이트 0 을 읽지 못해 "누가 잡고 있는지" 메시지가 Windows 에서 사실상 항상 익명이 된다.
- 제안: "r+b"/사전 생성 + 크기 검사로 교체, 보유자 정보는 잠금 파일과 분리된 사이드카 파일에 기록. (이 경로는 CI 에서 테스트되지 않음 — 21번.)

### 19. HTTP 토큰 비교·미들웨어 방식
- 위치: `hwpctl/mcp_server.py` `TokenAuthMiddleware`
- 내용: `provided != self.token` 은 상수 시간 비교가 아니고(로컬 전용이라 위험도 낮음), `BaseHTTPMiddleware` 는 SSE 스트리밍 응답과 역사적으로 궁합 문제가 있다(현재 starlette 1.6 에서는 동작 확인됨).
- 제안: `hmac.compare_digest` 사용, 미들웨어는 순수 ASGI 함수로 교체하면 스트리밍 간섭 여지가 없다.

### 20. 오류 메시지가 CLI 플래그 표기로 고정
- 위치: `hwpctl/engine.py` 의 DestructiveGuardError 문구("--discard", "--overwrite", "--force")
- 내용: MCP 로 호출한 모델에게도 CLI 플래그 문구가 간다. MCP 파라미터명은 `discard=true` 등이다.
- 제안: "--discard (MCP: discard=true)" 병기.

### 21. 색 이름 팔레트가 실제 색과 어긋남
- 위치: `hwpctl/colors.py` `NAMED`
- 내용: `"blue": (189, 215, 238)`, `"green": (198, 224, 180)`, `"red": (255, 199, 206)` — 전부 파스텔(강조용) 색이다. 모델이 "파란색 글자"를 요청하면 연한 하늘색이 나온다.
- 제안: 원색은 원색대로 두고 파스텔은 `lightblue` 등 별도 키로.

---

## 테스트가 주는 거짓 안심

### 22. `test_insert_title_one_insert` / `test_undo_replays_hangul_steps`
- 위치: `tests/test_engine.py`
- 내용: `undo_stack == [1]`(insert_title), `hangul_undo_steps == 2`(create_table) 를 단언해 **1번 버그(단위 오계산)를 스펙으로 고정**한다. FakeCanvas 는 한/글 Undo 모델을 전혀 흉내내지 않으므로 이 숫자들은 구현 반복 확인일 뿐이다.

### 23. `FakeCanvas.get_selected_text` 가 항상 "기존" 반환
- 위치: `tests/test_engine.py`
- 내용: 실제 pyhwpx 의 "선택 없으면 현재 단어 반환" 동작을 감춰 2번 버그가 테스트를 통과한다. "선택 없음" 케이스는 `selected = ""` 로만 재현되는데 실기에서는 "" 가 거의 나오지 않는다.

### 24. Windows 잠금 경로·HTTP 인증 미테스트
- 위치: `tests/test_lock.py`, `tests/` 전반
- 내용: CI(리눅스)에서는 `fcntl` 분기만 돈다. `msvcrt` 분기(18번 문제 포함)는 한 번도 실행되지 않는다. `TokenAuthMiddleware` 의 401/우회 경로, `/health` 무인증 예외도 테스트가 없다 — starlette TestClient 로 리눅스에서 충분히 검증 가능한 부분이다.

### 25. `test_mcp_tools` 가 사설 API 에 의존
- 위치: `tests/test_mcp_tools.py` (`mcp._tool_manager.list_tools()`)
- 내용: SDK 마이너 업그레이드에서 조용히 깨질 수 있다. 공개 API(`await mcp.list_tools()`) 사용 권장.

---

## 우선순위 요약

| 순위 | 항목 | 한 줄 |
|---|---|---|
| 1 | #3 | COM 폴백 fill_cells 가 문서 전체를 덮어쓸 수 있음 (조용한 이동 실패 + SelectAll) |
| 2 | #1 (+#22) | insert_title Undo 오계산·서식 누출, 테스트가 버그를 고정 |
| 3 | #2 (+#23) | replace_selection 선택 판정 불가 — 교체 대신 중복 삽입 |
| 4 | #4 | status 가 한/글을 실행해 버림, 대상 창 미고정 |
| 5 | #6, #7 | COM 폴백 정렬·셀 채우기 파라미터 오류 (헤더 회색 시나리오 파손) |
| 6 | #5 | MCP 동기 도구가 이벤트 루프 블로킹 |
| 7 | #9~#13 | header_fill 대상 표, snapshot 캐럿 파괴, undo 전역 스택, range 확대/무시 |