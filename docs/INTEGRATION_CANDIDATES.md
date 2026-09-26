# 폴더 조사 후보의 통합 결과와 남은 경계

2026-09-26. PR #24는 재사용 기반과 실험적 작성·변환 경로를 통합한다.
전체 네이티브 재현의 완성을 의미하지 않으며, 남은 구현과 실기는
[이슈 #25](https://github.com/Jasujung99/hwpctl/issues/25)에 남긴다.
목록은 모든 작업창의 개발 완료 선언이 아니며 원본 폴더/브랜치는 보존한다.

| 원본 후보 | 이번 PR의 소속·기준 구현 | 남긴 부분 / 이유 |
| --- | --- | --- |
| 공고 브랜치의 범용 HWPX 코드 | 입출력·작성 어댑터: hwpctl.hwpx.write, inspect | 공고 전용 gongo.py·HWP/PNG/JSON 원본은 제외. 오래된 compare/Engine을 덮어쓰지 않음 |
| FAQ 작성·변환 공통 코드 | authoring.legacy/model/compiler/converter; reference.analysis | v1 호환, 순서 있는 v2 명세, 포함 자산·그라디언트·격자 변환. 원본 별칭·개인 데이터 제외. 전체 스타일 변환은 미완료 |
| 참조 HWPML/PDF·그림 자산 추출 | 입출력: reference.export, 실행 관리: 기존 reference.capture | 원본 해시와 격리 수명주기 공통화. IMAGE가 참조한 Embedding만 추출, 연결/누락은 명시 |
| HWPML/HWPX 단위·표 속성 보정 | 구성: hwpctl.units, HWPX 검사 시 줄간격 종류 분리 | 문단 여백 1/2, hasMargin, repeatHeader 기본값 변환은 표본 검증 없이 전역화하지 않음 |
| 격자 역산 | 검증: reference.grid.solve_grid_tracks | 최빈값·하한·균등 분배·외곽 폭 스케일링을 채택하지 않음. 정확/정보 부족/모순을 구분 |
| 표 위치·페이지 흐름 | 다중 구역·중첩/병합 표 모델과 기존 네이티브 명령 연결 | 실제 작성 결과의 개체 순서·쪽 흐름 검증은 미완. 범용 자동 조판 엔진 아님 |
| safe 수동 릴리스 게이트 | safe 별도 PR의 scripts/native_release_gate.py와 테스트 | 개인 프로필·foreground 창 자동 선택 제거. native 문서만, 명시적 확인 및 수동 변경 확인. 실기 실행은 별도 |
| HAEON·포스터 작성 어댑터 | 문서별 실험 보관 | 개인 템플릿·좌표·소스 부분 실행 의존. 글상자 조합을 실제 표로 분류하지 않음 |
| 구형 복제본 및 옛 native 브랜치 | 후속 중복 감사 | .research-hwpctl, 옛 native 브랜치의 추가 패치 동등성 판정 필요. 새 기능으로 간주하여 재적용하지 않음 |

별도 HAEON 웹 편집기는 엔진과 합치지 않는다. archive/output/캐시는 산출물·보관·
실행 부산물이다. 미커밋 hangul.py 줄바꿈 표시, 기존 작업트리와 개인 문서는 그대로 둔다.

다음 승격 우선순위는 **FAQ 작성 명세 어댑터의 손실 검증 → 복잡 병합/페이지 흐름의
최소 재현 → 기본값·단위 변환의 형식별 증거**다. 이름이나 파일 존재만으로 승격하지 않는다.
사용법·계층 연결은 [작성·분석 안내](HWPX_AUTHORING.md)에 있다.
