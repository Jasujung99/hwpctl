# 제3자 구성요소 고지

이 저장소의 MIT 라이선스는 `hwpctl` 자체 코드에 적용됩니다. 설치 과정에서 함께 사용하는
아래 소프트웨어와 패키지는 각 프로젝트의 라이선스와 이용 조건을 따릅니다.

| 구성요소 | 용도 | 프로젝트 |
|---|---|---|
| 한글 오피스 | 대상 문서 편집기와 자동화 인터페이스 | <https://www.hancom.com/> |
| pyhwpx | 한글 자동화 Python 래퍼 | <https://github.com/martiniifun/pyhwpx> |
| python-hwpx | 한글 없이 HWPX(OWPML)를 읽고 쓰는 순수 파이썬 라이브러리 (선택 extra `hwpx`) | <https://github.com/airmang/python-hwpx> |
| Pillow | HWPX 쪽 PNG 근사 렌더와 원본 비교 시트 (선택 extra `hwpx`) | <https://python-pillow.org/> |
| pywin32 | Windows COM 접근 | <https://github.com/mhammond/pywin32> |
| MCP Python SDK | MCP 서버 | <https://github.com/modelcontextprotocol/python-sdk> |
| AnyIO | 비동기 작업과 워커 | <https://github.com/agronholm/anyio> |
| Starlette · Uvicorn | 선택적 로컬 HTTP 전송 | <https://github.com/encode/starlette> · <https://github.com/encode/uvicorn> |

배포 전에 잠긴 의존성 버전의 패키지 메타데이터와 라이선스 원문을 다시 확인하세요.
한글은 이 저장소에 포함되지 않으며 사용자가 별도로 유효한 라이선스를 준비해야 합니다.
