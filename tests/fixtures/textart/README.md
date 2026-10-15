# 글맵시(TextArt) 테스트 자료

한글 2022 `12.0.0.850`(Windows 11, `win32com`)에서 2026-10-15에 **새 빈 문서로 합성한** 테스트
자료입니다. 실제 사용자 문서나 개인 정보는 들어 있지 않습니다. 문서 메타데이터에는 한/글이 기본으로
넣는 작성자(`user`)와 서식 파일 날짜만 있습니다. HWPML은 같은 문서를 `GetTextFile("HWPML2X")`로
내보낸 것이고, XML 선언(`UTF-16`)에 맞춘 바이트로 저장했습니다.

| 파일 | 만든 방법 | 들어 있는 글맵시 |
|---|---|---|
| `ui-wave2-linear.hwpx` / `.hwpml` | 한/글 UI: 입력 → 글맵시, 개체 속성 → 채우기 → 그러데이션(가로) | 1개. "그라데이션 샘플", 함초롬바탕 보통, `WAVE2`, 선형 0° `#FF0000`→`#0000FF`, 떠 있음(문단·단 기준), 16500×5000 HU |
| `com-two-text-arts.hwpx` / `.hwpml` | 위 문서에 COM으로 추가: `TextArtCreate` → `ShapeObjDialog` | 2개. 위와 같은 UI 글맵시 + "COM 글맵시 그라데이션", 함초롬돋움, `PARALLELOGRAM`, 선형 90° `#FFA500`→`#800080`, 떠 있음(종이 기준) |
| `variants.hwpx` / `.hwpml` | COM: `TextArtCreate` → `ShapeObjDialog` | 10개. `RECTANGLE` 모양, 정렬 4종(`A0`~`A3` → LEFT/RIGHT/CENTER/FULL), 글꼴 스타일 4종(보통·굵게·기울임·굵게 기울임), `FontType=2`를 준 한양견고딕(저장 결과는 TTF), 두 줄 내용 |

이 자료로 고정한 실측 사실은 `hwpctl/textart.py`에 있습니다. 갱신할 때는 같은 방식으로 새 문서에서
다시 만들고, 사용한 한/글 빌드를 이 표와 `THIRD_PARTY_NOTICES.md`에 함께 기록합니다.
