# 구현 통합 대장 — 4계층 기준

기준일: 2026-09-08. 이 문서가 코드·예제·실험의 단일 진입점이다.
파일 존재, 자동 테스트 통과, 한/글 실기 통과, 시각적 동일성은 서로 다른 증거다.
새 범용 작성 CLI/MCP나 자동 조판 엔진을 제공한다는 뜻이 아니다.

## 기준 이력과 보존

- 출발 main: `d0f1141` (원격 해시 대조 후 별도 통합 작업트리 생성).
- 이슈 #17–#22의 마지막 `0c74dc0`과 main squash `3ca85d4`는
  `git diff 0c74dc0 3ca85d4`가 비어 있는 동일 트리다. 재적용하지 않았다.
- `feat/reference-rebuild-harness`의 `255590a`, `92b3584`, `cb44cf6`,
  `5139c45`, `0427e5d`, `381fd2e`만 의존 순서대로 통합했다.
- main의 `fbdb97e`/`d0f1141` 조판부호·보수적 서식 정리를 유지했다.
- 기존 작업트리·브랜치·미추적 개인 문서·출력은 그대로 보존했다. 원래
  `hangul.py`의 `i/lf w/mixed` 상태는 의미 있는 diff가 없어 가져오지 않았다.
- 아래의 로컬 실험 경로는 출처 식별자이며 배포 파일이나 실행 가능한 링크가 아니다.
  개인 데이터·참조 HWP·추출 이미지·빌드 로그는 공개 저장소에 넣지 않는다.

상태: **main 제공**은 이 통합을 포함한 main에서 접근 가능한 기능,
**브랜치 구현**은 아직 미통합 코드, **실험**은 제한된 검증의 후보,
**대체됨**은 유지보수 기준이 다른 곳으로 정해진 구현이다.

## 기능별 기준 구현

| 기능 / 출처 | 상태·최종 소속 | 기준 코드·공식 진입점 | 검증·제한 |
| --- | --- | --- | --- |
| 빈 HWPX·파트·참조·저장 / 출발 main | main 제공 / 패키지·입출력 | [hwpx/document.py](../hwpctl/hwpx/document.py): `new_document`, `open_document`, `save_document` | [test_hwpx.py](../tests/test_hwpx.py); python-hwpx extra 필요. 신규 일반 작성 CLI는 없음 |
| HWPX 문단·런·실제 표 / 출발 main | main 제공 / 모델·작성 어댑터 | [hwpx/write.py](../hwpctl/hwpx/write.py): `insert_paragraph`, `create_table_and_fill` | 동일 테스트의 생성·검사; 저수준 임의 도형 작성은 검증 범위 밖 |
| 네이티브 문단·런·셀·표·그림·글상자 / 출발 main | main 제공 / 모델·구성 | [Engine](../hwpctl/engine.py), [HangulCanvas](../hwpctl/hangul.py); `insert_paragraph`, `write_cell`, `create_table`, `insert_image`, `insert_text_box` | [test_engine.py](../tests/test_engine.py), [test_hangul_com.py](../tests/test_hangul_com.py); 실제 표와 글상자는 별개 |
| 표 레이아웃 검토 / 출발 main | main 제공 / 구성·조판 | [layout.py](../hwpctl/layout.py), `layout_review` | Engine 회귀 테스트; 실측 줄 수와 폭 추정을 구분. 페이지 완전 재현·자동 fit 보장 아님 |
| 조판부호 표시·미사용 서식 정의 / `fbdb97e` | main 제공 / 검증·실행 관리 | [edit_support.py](../hwpctl/edit_support.py), `set_edit_marks`; `compact_formatting_xml`은 내부 순수 함수 | [test_edit_support.py](../tests/test_edit_support.py); 반복 설정은 토글 아님. 빈 문단·개체 앵커 자동 삭제 금지 |
| 참조 정규화·구조 비교 / `255590a`, `92b3584` | main 제공 (실험 API) / 모델·검증 | [reference](../hwpctl/reference/__init__.py): `compare_hwpml`, `compare_structure`, 읽기 전용 캡처 | [test_reference_compare.py](../tests/test_reference_compare.py), [test_reference_capture.py](../tests/test_reference_capture.py); 미지원 개체는 inconclusive, 구조 일치 ≠ 시각 일치 |
| 표 격자·셀 탐색·부모 표 탈출 / `cb44cf6`, `381fd2e` | main 제공 / 구성·조판 | `set_table_grid`, `move_to_cell`, `exit_table(destination="parent")` | Engine/COM/parser/MCP 및 [실기](../tests/test_hangul_live_integration.py); 격자는 병합 전 직사각 표에 적용 |
| 문자권 글꼴·문단 종료 제어 / `5139c45` | main 제공 / 모델·구성 | `font_slots`, `insert_paragraph(terminate=False)` | Engine/COM/실기; HFT 설치·폰트 가용성은 실행 환경에 의존 |
| floating 표 정렬 / `0427e5d` | main 제공 / 구성·조판 | `set_table_position` → 네이티브 표 정렬 enum | COM/실기; 일반 문단 정렬 enum과 혼동 금지 |
| 표 전역 안 여백 / `381fd2e` | main 제공 / 구성·조판 | `set_table_inside_margin` | Engine/COM/실기; `TABLE/INSIDEMARGIN`과 `CELL/CELLMARGIN`을 구분 |
| 합성 FAQ 작성 드라이버 / 로컬 미추적 예제 | main 제공 (공식 예제) / 입력 변환·구성 | [드라이버](../examples/rebuild_faq_002_from_normalized_spec.py), [명세 안내](../examples/FAQ_002_NORMALIZED_SPEC.md), [합성 JSON](../examples/specs/faq.synthetic.json) | [FAQ 테스트](../tests/test_rebuild_faq_002_from_normalized_spec.py), opt-in 실기. 공개 dispatch만 사용. 자동 조판·범용 import 아님 |
| FAQ 여백 재적용 커서 이동·개별 격자 설정 | 대체됨 / 예제 | 공식 예제의 `move_to_cell` / `set_table_grid` | 원본 로컬 스크립트는 보존; 새 예제는 불필요한 서식 액션을 내보내지 않음 |
| 저장·창 고정·부분 실패 Undo / #17–#22 | main 제공 / 실행 관리 (4계층 외부) | Engine / HangulCanvas / [lock.py](../hwpctl/lock.py) | Engine/lock 회귀. 자동 저장·다른 창 암묵적 닫기 없음 |

이번에 확인한 참조 브랜치의 여섯 커밋은 모두 통합했다. 그 범위에 남은
`브랜치 구현` 항목은 없다. 다른 실험은 아래 기준을 통과하기 전 승격하지 않는다.

## 4계층 책임과 변환 지점

| 계층 | 책임·기존 확장 지점 | 여기서 하지 않는 일 |
| --- | --- | --- |
| 패키지·입출력 | `hwpx/document.py`, `hwpx/write.py`, 포맷별 저장·참조 보존 | 입력 의미 추측, 시각적 동일 판정 |
| 문서 모델 | 문단·런·표·셀·도형 의미, `reference/model.py`, FAQ `BuildSpec` | 참조 정규화와 작성 명세의 강제 스키마 통합 |
| 구성·조판 | `layout.py`, Engine의 검증·조합, HangulCanvas 네이티브 크기·배치 | 문서별 좌표 우회를 모든 문서에 적용 |
| 검증 | `hwpx/inspect.py`, `hwpx/compare.py`, `reference/structural.py`, 회귀 테스트 | 구조 검사만으로 렌더링 동일성 주장 |

참조 HWP → 읽기 전용 캡처 → `reference/model.py`의 관찰 모델은 **비교용**이다.
FAQ JSON → `load_spec`의 `BuildSpec` → `PublicBuild` → 공개 `Engine.dispatch`는
**작성용**이다. 관찰값을 작성 의도로 바꾸는 분석기는 별도 검토 대상이며 현재
두 모델 사이의 범용 자동 변환기는 없다. `_table_position` 같은 예제 내 변환은
원본 관찰 필드와 공개 명령의 인라인/떠 있는 표 의미 차이를 명시한다.

하나의 기존 모듈이 여러 책임을 포함할 수 있다. 호환성을 지키기 위해 새 폴더
4개로 옮기거나 import를 바꾸지 않았다. 창 생성·저장·닫기·잠금·대상 고정은
Engine/HangulCanvas 실행 관리에 남기고, 예제가 별도 수명주기 엔진을 만들지 않는다.

공식 명령 기준은 [tools.py](../hwpctl/tools.py), [CLI](../hwpctl/cli.py),
[parser](../hwpctl/parser.py), [MCP](../hwpctl/mcp_server.py),
[README 도구 표](../README.md)다. 참조 캡처와 HWPX 작성 래퍼는 라이브러리 API이며
별도의 공개 MCP 명령으로 오인하지 않는다.

## 남은 프로토타입과 승격 조건

| 로컬 원본 식별자 | 상태·소속 후보 | 보관 이유·후속 승격 조건 |
| --- | --- | --- |
| `tmp/haeon-final-editable/build_editable.py`, `open_in_hwp.py` | 실험 / 작성 어댑터·실행 관리 | 개인 JSON·`haeon-upgrade/before.hwpx` 템플릿 의존. 표는 사각형+글상자이며 실제 표가 아님. 글상자 261개는 사각형 전체 433개에 포함됨. ZIP 잔존 자산, 줄 수 추정, 고정 페이지 분할 검증 필요 |
| `tmp/haeon-137/extract_layout.py`, `build.py`, `repair_geometry.py` | 실험 / 입력 변환·구성 | PDF 측정값 기반 글상자·기하 보정. 글자 누락·범위·좌표 회귀 fixture 없이는 기본 동작으로 채택하지 않음 |
| `tmp/haeon-upgrade/prepare.py`, `add_table.py`, `compose.py` | 실험 / 구성·검증 | 실제 표·허용 그림·서식 정리 후보. 개인 템플릿 제거, 합성 실제 표·자산 허용 목록·저장 후 검사 필요 |
| `tmp/sound-lab/build.py`, `open_save.py`, `tmp/sound-landscape.py` | 실험 / 구성·실행 관리 | landscape가 sound-lab 소스의 앞부분을 읽어 실행하므로 독립 삭제 불가. 템플릿·오른쪽 기준 좌표·문단 들여쓰기 우회는 원인 입증과 합성 경계 테스트 후 판단 |
| `examples/export_faq_002_normalized_spec.py` (미추적 원본) | 실험 / 입력 변환 | 문서별 추출기·기본 참조 경로. 모델 분리와 미지원 정보 보존을 검증하고 경로·개인 내용을 제거한 뒤 별도 승격 |
| `examples/export_reference_hwpml_readonly.py`, `export_reference_pdf_readonly.py` (미추적 원본) | 실험 / 검증·입출력 | HWPML 캡처는 `hwpctl.reference.capture`를 기준으로 중복 축소 후보. PDF 캡처는 동일 렌더러 시각 검증 역할을 따로 검토 |
| `examples/rebuild_official_notice_from_blank.py`, `rebuild_official_notice_via_hwpx.py`, 저장소 `tmp/` 공고문 보정들 | 실험 / 입력 변환·구성 | 개인 경로·서로 간 import·python-hwpx 비공개 내부 API 의존. 병합·여백·앵커·페이지 흐름을 합성 테스트로 분리한 뒤 공개 API 사용으로 전환 |
| `tmp/haeon-final-reference/build_hwp.py`, `open_in_hwp.py` | 대체됨 (기존 요청으로 삭제됨) | 전체 렌더링 페이지를 그림 컨테이너에 넣는 방식. 편집형 재현 기준이 아니므로 되살리지 않음 |

원본 스크립트나 브랜치를 일괄 삭제하지 않았다. 후속 순서는 입력 검증·내용
완전성 → 네이티브 표/개체 어댑터 → 단위·배치 근거 → 저장 후 검사다.
각 후보마다 공개 API, 합성 실패·성공 fixture, 회귀, 소유 계층, 대체 호출 경로가
갖춰진 경우에만 승격한다. 새 작성 명령·자동 조판 엔진은 별도 후속 설계다.

## 검증과 저장소 경계

검증 결과는 [통합 검증 기록](INTEGRATION_VERIFICATION.md)에 기록한다.
본문은 텍스트, 표는 실제 표로 확인한다. 로고·낙관·교육용 삽화는 허용된 그림으로
별도 집계한다. `그림 0개`나 COM `PageCount`만을 성공 기준으로 삼지 않는다.
명시적 `PageBreak`도 물리 페이지 수와 일대일 대응하지 않는다.

`hwp-ai-bridge`는 기능 상태와 예제 링크를 안내하는 허브다. `hwp-live-safe`는
새 문서·preview·revision·승인 계약을 그대로 유지한다. 공용 Undo/잠금이나 자동
라우팅, safe에 새 작성 엔진 연결은 이번 통합 범위가 아니다.
