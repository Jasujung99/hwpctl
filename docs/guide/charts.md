# 한/글 네이티브 차트 (insert_chart)

[← README](../../README.md) · [문서 목록](../README.md)

> **현재 사용 비권장 ([#33](https://github.com/Jasujung99/hwpctl/issues/33)).** 2026-10-15 실기(한글 2022 `12.0.0.850`)에서
> `ChartDataDialogDisable=1`이 무시되어 "차트 데이터 편집" 대화상자가 떴고, 대화상자가 닫힐 때까지
> 호출이 반환되지 않았으며 차트에 표 데이터가 아닌 기본값이 들어갔습니다. 아래 설명은 의도한
> 동작이며, 이 문제가 해결될 때까지 사용자가 명시적으로 요청한 경우에만 쓰세요.

`insert_chart` 는 **한/글 입력 > 차트** 개체를 넣습니다. PNG 그림 삽입이 아닙니다.

흐름: 데이터 표를 만들고(`create_table` + `fill_cells`) → `insert_chart --table N`.
표(또는 `--range` 범위)의 셀을 선택한 뒤 `InsertChart` 액션을
`ChartGroup` / `ChartIndex` / `ChartDataDialogDisable=1` 파라미터로 실행합니다
(한컴 포럼에서 확인된, 노출된 파라미터 전부입니다 — 생성 후 차트 수정 API 는 없습니다).

```bat
hwpctl insert_chart --table 1 --type line      :: 인생 그래프 = 꺾은선
hwpctl insert_chart --table 0 --type column --range A1:B10
```

- 종류: `line`(꺾은선) / `column`(세로막대) / `bar`(가로막대) / `pie`(원형).
  0=가로막대·1=세로막대·3=원형은 한컴 포럼에서 확인된 값이고, line=2 는 추론값이라
  실기에서 종류가 다르게 나오면 `--type` 대신 `--index` 와 함께 조정하세요.
- **한글 2022 이상 전용.** 2020 이하에는 `ChartDataDialogDisable` 이 없어 데이터
  편집 대화상자가 뜹니다. 대화상자가 뜨면 자동화 실패입니다 — hwpctl 은 한국어
  오류를 내며, 화면의 창을 대신 눌러 주지 않습니다.
