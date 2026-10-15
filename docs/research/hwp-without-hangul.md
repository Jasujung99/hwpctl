# 한글 2022 없이 HWP/HWPX 열고 고치기 — 조사 보고서

> 리서치 전용 문서입니다. `hwpctl` 런타임 코드는 이 PR에서 바꾸지 않습니다.
> 조사일: 2026-09-01. 별표·포크·마지막 커밋 시각은 GitHub REST API(`gh api repos/...`)로
> 직접 조회한 값이며, 프로젝트 자체 마케팅 문구의 수치는 별도로 표시했습니다.

## 0. 왜 이 조사를 하는가

`hwpctl`은 **열려 있는 한글 2022 창**을 `pyhwpx`/`win32com`으로 조작하는 COM 브리지입니다.
표에 `TreatAsChar` 개체가 섞이거나 쪽 레이아웃이 복잡한 실제 공고문(관공서 고시문 등)을
COM 자동화로 처음부터 재현하려 하면, 키 입력·다이얼로그·Undo 단위가 얽혀 느리고 깨지기
쉽습니다. 이 문서는 **한글 2022 설치 없이** `.hwp`/`.hwpx`를 읽고 고칠 수 있는 대안이
있는지, 있다면 어느 것이 "복잡한 공고문 재현"에 실전으로 쓸 만한지를 정리합니다.

**결론 먼저:** 완전한 대체재는 아직 없습니다. 다만 **`.hwpx`를 목표 포맷으로 잡고
Python으로 XML을 직접 다루는 방식**(`python-hwpx`)이 지금 가장 실전에 가깝고,
`hwpctl`과는 경쟁이 아니라 **보완** 관계로 조합하는 것이 현실적입니다(§5 참고).

---

## 1. hwpx (OWPML/OOXML형) 라이브러리

`.hwpx`는 ZIP + XML(OWPML, 한국산업표준 KS X 6101) 구조라 원리상 순수 언어 구현이
가능합니다. 한글 2022는 **한글 2010 이후 버전**이면 `.hwpx`로 저장할 수 있으므로,
"한글에서 한 번 hwpx로 내보낸 뒤 이후 편집은 Hancom 없이" 흐름이 성립합니다.

| 이름 | 언어 | 라이선스 | 포맷 | 읽기/쓰기 | 표·이미지·쪽 서식 | OS | 성숙도(★는 GitHub API 실측) | 우리 용도 적합성 |
|---|---|---|---|---|---|---|---|---|
| [python-hwpx](https://github.com/airmang/python-hwpx) | Python | Apache-2.0 | hwpx만 | 읽기✅/쓰기✅ | 표·이미지·머리글/바닥글·각주·줄간격·여백·쪽번호 O | Linux/Mac/Win/CI | ★108, fork 38, 마지막 푸시 2026-08-22. 2025-09 시작, PyPI 71릴리즈로 활발 | **가장 근접**. "손댄 곳만 바뀌고 나머지 바이트 보존" 저장 계약, `MutationReport`로 저장 실패를 명시적으로 알려줌(표 줄바꿈처럼 `hwpctl layout_review`가 지금 수작업으로 하는 일부를 대체 가능) |
| [python-hwpx-automation](https://github.com/airmang/python-hwpx-automation) | Python | Apache-2.0 | hwpx | 읽기✅/쓰기✅(양식 채움 특화) | 위와 동일 + mail merge, 목차 | 동일 | ★67, fork 23, 2026-08-24 | `hwpx-mcp-server`로 MCP 노출 — `hwpctl`처럼 AI 클라이언트에 도구로 연결 가능 |
| [neolord0/hwpxlib](https://github.com/neolord0/hwpxlib) | Java | Apache-2.0 | hwpx | 읽기✅/쓰기✅ | 표·이미지·쪽 서식 O(저수준 OWPML 엘리먼트 단위) | JVM 있는 모든 OS | ★181, fork 49, 2026-08-31(활발). 2023년 시작, 가장 오래·널리 참조됨 | Python 생태계 밖(JVM 필요)이지만 **레퍼런스 구현**. `python-hwpx`도 오라클 코퍼스로 이 라이브러리를 인용 |
| [hancom-io/hwpx-owpml-model](https://github.com/hancom-io/hwpx-owpml-model) | C++ | Apache-2.0 | hwpx | 읽기✅/쓰기 부분적(엘리먼트 추출·저장 예제만) | 저수준 모델만, 고수준 문서 API 없음 | Windows(VS2017 빌드 전제) | ★37, fork 12, **마지막 푸시 2023-10-24**(3년 정체) | 한컴이 공개한 **공식 참조 모델**. 스펙 검증용으로는 가치 있으나 그 자체로 제품화하기엔 API가 너무 저수준이고 유지보수가 멈춰 있음 |
| [jakal-hwpx](https://github.com/Ahnd6474/jakal-hwpx) | Python | MIT | hwpx + hwp(바이너리도) | 읽기✅/쓰기✅ 주장(`write_to_hwp`까지) | 표·수식·이미지·각주 O | Linux/Mac/Win | ★12, fork 2, 마지막 푸시 2026-06-08(약 3개월 정지) | 설계는 흥미(계층 분리: `HancomDocument`/`HwpxDocument`/`HwpDocument`)하나 채택 사례·이슈 트래킹이 거의 없어 **파일럿 검증 필수** |

**주의할 점:** `python-hwpx` 저장소의 "한컴 열림 120/120", "렌더 검증 476/476" 같은 수치는
**자체 측정치**(README/PyPI 페이지에 프로젝트가 직접 기재)이며 제3자 검증이 아닙니다.
실제 도입 전에는 우리 쪽 공고문 샘플로 반드시 재현 테스트를 해야 합니다.

---

## 2. 레거시 `.hwp` 바이너리 (Compound File Binary)

`.hwp`는 MS-CFB(OLE2) 컨테이너에 압축된 레코드 스트림입니다. 텍스트 추출은 여러 구현체가
있지만, **깨지지 않게 다시 쓰는 것**은 스트림 길이가 바뀌면 디렉터리 트리 전체를 재계산해야
해서 근본적으로 더 어렵습니다.

| 이름 | 언어 | 라이선스 | 읽기/쓰기 | 비고 | 성숙도 |
|---|---|---|---|---|---|
| [pyhwp / hwp5](https://github.com/mete0r/pyhwp) | Python 2/3 | **AGPL-3.0-or-later** | 읽기✅ / 쓰기❌ (odt·txt로 실험적 변환만) | `olefile` + `zlib`로 스트림 해석. 사실상 **hwp5 파서의 표준**이지만 표 셀 구조·이미지·문단 계층까지는 못 뽑음 | ★301, fork 73, open issue 87개. 최근에도 가끔 푸시되지만 핵심은 오래된 코드베이스 |
| [neolord0/hwplib](https://github.com/neolord0/hwplib) | Java | Apache-2.0 | 읽기✅/쓰기✅ | hwp.js, hwp2hwpx 등이 기반으로 삼는 **자바 진영의 사실상 표준**. 표·글자모양·문단모양까지 조작 가능 | ★588, fork 191, 2026-08-19(활발) |
| [hahnlee/hwp.js](https://github.com/hahnlee/hwp.js) | TS/JS | Apache-2.0 | 읽기✅ / 쓰기❌(뷰어) | 브라우저에서 hwp를 렌더링하는 **가장 널리 알려진 웹 뷰어**. hwplib을 참고해 포팅 | ★1305, fork 108, **마지막 푸시 2025-01-10**(약 1년 8개월 정지 — 유지보수 느려짐) |
| [hwpkit](https://github.com/psychofict/hwpkit) (PyPI: `hwpkit`) | Python | MIT | 읽기✅ / 쓰기 주장(텍스트 교체·이미지=직인 삽입) | MS-CFB 디렉터리(red-black-tree) 전체를 재작성해 스트림 길이 변화를 처리한다고 설명 — 접근 자체는 올바르나 | ★1, 단일 관리자, 2026-05 시작. **실전 검증 이전 단계** |
| [syhwp](https://github.com/sysphere/syhwp) (PyPI: `syhwp`) | Python | MIT | 읽기✅ / 쓰기❌ | pyhwp의 AGPL 회피용 "클린룸" 재구현이라 주장. 텍스트/표/Markdown/HTML 추출 전용 | ★1, 2026-07 시작. 신생 |
| [edwardkim/rhwp](https://github.com/edwardkim/rhwp) (core) | Rust+WASM | MIT | 읽기✅ / 쓰기✅(HWP 편집 저장, HWPX/HML 보존 저장 주장) | HWP 5.0 + HWPX + HML 파싱, 표 셀 병합·테두리, treat-as-char, 페이지네이션까지 **범위가 가장 넓음**. CLI(`export-svg/png/pdf`, `dump`)와 MCP 서버(`rhwp mcp-serve`) 내장 | ★3768, fork 693, 2026-09-01(활발). **단, 2026-03 생성 후 약 5개월 만에 이 정도 트랙션은 이례적으로 빠른 성장이라 도입 전 라이선스·거버넌스·실사용 사례를 별도로 확인 권장** |

---

## 3. 변환기 (hwp → hwpx / docx / odt / pdf)

편집이 아니라 "일단 열어서 보거나 다른 포맷으로 바꾸는" 경로입니다. 편집 후 되돌리는
왕복(round-trip)은 대부분 **손실**이 있습니다.

| 이름 | 방식 | 손실 여부 | 비고 |
|---|---|---|---|
| LibreOffice 내장 `hwpfilter` | 바이너리 hwp 직접 파싱 | **위험**: 최신 포맷을 "조용히 손상"시키는 알려진 버그 [tdf#70097](https://bugs.documentfoundation.org/show_bug.cgi?id=70097). [공식 문서](https://docs.libreoffice.org/hwpfilter.html)도 "새 포맷을 제대로 처리 못 함"이라고 명시 | HWP97급 구버전만 안전. **최신 hwp/hwpx 재현에는 부적합** |
| [H2Orestart](https://github.com/ebandal/H2Orestart) (LibreOffice 확장) | hwp/hwpx → ODT 임포트 필터, headless PDF 변환 지원 | 중간(복잡한 표·개체 손실 사례 다수 보고) | ★192, fork 17, 2026-08-30(활발). `soffice --headless --infilter="Hwp2002_File" --convert-to pdf`로 **CI/Docker에서 무설치 변환** 가능. 사실상 **Linux 진영에서 가장 널리 쓰이는 무료 경로** |
| [neolord0/hwp2hwpx](https://github.com/neolord0/hwp2hwpx) | hwplib 기반, hwp→hwpx 순변환 | 낮음(같은 저자 라이브러리 간 변환) | Apache-2.0, ★60, 2026-08-31 활발. hwp를 hwpx로 바꿔 이후 `python-hwpx`/`hwpxlib`로 편집하는 **2단계 전략**의 핵심 다리 |
| [ratiertm/pyhwpxlib](https://github.com/ratiertm/pyhwpxlib) | hwp2hwpx/hwplib을 Python으로 포팅 | 낮음(포팅 원본과 동일) | **라이선스 혼재**: 포팅된 변환 파일(`hwp2hwpx.py` 등)만 Apache-2.0, **나머지 전부 BSL 1.1**(개인/비영리/오픈소스는 무료, 상업적 이용은 유료 라이선스 필요). 공공기관 공고문을 유상 용역으로 재현한다면 반드시 확인 |
| 한컴 통합문서뷰어(문서변환 API) — [developer.hancom.com](https://developer.hancom.com/docsconverter/guide/api) | 한컴 자체 서버 엔진, `doc2pdf`/`doc2jpg` REST API | 가장 낮음(한컴 자체 엔진) | **상용/설치형**. CentOS 7 / RHEL 8.6 / Ubuntu 20.x + Docker 지원, 포트 8101/HTTP API. **"한글 2022 데스크톱"은 필요 없지만 한컴 제품 구매·라이선스는 필요** — "한컴 종속 완전 제거"가 목표라면 이 항목은 절반만 해당 |
| Microsoft Word `BATCHHWPCONV.exe` | MS 제공 HWP 5.0 필터 | 중간 | Windows 전제라 이번 조사 목적(Hancom-free, OS 무관)과는 거리가 있어 참고만 |

---

## 4. 서버 / 헤드리스 / Docker

| 이름 | 구성 | 비고 |
|---|---|---|
| [jacepark12/hwp-converter-api](https://github.com/jacepark12/hwp-converter-api) | Ubuntu + LibreOffice + H2Orestart + FastAPI, `POST /convert` | ★2, fork 2, 2025-08 마지막 푸시(약 1년 정지). Palantir Foundry 컨테이너 규격에 맞춰 만들어졌지만 **Dockerfile 자체는 범용**으로 재사용 가능. hwp/hwpx → pdf/docx |
| [Gotenberg](https://github.com/gotenberg/gotenberg) | Docker API, LibreOffice 기반 오피스→PDF 변환 | ★12,981, fork 847, 2026-08-31(매우 활발). **hwp를 기본 지원하지 않음** — 내부 LibreOffice에 H2Orestart를 얹어야 hwp 처리 가능. 범용 문서 변환 인프라로는 최상급 |
| 한컴 통합문서뷰어 | 위 §3 참고 | Docker 지원 공식 언급되지만 상용 |

**직접 만들어야 하는 조합:** 지금 시점에 "무료 + Docker + hwp/hwpx 지원"을 다 만족하는
완성형 오픈소스 서버는 없고, **LibreOffice + H2Orestart를 자체 컨테이너로 감싸는 것**이
가장 현실적인 헤드리스 경로입니다(`jacepark12/hwp-converter-api`의 Dockerfile이 좋은 출발점).

---

## 5. 법률 / 라이선스

- **한컴의 공개 문서**: 한컴은 2010년 HWP 5.0 바이너리 스펙과 HWPML을 공개했고, OWPML은
  한국산업표준 **KS X 6101:2011**로 제정되었습니다.
  ([한컴 공식 배포처](https://www.hancom.com/support/downloadCenter/hwpOwpml),
  [스펙 원문 PDF](https://cdn.hancom.com/link/docs/%ED%95%9C%EA%B8%80%EB%AC%B8%EC%84%9C%ED%8C%8C%EC%9D%BC%ED%98%95%EC%8B%9D_5.0_revision1.3.pdf))
  다만 완전한 퍼블릭 도메인은 아닙니다:
  - 스펙 문서 자체는 "열람은 누구나 가능, 배포는 원본 그대로만" 조건.
  - 스펙을 근거로 만든 **결과물의 저작권은 개발자에게** 있다고 명시하지만,
    **"본 제품은 한글과컴퓨터의 글 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다"**
    라는 문구를 UI·매뉴얼·소스에 표기해야 합니다.
  - 한컴은 "이 공개 문서로 얻은 결과를 근거로 한컴을 상대로 독점적·배타적 권리를
    행사하려는 자"에게는 **적극적으로 대응(권리 행사)할 수 있다**고 명시 — 즉
    특허/독점권 주장 목적이 아니라면 실무 개발에는 안전하지만, "한컴을 상대로 한
    독점권 주장"만 명확히 배제된 조건부 공개입니다.
  - "Hangul", "한컴", "HWP", "HWPX"는 등록 상표 — 커뮤니티 프로젝트들이 공통적으로
    "한컴과 제휴·후원·승인 관계 없음"을 명시하는 이유입니다. `hwpctl`도 README에 이미
    동일한 취지의 비제휴 고지를 두고 있습니다.
- **pyhwp/hwp5 = AGPL-3.0-or-later**: 서버에서 이 라이브러리를 네트워크로 서비스하면
  결과물도 AGPL 조건(소스 공개 의무)이 전이될 수 있습니다. 상용·비공개 백엔드에
  넣기 전 라이선스 검토가 필요합니다.
- **pyhwpxlib = Apache-2.0 + BSL 1.1 혼재**: 위 §3 참고. 상업적 이용은 유료.
- **rhwp(core)/hwp.js/hwplib/hwpxlib/python-hwpx 계열 = MIT 또는 Apache-2.0**: 상업적
  이용에 제약이 없는 허용적 라이선스입니다. 다만 라이선스가 자유롭다는 것과 "안정적으로
  동작한다"는 것은 다른 문제이므로 §1·§2의 성숙도 칸을 함께 봐야 합니다.
- **한컴 통합문서뷰어 = 상용 SDK**: 구매·계약 필요. 안전하지만 "무료·오픈소스" 조건과는
  맞지 않습니다.

---

## 6. 최종 순위 추천

### 🥇 1위 — `python-hwpx` (+ `python-hwpx-automation`)

- <https://github.com/airmang/python-hwpx> · Apache-2.0 · Python 3.10+
- **왜 1위인가**: (1) `hwpctl`과 같은 언어(Python)라 통합 마찰이 적음. (2) 목표 포맷이
  `.hwpx`인데, 한글 2022에서 `save_as`로 이미 `.hwpx` 저장이 가능하므로 **"한글에서 최초
  1회 hwpx로 내보내고, 이후 반복 수정은 Hancom 없이"** 흐름이 지금 당장 성립. (3) "손댄
  부분만 바꾸고 나머지는 바이트 보존" 저장 계약과 실패 시 아무것도 쓰지 않는 fail-closed
  설계가, `hwpctl`이 `layout_review`로 수동 보정해야 했던 문제(표 줄바꿈, 셀 여백)의
  근본 원인 — "자동화 도구가 문서를 조용히 깨는 것" — 을 구조적으로 줄여줌. (4) `mail
  merge`/폼 필드 채우기 API가 있어 반복되는 공고문 양식 재현에 바로 쓸 수 있음.
  (5) 활발한 릴리즈 주기(PyPI 71개 릴리즈, 최근 푸시 2026-08-22).
- **한계**: `.hwp` 바이너리는 지원하지 않음(반드시 `.hwpx`로 변환 후 사용). Alpha 단계로
  API가 바뀔 수 있음. 커뮤니티 규모가 아직 작음(★108) — 실제 배포 전 우리 공고문 코퍼스로
  파일럿 필수. `add_shape`/`add_control` 같은 저수준 API는 경고만 내고 깨진 파일을 만들 수
  있어 고수준 API(`add_table`, `add_paragraph`, `fill_by_path`) 위주로 써야 함.

### 🥈 2위(대안) — `neolord0/hwplib` + `hwpxlib` (Java) 조합, 또는 `edwardkim/rhwp` (Rust/WASM)

- **하이브리드 전략용**: <https://github.com/neolord0/hwplib> ·
  <https://github.com/neolord0/hwpxlib> · 둘 다 Apache-2.0.
  Python 생태계 밖(JVM 필요)이지만 **가장 오래되고(2016~), 가장 널리 인용되는** 레퍼런스
  구현입니다. `hwp2hwpx`로 레거시 `.hwp`를 `.hwpx`로 옮긴 뒤 1위 도구로 넘기는 **다리
  역할**로 가장 적합합니다. subprocess로 JVM을 호출하는 형태라 `hwpctl`의 CLI 철학과도
  잘 맞습니다.
- **엔진 대체용(더 실험적)**: <https://github.com/edwardkim/rhwp> · MIT · Rust+WASM.
  표 셀 병합/테두리, treat-as-char, 페이지네이션, 머리말/꼬리말 홀짝 분리까지
  구현 범위가 가장 넓고, `export-pdf`/`export-svg` CLI로 `hwpctl`의 "화면에서 즉시
  확인" 워크플로에 준하는 **비-Hancom 시각 검증**이 가능합니다. 다만 v0.8.x(pre-1.0)
  단계이고, 생성 후 약 5개월 만에 ★3,768·fork 693이라는 이례적으로 빠른 성장을 보이는
  프로젝트라 — 악의적이라는 근거는 없지만 — **독립적으로 검증(라이선스 조건, 실제 배포
  사례, 이슈 대응 속도)한 뒤 소규모 파일럿으로 시작**할 것을 권장합니다.

---

## 7. 사용하지 말 것 (Do-Not-Use) 목록

| 대상 | 문제 | 대안 |
|---|---|---|
| LibreOffice 내장 `hwpfilter` (확장 없이) | 최신 hwp/hwpx를 **조용히 손상**시키는 공개 버그(tdf#70097) | `H2Orestart` 확장을 반드시 추가 |
| `pyhwp`/`hwp5`를 상용 백엔드에 그대로 통합 | AGPL-3.0 copyleft 전이 위험, 쓰기 기능 없음, 표/이미지 구조 추출 불가 | 텍스트 추출만 필요하면 MIT의 `syhwp`/`hwpkit` 검토, 편집은 `python-hwpx` |
| `ratiertm/pyhwpxlib`를 상업 프로젝트에 무단 사용 | 핵심 로직 대부분이 **BSL 1.1**(상업적 이용 유료) | 같은 기능은 Apache-2.0인 `neolord0/hwp2hwpx` 원본을 직접 사용 |
| `hancom-io/hwpx-owpml-model`을 제품으로 채택 | 마지막 커밋 2023-10, 저수준 C++ 모델뿐 고수준 문서 API 없음, Windows/VS 빌드 전제 | 스펙 대조용 참고 자료로만 사용 |
| `hahnlee/hwp.js`를 편집기로 기대 | **뷰어 전용**(쓰기 없음), 마지막 푸시 2025-01(정체) | 표시만 필요하면 유지, 편집은 다른 도구 |
| `sechan9999/rhwp` | `edwardkim/rhwp`와 설명이 동일한 ★0 사본. 독자적 가치 없음 | 원본 `edwardkim/rhwp` 확인 시에도 §6 2위 항목의 검증 절차를 그대로 적용 |
| 레거시 `.hwp` 바이너리 **직접 쓰기**(`hwpkit`의 편집 저장, `jakal-hwpx`의 `HwpDocument.write_to_hwp`) | 채택 사례·이슈 이력이 거의 없는 신생 프로젝트(★1~12)의 주장일 뿐. MS-CFB 디렉터리 재작성은 한컴 스펙 문서조차 안전하다고 보증하지 않는 영역 | 프로덕션 공고문에는 아직 쓰지 말 것. 파일럿에서 한글로 열어 매번 눈으로 검증 후에만 확대 |
| 한컴 통합문서뷰어를 "Hancom-free 대안"으로 홍보 | 데스크톱 한글 2022는 필요 없지만 여전히 **한컴 자사 상용 엔진**이자 유료 제품 | "한글 2022 COM 자동화 제거"가 목적이면 유효하나 "한컴 종속 제로"가 목적이면 부적합 |

---

## 8. `hwpctl`과의 관계 — 대체가 아니라 보완

- `hwpctl`의 강점은 **사용자가 이미 열어 둔 한글 2022 창**을 실시간으로 조작해 화면에서
  바로 확인하는 워크플로입니다. 이건 어떤 헤드리스 라이브러리도 대신할 수 없습니다
  (한글 2022가 렌더링하는 실제 결과와 100% 동일한 화면 확인은 결국 한글 2022 자체가
  필요).
- 반면 **처음부터 복잡한 표·쪽 레이아웃을 가진 공고문을 "재현(recreate)"**하는 작업은
  COM 키 입력·Undo 단위 조작보다 **XML을 구조적으로 조립하는 방식**(`python-hwpx`)이
  훨씬 안정적입니다. 표 셀 여백, `TreatAsChar`, 쪽 나눔처럼 `hwpctl`이 `layout_review`로
  사후 보정해야 했던 항목들이 XML 직접 조립에서는 "만드는 시점에 정확하게 지정"되는
  문제로 바뀝니다.
- **권장 조합**: (1) 초안/반복 재현은 `python-hwpx`로 `.hwpx`를 직접 조립 → (2)
  `hwpctl open`으로 한글 2022에 로드해 화면 확인 → (3) 미세 조정이 필요하면 그 부분만
  `hwpctl`의 표/서식 명령으로 보정 → (4) `save_as`. 즉 `python-hwpx`(및 필요시
  `neolord0/hwp2hwpx`로의 레거시 `.hwp` 변환)를 **"구조를 한 번에 정확히 세팅하는
  전처리 단계"**로, `hwpctl`을 **"실물 한글 2022에서의 최종 확인·미세 조정 단계"**로
  나누는 것이 지금 조사 기준으로는 가장 현실적입니다.
- 이 조합을 쓰더라도 `hwpctl`이 서비스하는 "지금 열려 있는 창을 실시간으로 만진다"는
  가치 제안 자체는 바뀌지 않으므로, 이번 조사 결과로 `hwpctl`의 런타임 로직을 바꿀
  필요는 없습니다(이번 PR에서도 바꾸지 않았습니다). 다음 단계로 원한다면 별도 PR에서
  "`.hwpx` 사전 조립 → `hwpctl open` 확인" 예제 워크플로 문서만 추가하는 정도가 자연스러운
  후속 작업입니다.

---

## 참고 링크 모음

- python-hwpx: <https://github.com/airmang/python-hwpx> · <https://pypi.org/project/python-hwpx/>
- python-hwpx-automation: <https://github.com/airmang/python-hwpx-automation>
- neolord0/hwplib: <https://github.com/neolord0/hwplib>
- neolord0/hwpxlib: <https://github.com/neolord0/hwpxlib>
- neolord0/hwp2hwpx: <https://github.com/neolord0/hwp2hwpx>
- hancom-io/hwpx-owpml-model: <https://github.com/hancom-io/hwpx-owpml-model>
- jakal-hwpx: <https://github.com/Ahnd6474/jakal-hwpx>
- pyhwp/hwp5: <https://github.com/mete0r/pyhwp>
- hwp.js: <https://github.com/hahnlee/hwp.js>
- hwpkit: <https://github.com/psychofict/hwpkit>
- syhwp: <https://github.com/sysphere/syhwp>
- rhwp: <https://github.com/edwardkim/rhwp>
- H2Orestart: <https://github.com/ebandal/H2Orestart>
- hwp-converter-api: <https://github.com/jacepark12/hwp-converter-api>
- Gotenberg: <https://github.com/gotenberg/gotenberg>
- LibreOffice hwpfilter 버그(tdf#70097): <https://bugs.documentfoundation.org/show_bug.cgi?id=70097>
- 한컴 문서 변환 API: <https://developer.hancom.com/docsconverter/guide/api>
- 한컴 HWP/OWPML 형식 공개: <https://www.hancom.com/support/downloadCenter/hwpOwpml>
- HWP 5.0 문서 파일 형식 스펙: <https://cdn.hancom.com/link/docs/%ED%95%9C%EA%B8%80%EB%AC%B8%EC%84%9C%ED%8C%8C%EC%9D%BC%ED%98%95%EC%8B%9D_5.0_revision1.3.pdf>
