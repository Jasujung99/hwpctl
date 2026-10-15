# 통합 검증 기록

## 글맵시 `insert_text_art` 실기 검증 (2026-10-15, #30)

환경: Windows 11, 한글 2022 `12.0.0.850`, Python 3.13, pywin32 312. 새 문서와 DispatchEx 소유 문서만 사용했다.

- 실측: `TextArtCreate`는 넘긴 값을 무시하고 기본 글맵시를 만든다. `GetDefault` 없이 `Execute`하면 RPC_E_SERVERFAULT가 난다.
  `ShapeObjDialog`는 하위 셋 복사본을 돌려주므로 `SetItem`으로 다시 넣어야 하고, 너비·높이는 성공을 반환해도
  무시한다(RelTo·ShapeType 변형 모두). 크기는 개체 `Properties` 대입으로 바뀌며 Undo 단계를 만들지 않는다.
- 결과: 생성 1 + 속성 1 = 한/글 Undo 2단계, hwpctl `undo` 한 번으로 개체가 사라진다.
- 실기 확인: 선형(step 255)·방사형(step 200)·단색 채우기, 모양(wave2·arch_up·rectangle), 굵게, 정렬 4종, 여러 줄,
  줄·글자 간격 끝값(50·500), 윤곽선, 글자처럼 취급·떠 있음(쪽 기준), 표 칸 안 삽입, 요청 크기(mm→HU) 정확히 저장.
- 왕복: UI로 만든 글맵시 HWPML → `reference_to_spec`(손실 없음) → `build_document` → HWPX가 원본과 내용·글꼴·모양·
  정렬·간격·크기(HU)·위치·윤곽선·그러데이션(step 포함) 모두 일치.
- 회귀: opt-in 실기 20개 통과(기존 18 + 글맵시 2), 남은 `Hwp.exe` 없음. 단위 523 passed.

## v0.1.0 릴리스 실기 검증 (2026-10-15)

환경: Windows 11 Home 22621, 한글 2022 `12.0.0.850`, Python 3.13.5, pywin32 312(`win32com`),
MCP Python SDK 1.29.1. 작업 전 한/글 미실행 상태에서 시작했고, 테스트가 만든 문서와 프로세스만 다뤘다.

- 단위·계약: `pytest` 482 passed, 21 skipped. `validate_public_files.py`, `mcp --list-tools`(54), `python -m build` 통과.
- opt-in 실기(`HWPCTL_RUN_HANGUL_INTEGRATION=1`, `test_hangul_live_integration.py`, `test_authoring_native.py`)
  - 첫 실행: 14 passed, 4 failed. `build_document` 소유 세션이 문서를 닫은 뒤 한/글이 자동으로 만든 빈
    문서 때문에 Quit을 건너뛰어 `ok: false`가 되고 숨은 인스턴스 3개가 남음. 남은 인스턴스 때문에
    `test_hierarchical_table_selector_matches_native_control_order`도 실패(단독 실행 시 통과).
  - 수정(`_only_automatic_blank_documents`) 뒤 재실행: **18 passed**, 남은 `Hwp.exe` 없음.
- CLI 점검(새 문서): `open --new`, `status`(backend `win32com`), `insert_title`, `create_table`, `fill_cells`,
  `layout_review`, `snapshot`, `save_as`(.hwpx), 같은 경로 `save_as` 거부(종료 코드 5), `undo`, `page`,
  `move_to_cell` → `exit_table` → `insert_paragraph`, `close_all --force` 정상.
  - `fill_cells` 직후 `exit_table`은 마지막 셀이 아니어서 거부됨 → 문서 예시에 `move_to_cell` 추가.
  - `insert_chart`: 범위 없이 표 전체 선택 실패, `--range` 지정 시 차트는 생기지만 `ChartDataDialogDisable=1`이
    무시되어 데이터 편집 대화상자가 뜨고 호출이 반환되지 않음, 데이터는 기본값 → #33으로 분리하고 사용
    비권장으로 문서화.

## 후속 후보 PR 로컬 검증 (2026-09-08)

기준 main `09fe928` 위의 별도 작업트리. 아래 변경은 PR 제안이며 main 반영을 뜻하지 않는다.

- 자동 회귀: **339 passed, 15 skipped**. opt-in 한/글 12개와 비-Windows 3개 제외.
- 한/글 opt-in 실행: **12 passed**. 기존 7개 외 floating 위치 보존, 소수 mm 격자,
  HWPX 가로/세로 실제 표 편집, 합성 HWP의 읽기 전용 HWPML/PDF/자산 번들 내보내기.
- 내보내기 테스트에 합성 PNG를 추가한 별도 재실행: **1 passed, 11 deselected**.
  포함 그림 1개 추출, 원본 HWP SHA-256 보존, 실제 TABLE 존재, PDF 헤더 확인.
  PDF 물리 쪽수·시각 동일성을 검증한 것은 아니다.
- **1차 안정화:** 위 최초 실행의 `0x800706ba` COM RPC 진단은 합성 원본을 만든
  테스트의 종료된 root COM proxy가 이후 내보내기 세션 동안 유지될 때 재현됐다.
  개별 HWPML/PDF/자산 내보내기는 진단 없이 완료됐으며, 테스트에서 creator의
  proxy를 Quit 직후 해제하자 진단이 사라졌다. 런타임 예외를 무시하는 변경은 없다.
- 새 회귀는 독립 프로세스 안에서 생성→내보내기→종료를 **3회 연속** 수행한다.
  원본 SHA-256·실제 표·포함 그림·PDF 헤더 검사에 더해 stderr/stdout의 native fatal
  또는 RPC 진단도 실패로 처리한다. 반환 코드 0만으로 성공 판정하지 않는다.
  별도 반복 검사 **1 passed, 11 deselected**이며 세 cycle 모두 진단 없이 완료됐다.
- 최종 보강 검사에서는 cycle마다 creator와 내보내기 3개의 **소유 창 핸들 4개**가
  모두 닫혔는지도 확인했다. **1 passed, 11 deselected**, 3회 모두 통과.
  테스트 밖의 창에는 연결하거나 종료 명령을 보내지 않는다.
- 수명주기 수정 후 전체 실기 재실행 **12 passed**, 자동 회귀 **339 passed, 15 skipped**.
  1차는 현재 PR 안정화에서 종료한다. 전체 FAQ importer·복잡 조판 등은
  INTEGRATION_CANDIDATES.md의 다음 단계로 남기며 이번 완료 범위에 포함하지 않는다.
- 공유 내보내기 mock 테스트: 원본 변경/실패 미게시, 기존 경로 거부, XML 인코딩,
  자산 해시·누락·연결 파일 제외. 실제 자산 수명주기 확인은 위 opt-in과 구분한다.
- 공개 파일 검사, CLI/MCP 목록, 합성 FAQ dry-run, wheel/sdist 빌드 통과.
  기존 setuptools license-table deprecation 경고는 그대로다.
- 이번 원격 검증은 PR CI에 기록한다. 과거 main CI 결과를 이번 변경의 증거로 쓰지 않는다.

아래는 앞선 main 통합의 기록이다.

기준: 2026-09-08, main `d0f1141` + 참조 브랜치 여섯 커밋 + 합성 FAQ 정리.

- 통합 전 main: **237 passed, 3 skipped**.
- 여섯 커밋 + 기존 FAQ 테스트: **293 passed, 9 skipped** (Windows 로컬).
- 기본 pytest의 한/글 실기 테스트는 opt-in이며, skip을 실기 통과로 세지 않는다.
- 첫 실행은 시스템 pytest 임시 폴더 접근 권한 때문에 실패했다. 접근 가능한
  별도 basetemp에서 기준 테스트를 다시 실행했고 위 결과는 그 재실행 결과다.

## 최종 로컬 검증

- 자동 회귀: **299 passed, 10 skipped**. Windows에서 비-Windows 전용 3개,
  opt-in 한/글 실기 7개는 기본 실행에서 제외한다.
- 별도 한/글 실기: **7 passed**. 페이지 경계를 넘는 표 격자, 부모 표 탈출,
  문단 종료 제어, HFT 글꼴, floating 표 왼쪽 정렬, 표 전역 안 여백,
  합성 FAQ의 저장·닫기·재열기·실제 병합 표·셀/본문 편집·Undo·창 고정·조판부호.
- 실기 첫 FAQ 실행은 SaveAs 직후 Modified 상태로 재열기 가드가 거부했다.
  가드는 유지하고 저장 파일 존재 확인 → 소유 문서만 닫기 → 재열기 순서로
  수정했다. 소유 COM 인스턴스만 정리하며 사용자 문서/Undo 상태는 변경하지 않는다.
- 합성 FAQ dry-run 성공: 문단 3개, 실제 표 작성 1개, 공개 dispatch 계약.
  미지원 개체·명령 누락·자산 누락·원본 경로·비유한 치수·덮어쓰기 거부 테스트 포함.
- 공개 파일·README 도구 표·JSON/TOML·문서 링크 검사 통과.
- CLI/MCP 목록 확인, wheel 및 sdist 빌드 통과. 소스 배포에 FAQ 예제·명세도 포함.
  기존 setuptools license-table deprecation 경고는 남아 있으며 이번 동작 통합과 별개다.
- bridge: unittest 6개, 저장소 검증, PowerShell 설정 예제 검증 통과.

## 원격 재현

[CI](https://github.com/Jasujung99/hwpctl/actions/workflows/ci.yml)는 main push에서
Windows 및 Linux Python 3.10/3.12 테스트·공개 검사·MCP 목록·합성 FAQ dry-run을
실행한다. Windows job은 배포 패키지도 빌드한다. 정확한 commit별 실행 결과는
위 CI에서 확인하며, 로컬 결과를 원격 CI 통과로 대신하지 않는다.

구조 검사와 편집·재열기는 시각적 동일성의 증거가 아니다. 이번에는 참조 PDF의
렌더링 동일성이나 원본 개인 문서의 완전 재현을 검증하지 않는다.
