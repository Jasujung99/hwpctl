# 기여 안내

`hwpctl`은 실제 한글 문서를 다루므로 기능 정확성과 데이터 보호를 같은 우선순위로
다룹니다.

## 개발 환경

한글이 없는 환경에서도 파서, 잠금, MCP 도구와 COM 스텁 테스트를 실행할 수 있습니다.

```bash
python -m pip install -e ".[dev]"
pytest
hwpctl mcp --list-tools
hwpctl hwpx_status
```

한/글이 없거나 Windows가 아니면 `hwpctl status`는 스택 없이 한국어 오류와 종료 코드 3으로
끝나야 합니다. CI의 `linux-contract` job이 이 계약을 고정합니다.

`.hwpx` 준비 계층만 쓰려면 `pip install -e ".[hwpx]"` 로도 충분합니다. 한/글은
필요 없습니다.

개발용(editable) 가상환경을 MCP 클라이언트의 실행 환경으로 함께 쓰지 마세요. 서버가 떠 있으면
`hwpctl.exe`가 잠겨 `pip install -e` 재설치가 가상환경을 깨뜨릴 수 있습니다. 실행 환경은
[설치 가이드](docs/guide/install.md)처럼 소스와 분리된 가상환경에 일반 설치합니다.

저장소 구조:

```text
hwpctl/           엔진·CLI·MCP 서버
hwpctl/hwpx/      한글 없는 .hwpx 읽기·작성 (python-hwpx)
hwpctl/authoring/ 실험적 작성 명세·변환 (reference_to_spec, build_document)
examples/         MCP 클라이언트 설정과 Engine 직접 호출 예제
tests/            파서·잠금·COM 스텁·HWPX XML·공개 문서 검사 (실기 테스트는 opt-in)
docs/guide/       사용자 가이드
docs/dev/         통합 대장·검증 기록·릴리스 체크리스트 등 개발 문서
docs/research/    조사 문서
```

Windows와 한글 2022에서 실기 확인하려면 별도 가상환경에 다음을 설치하세요.

```bat
py -m pip install -e ".[windows,dev]"
```

표 격자·중첩 표처럼 COM 스텁만으로 확정할 수 없는 변경은, 사용자 문서가 아닌
별도 `DispatchEx` 빈 문서를 쓰는 opt-in 실기 회귀도 실행합니다. 이 테스트는 저장하지
않고 만든 한/글 인스턴스를 닫습니다.

```bat
set HWPCTL_RUN_HANGUL_INTEGRATION=1
pytest tests/test_hangul_live_integration.py
```

## 변경 원칙

- `main`에 직접 푸시하지 않고 작은 작업 브랜치와 PR을 사용합니다.
- 한글 없는 환경의 전체 테스트와 패키지 빌드가 통과해야 합니다.
- 실제 한글을 건드리는 변경은 개인정보 없는 복사본에서 검증하고, 사용한 한글 빌드와
  절차를 PR에 기록합니다.
- 원본 덮어쓰기, 닫기, 큰 범위 삭제처럼 되돌리기 어려운 동작은 명시적 확인이나 플래그를
  요구해야 합니다.
- MCP 도구 설명에는 대상, 부작용, 거부 조건을 AI가 이해할 수 있게 적습니다.
- 새 네트워크 연결이나 외부 서비스는 신뢰 경계와 안전한 기본값을 함께 문서화합니다.

## 문서

- 사용자에게 보이는 동작이 바뀌면 [사용 가이드](docs/guide/)와 [CHANGELOG](CHANGELOG.md)를
  같은 PR에서 고칩니다.
- MCP 도구를 추가·변경·삭제하면 [도구 레퍼런스](docs/guide/tools.md) 표를 `hwpctl.tools`
  순서대로 갱신합니다. README의 대표 도구 표는 실제 도구 이름만 쓸 수 있고 한국어·영어 표가
  같아야 합니다. 모두 `scripts/validate_public_files.py`와 테스트가 검사합니다.
- README는 한국어 절 아래에 영어 절을 둡니다. 두 절의 내용을 함께 고칩니다.
- 통합 기록·실측 노트는 [docs/dev](docs/dev/)에 둡니다.

## 개인정보와 테스트 자료

실제 이력서·계약서·주민번호·주소·연락처가 든 문서, 토큰, 로컬 MCP 설정, 사용자명이나
절대 경로가 포함된 로그·스크린샷은 커밋·Issue·PR에 올리지 마세요. 테스트에는 새로 만든
빈 문서나 익명화한 합성 데이터를 사용합니다. HWP/HWPX 파일은 기본적으로 Git에서
제외됩니다.

## Issue와 PR

버그에는 Windows·한글·Python·pywin32(설치했다면 `pyhwpx`) 버전, 사용한 명령, 개인정보 없는 최소 재현 절차를
포함해 주세요. 보안 문제는 [SECURITY.md](SECURITY.md)의 비공개 신고 절차를 따릅니다.
PR은 제공된 체크리스트를 작성하고 CI 실패나 리뷰 대화를 모두 해결한 뒤 병합합니다.
