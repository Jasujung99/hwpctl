# 변경 기록

주요 변경 사항을 이 문서에 기록합니다. 버전은 [Semantic Versioning](https://semver.org/)을
따르며, 첫 GitHub Release는 한글 2022 수동 검증을 통과한 뒤 `v0.1.0`으로 게시합니다.

## [Unreleased]

### Added

- `--backend auto|hwpx|hancom` (`auto` 는 비-Windows 에서 `hwpx`)
- HWPX 쓰기 래퍼: 부분 런(색·밑줄), 표 채움/테두리/열너비, 크림 구역 헤더
- `scripts/recreate_gongo.py` 와 `hwpx_compare` — 공고문 1–3쪽 충실 재현, 4–10·27–29 골격
- 한글 GUI 없이 inspect JSON·레이아웃 HTML·원본 PNG 비교 시트
- 한글 없이 `.hwpx`를 다루는 준비 계층(`hwpctl/hwpx`, extra `hwpx`, `hwpx_status` / `hwpx_inspect`)
- Codex, Claude Code, Cursor, Gemini CLI, Grok Build용 로컬 MCP 설정 예제
- 공개용 보안 정책, 알려진 한계, 기여 안내와 릴리스 체크리스트
- 표 너비·높이, 셀 병합·정렬·테두리, 쪽 설정, 스타일과 레이아웃 검토 문서

### Changed

- `open --new` 이후의 후속 명령이 고정된 한글 창을 계속 사용하도록 창 핀을 갱신
- 로컬 클라이언트는 stdio를 기본으로 사용하고 HTTP는 선택 연결로 구분

### Security

- 원본 덮어쓰기·닫기·수정본 폐기에 명시 플래그 요구
- MCP HTTP 연결을 loopback과 토큰으로 제한
