# 통합 검증 기록

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
