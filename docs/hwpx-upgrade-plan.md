# HWPX 업그레이드 계획 — 한글 없이 조립하기

조사 결론([research-hwp-without-hangul.md](research-hwp-without-hangul.md))을
따른다. **1차 엔진은 `python-hwpx`**, `hwpctl` COM 은 **선택적 실물 확인**이다.

검증한 패키지: **`python-hwpx` 6.3.0** (PyPI, Apache-2.0, Python ≥3.10, 의존성 `lxml`).
6.x 고수준 이름(`HwpxDocument.open` / `new` / `add_paragraph` / `add_table` /
`styles.ensure_font` / `styles.ensure_run` / `save_to_path(..., mode="patch")`)을 쓴다.
7.0에서 5.x 호환 shim 이 제거될 수 있어 extra 는 `python-hwpx>=6.3,<7` 로 묶는다.
`python-hwpx-automation` 은 양식 채움·별도 MCP 용이며 **지금은 넣지 않는다**.

```mermaid
flowchart LR
    A["fixtures 텍스트·원본 PNG"] --> B["hwpctl.hwpx.write<br/>OWPML 서식 라운드트립"]
    B --> C["rebuild_p1.hwpx"]
    C --> D["hwpx_inspect 가 진실"]
    D --> E["선택: Pillow 비교 시트"]
    E --> F["선택: 한글 2022 창 확인"]
```

## 현재 상태 (품질 패스)

Pillow 시트를 예쁘게 만드는 것이 목표가 아니다. **한/글이 열 때 원본에 가깝게
보이도록 OWPML 에 서식이 실제로 남는지** 를 `hwpx_inspect` 로 잰다.

- `ensure_run_style` 이 `styles.ensure_font` 를 먼저 호출한다. 스켈레톤에 없는
  `휴먼명조` / `HY헤드라인M` 이 header.xml 에 선언된다.
- 표 셀 문단은 `document.paragraphs` 밖에 있어 `styles.apply_paragraph_format`
  이 무시하던 정렬·줄간격을 `header.ensure_paragraph_format` + `paraPrIDRef`
  로 단다.
- 크림 채움은 원본과 같은 `#FCF5E7`.
- `scripts/recreate_gongo.py` 기본은 **1쪽만** `rebuild_p1.hwpx`. 4쪽 이후는
  만들지 않는다. `--pages 1,2,3` 은 같은 엔진을 2–3쪽에 적용할 때만.
- 쪽 PNG 는 HWPX XML 근사(Noto CJK). 한글 래스터·LibreOffice `hwpfilter` 없음.
- 기존 `hangul.py` / Engine COM 은 그대로. 한글 2024 GSG 없음.

Linux 에서 재현:

```bash
pip install -e ".[hwpx]"
hwpctl --backend auto hwpx_status
python scripts/recreate_gongo.py --out artifacts/gongo
hwpctl hwpx_inspect artifacts/gongo/rebuild_p1.hwpx
hwpctl hwpx_compare artifacts/gongo/rebuild_p1.hwpx \
  --orig-dir fixtures/gongo --out-dir artifacts/gongo
pytest
```

바이너리 `fixtures/gongo/doc1.hwp` → `.hwpx` 변환은 이 환경에서 검증된
변환기를 쓰지 않았다. `gongo_pages.json` 과 `orig_p1.png` 로 처음부터 조립한다.

## 1쪽 품질 — inspect 가 보장하는 것

| 항목 | OWPML |
|---|---|
| 제목 페이스 | `HY헤드라인M` |
| 본문·기한·일자 | `휴먼명조` |
| 서문 정렬 | `JUSTIFY`, 줄간격 160% |
| 일자/이사장 | `RIGHT` |
| 간단소개 헤더 | 표 셀 채움 `#FCF5E7` |
| 기한 `7. 3(금) 16시까지` | 같은 문단의 부분 런, `#FF0000` + 밑줄 |
| URL `sbiz24.kr` | 파란 밑줄 런 |

## python-hwpx 가 아직 표현하지 못하는 것

정직하게 적는다. 아래는 한/글 원본에 있으나 이 쓰기 경로로는 만들지 않는다.

- 구역 헤더의 **갈매기/빗금(chevron·hatch) 도형**. `add_shape` 는 깨진 파일을
  만들 수 있어 쓰지 않는다. 크림 배경 표 `[번호 \| 제목]` 으로 대체한다.
- 한/글 2022 가 그리는 **정확한 래스터**(커닝, 함초롬/휴먼 힌팅, 줄 나눔).
  Linux Pillow 시트는 Noto CJK 대체이며 품질 판정이 아니다.
- 원본의 **정확한 자간·장평·금칙** 수치. 공개 API 로 맞추지 않았다.
- 4쪽 이후 표·도식. 이 패스는 1쪽(선택 2–3쪽)만.

## 하지 않는 것

- COM 경로 재작성, `hangul.py` 삭제
- `.hwp` 바이너리 쓰기
- LibreOffice `hwpfilter` 변환
- `python-hwpx` 포크/벤더링
- 한글 2024 GSG
- 4–29쪽 확장 (PR #12 골격 초안과 분리)
