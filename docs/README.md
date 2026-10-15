# 문서 목록 · Documentation

[← README](../README.md)

## 사용 가이드 · User guide (`guide/`)

| 문서 | 내용 |
|---|---|
| [설치](guide/install.md) | 전용 가상환경 설치, 연결 확인, 업데이트, 선택 extra |
| [클라이언트 연결](guide/clients.md) | Claude Code·Codex·Cursor·Gemini CLI·Grok Build 설정, HTTP 연결 |
| [도구 레퍼런스](guide/tools.md) | MCP 도구·CLI 명령 전체 목록과 사용 예 |
| [표와 서식](guide/tables-and-formatting.md) | 표 격자·병합·여백, 문단·글자 서식 시그니처 |
| [한/글 네이티브 차트](guide/charts.md) | `insert_chart` 종류와 제약 |
| [글맵시 (글자 그러데이션)](guide/text-art.md) | `insert_text_art`, 모양 55종, 채우기, 작성 명세 `text_art` |
| [HWPX 작성 (실험)](guide/hwpx-authoring.md) | `.hwpx` 읽기·작성, `reference_to_spec`·`build_document` |
| [안전 장치](guide/safety.md) | 파괴적 작업 플래그, 잠금, Undo |

함께 보기: [알려진 한계](../KNOWN_LIMITATIONS.md) · [변경 기록](../CHANGELOG.md) ·
[보안 정책](../SECURITY.md)

## 개발 문서 · Developer docs (`dev/`)

기여자와 유지관리자를 위한 내부 기록입니다. 사용자 기능 설명은 위 가이드를 기준으로 합니다.

| 문서 | 내용 |
|---|---|
| [구현 통합 대장 (4계층 기준)](dev/INTEGRATION_STATUS.md) | 코드·예제·실험의 단일 진입점 |
| [통합 검증 기록](dev/INTEGRATION_VERIFICATION.md) | 통합 PR별 로컬·실기 검증 결과 |
| [후속 후보 통합 결과](dev/INTEGRATION_CANDIDATES.md) | 폴더 조사 후보의 통합 결과와 남은 경계 |
| [작성 기능 상태](dev/AUTHORING_COMPLETION.md) | 실험적 작성·변환 기반의 제공 범위 |
| [HWPX 업그레이드 계획](dev/hwpx-upgrade-plan.md) | 한글 없이 조립하는 단계 계획 |
| [릴리스 체크리스트](dev/RELEASE_CHECKLIST.md) | 공개 릴리스 전 자동·실기 게이트 |
| [코드 검토 기록](dev/CODE-ISSUES.md) | 과거 코드 검토와 패치 판단 |

## 조사 · Research (`research/`)

| 문서 | 내용 |
|---|---|
| [한글 2022 없이 HWP/HWPX 다루기](research/hwp-without-hangul.md) | 라이브러리 비교와 `python-hwpx` 선택 근거 |

## 문서 규칙

- 사용자에게 보이는 동작이 바뀌면 `guide/`와 [CHANGELOG](../CHANGELOG.md)를 함께 고칩니다.
- 도구를 추가·변경하면 [도구 레퍼런스](guide/tools.md) 표를 `hwpctl.tools` 순서대로 갱신합니다.
  CI가 순서와 이름을 검사합니다.
- 실측 노트와 통합 기록은 `dev/`에 둡니다. 개인 경로·실제 문서 내용은 넣지 않습니다.
