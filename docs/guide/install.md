# 설치

[← README](../../README.md) · [문서 목록](../README.md)

## 요구 사항

- Windows 10/11
- 한글 2022 (검증 빌드 `12.0.0.850`)
- [Python 3.10 이상](https://www.python.org/downloads/) — 설치할 때 **Add Python to PATH**를 켭니다.
- Git (GitHub에서 바로 설치할 때)

## 권장: 전용 가상환경에 고정 설치

MCP 클라이언트는 `hwpctl.exe`를 서버로 띄워 둡니다. 실행 중인 서버는 `hwpctl.exe`를 잠그므로,
소스 폴더에 묶이는 `pip install -e`(editable) 설치를 실행 환경으로 쓰면 재설치 중에 가상환경이
깨질 수 있습니다. 사용자는 **소스와 분리된 전용 가상환경**에 일반 설치를 권장합니다.

```bat
py -3.13 -m venv C:\hwpctl\venv
C:\hwpctl\venv\Scripts\python -m pip install "hwpctl[windows] @ git+https://github.com/Jasujung99/hwpctl@main"
```

- `windows` extra는 `pywin32`를 설치합니다. 검증 기준 백엔드는 `win32com`입니다.
- 설치 위치는 바꿔도 됩니다. 클라이언트 설정에는 그 위치의 `hwpctl.exe` 절대 경로를 씁니다.

## 연결 확인

한글 2022에서 문서를 하나 열어 둔 뒤:

```bat
C:\hwpctl\venv\Scripts\hwpctl doctor
C:\hwpctl\venv\Scripts\hwpctl status
```

- `doctor`는 응답 없는 한/글, 떠 있는 대화상자, 고정 창 상태 등을 읽기 전용으로 점검합니다.
- 처음 파일 열기·저장 때 보안 모듈(`FilePathChecker`) 대화상자가 뜨면 허용합니다. `hwpctl`이
  연결할 때 모듈을 등록합니다.
- 한/글이 없거나 Windows가 아니면 스택 없이 한국어 오류와 종료 코드 3으로 실패합니다.

```
한/글(한글 오피스)을 찾을 수 없습니다. 이 컴퓨터에 한글 2022가 설치되어 있고 Windows에서 실행 중인지 확인하세요. ...
```

다음 단계: [클라이언트 연결](clients.md)

## 업데이트

1. 이 hwpctl을 쓰는 **모든 MCP 클라이언트를 종료**합니다(Claude Code, Codex, Cursor 등).
   서버가 떠 있으면 `hwpctl.exe`가 잠겨 설치가 중간에 실패합니다.
2. 같은 명령에 `--upgrade`를 붙여 다시 설치합니다.

```bat
C:\hwpctl\venv\Scripts\python -m pip install --upgrade "hwpctl[windows] @ git+https://github.com/Jasujung99/hwpctl@main"
```

## 선택 extra

| extra | 설치되는 것 | 용도 |
|---|---|---|
| `windows` | pywin32 | 한글 2022 COM 편집 (필수) |
| `hwpx` | python-hwpx | 한글 없이 `.hwpx` 읽기·작성 (`hwpx_status`, `hwpx_inspect`, HWPX 작성 경로) |
| `pyhwpx` | pyhwpx | 선택. 창을 고정하기 전 연결(`open --new` 등)에서만 쓰입니다. 고정한 창의 편집은 항상 `win32com` |

여러 개를 함께 설치할 때는 `hwpctl[windows,hwpx]`처럼 씁니다.

## 한글 없이 `.hwpx`만 쓸 때

`.hwpx` XML을 한/글 없이 읽고 조립하는 계층은 Linux에서도 동작합니다.

```bash
python -m pip install "hwpctl[hwpx] @ git+https://github.com/Jasujung99/hwpctl@main"
hwpctl hwpx_status
hwpctl hwpx_inspect sample.hwpx
```

참조 문서를 작성 명세로 바꾸는 `reference_to_spec`과 명세로 새 문서를 만드는 `build_document`는
실험 기능입니다. [HWPX 작성](hwpx-authoring.md)을 보세요.

## 개발용 설치

소스를 고치며 테스트하는 개발 환경(editable 설치)은 [기여 안내](../../CONTRIBUTING.md)를 따릅니다.
개발용 가상환경을 MCP 실행 환경으로 함께 쓰지 마세요.
