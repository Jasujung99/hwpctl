# HWPX 업그레이드 계획 — 한글 없이 조립하기

조사 결론([research-hwp-without-hangul.md](research-hwp-without-hangul.md))을
따른다. **1차 엔진은 `python-hwpx`**, `hwpctl` COM 은 **선택적 실물 확인**이다.
이 문서는 단계만 고정한다. 복잡한 공고문 재현은 **다음 단계**이지 현재 PR이 아니다.

검증한 패키지: **`python-hwpx` 6.3.0** (PyPI, Apache-2.0, Python ≥3.10, 의존성 `lxml`).
6.x 고수준 이름(`HwpxDocument.open` / `new` / `add_paragraph` / `add_table` /
`styles.ensure_run` / `save_to_path(..., mode="patch")`)을 쓴다.
7.0에서 5.x 호환 shim 이 제거될 수 있어 extra 는 `python-hwpx>=6.3,<7` 로 묶는다.
`python-hwpx-automation` 은 양식 채움·별도 MCP 용이며 **지금은 넣지 않는다**.

```mermaid
flowchart LR
    A["원본 .hwpx"] --> B["hwpx_inspect<br/>서식 그룹"]
    B --> C["python-hwpx 조립"]
    C --> D["쪽 이미지 비교"]
    D --> E["선택: hwpctl open<br/>한글 2022 확인"]
```

## 1단계 — 준비 (이 PR)

- extra `hwpx`: `pip install -e ".[hwpx]"` — Linux CI 에서 한/글·pywin32 없이 설치.
- 패키지 `hwpctl/hwpx/`: `document` · `inspect` · `write` · `compare`.
- 읽기 명령 `hwpx_status` / `hwpx_inspect` — **COM·SingleWriterLock 없음**.
- `write.py` 는 문단·런 서식·표 채움의 얇은 래퍼만. CLI 쓰기 명령은 아직 없다.
- `compare.py` 는 이미 사전 렌더된 PPM(P6) 쪽 이미지의 픽셀 차이·diff·overlay를
  계산하는 라이브러리 API `compare_page_images(...)`를 제공한다. PDF/HWPX를 PPM으로
  렌더하는 파이프라인과 CLI/MCP 래퍼는 아직 없다.
- 기존 `hangul.py` / Engine COM 명령은 그대로.

Linux 에서 읽기만 확인:

```bash
pip install -e ".[hwpx]"
hwpctl hwpx_status
hwpctl hwpx_inspect 샘플.hwpx
```

## 2단계 — 원본 검사 (다음)

대상 공고문을 `.hwpx` 로 두고 `hwpx_inspect` 로 문단·런·셀 채우기 그룹
(정렬, 글꼴, 크기, 굵게, 색, 셀 배경, `paraPr`/`charPr`/`borderFill` id)을 고정한다.
쓰기는 이 그룹을 **상속**한 뒤에만 한다.

## 3단계 — 조립 (다음)

`insert_paragraph` / `set_run_props` / `create_table_and_fill` 로 초안을 만들고
`save_document(..., mode="patch")` 로 손대지 않은 파트를 보존한다.
`add_shape` / `add_control` 같은 저수준 API 는 쓰지 않는다.

## 4단계 — 렌더 파이프라인과 공개 시각 비교 (다음)

원본·결과를 같은 렌더러와 DPI로 PPM(P6) 쪽 이미지로 만든 뒤
`compare_page_images(...)`에 넘기는 현재 라이브러리 API를 CLI/MCP 작업 흐름으로
연결한다. 한/글 렌더가 없으면 비-Hancom 렌더러 파일럿만 허용한다.

## 5단계 — 선택적 `hwpctl open` (다음)

Windows + 한글 2022 가 있을 때만 실물 창에서 확인·미세 조정한다.
자동저장 동작은 바꾸지 않는다. 한글 2024 GSG API 는 쓰지 않는다.

## 이 PR 에서 하지 않는 것

- COM 경로 재작성, `hangul.py` 삭제
- 공고문 전체 재현 스크립트
- `.hwp` 바이너리 쓰기
- `hwpx_inspect` 이외의 HWPX 쓰기 CLI/MCP 명령
- PDF/HWPX → PPM 렌더 파이프라인과 쪽 이미지 비교 CLI/MCP 명령
