# 글맵시 (글자 그러데이션)

[← README](../../README.md) · [문서 목록](../README.md)

한/글에서 **글자 자체에 그러데이션을 넣는 기본 방법은 글맵시(TextArt)**입니다. 글자 모양(`set_format`)에는
그러데이션이 없습니다. `insert_text_art`는 편집 가능한 한/글 네이티브 글맵시를 넣습니다. 그림으로 바꾸지
않으므로 한/글에서 내용·글꼴·채우기를 계속 고칠 수 있습니다.

## 사용 예

MCP:

```json
{
  "text": "2026 북클럽",
  "width_mm": 120,
  "height_mm": 25,
  "shape": "rectangle",
  "font": "함초롬돋움",
  "font_style": "bold",
  "fill": {"type": "linear_gradient", "angle": 0, "stops": ["#7B2FF7", "#F107A3"], "step": 255}
}
```

CLI:

```bat
hwpctl insert_text_art "2026 북클럽" --width 120 --height 25 --font 함초롬돋움 --font-style bold ^
  --fill "{\"type\":\"linear_gradient\",\"angle\":0,\"stops\":[\"#7B2FF7\",\"#F107A3\"],\"step\":255}"
```

## 인자

| 인자 | 기본값 | 설명 |
|---|---|---|
| `text` | (필수) | 내용. 여러 줄은 `\n` (CLI에서는 `\n` 두 글자) |
| `width_mm`, `height_mm` | (필수) | 글맵시 크기(mm). 글자가 이 상자에 맞게 늘어납니다 |
| `shape` | `rectangle` | 글맵시 모양. 아래 55종의 이름. `rectangle`은 일반 직선 모양 |
| `font` | 한/글 기본(함초롬바탕) | TTF 글꼴 이름 |
| `font_style` | `regular` | `regular`, `bold`, `italic`, `bold_italic` |
| `fill` | 한/글 기본(파란 단색) | 색 문자열(단색) 또는 채우기 객체. 아래 참고 |
| `line` | 없음 | 글맵시 윤곽선 `{"type":"solid","color":"#RRGGBB","width_mm":0.5}` |
| `shadow` | 없음 | 개체 그림자 `{"type":"offset","color":..., "offset_x_mm":1, "offset_y_mm":1}` |
| `align` | `left` | 여러 줄 정렬: `left`, `right`, `center`, `full` |
| `line_spacing_percent` | 120 | 줄 간격(%) 50~500 |
| `char_spacing_percent` | 100 | 글자 간격(%) 50~500 |
| `position` | 글자처럼 취급 | `{"mode":"inline"}` 또는 `{"mode":"floating","x_mm":..,"y_mm":..,"wrap":"in_front_of_text",...}` |

## 채우기

- 단색: `"#FF0000"` 또는 `{"type":"solid","color":"#FF0000"}`
- 선형: `{"type":"linear_gradient","angle":0~359,"stops":["#시작","#끝"],"step":0~255,"step_center":0~100}`
- 방사형: `{"type":"radial_gradient","stops":[...],"center_x":0~100,"center_y":0~100,"step":0~255,"step_center":0~100}`
- `step`은 한/글의 **번짐 정도**입니다. 한/글 UI 기본값은 255이고, 생략하면 선형은 100을 씁니다.
- 색은 **2개만** 받습니다. 한글 2022 자동화는 3색 이상이면 오류 없이 채우기 전체를 버리기 때문입니다.

이 채우기 형식은 표 칸(`set_cell_fill`)·글상자·도형과 같습니다.

## 모양 55종

`shape`에는 아래 이름을 소문자로 씁니다. 번호는 한/글 `DrawTextart.Shape` 값이고, 이름은 HWPX `textShape` 표기입니다.

| 번호 | 이름 | 번호 | 이름 | 번호 | 이름 |
|---|---|---|---|---|---|
| 0 | parallelogram | 19 | wave4 | 38 | deflate |
| 1 | inverted_parallelogram | 20 | left_tilt_cylinder | 39 | inflate |
| 2 | inverted_upward_cascade | 21 | right_tilt_cylinder | 40 | inflate_top |
| 3 | inverted_downward_cascade | 22 | bottom_wide_cylinder | 41 | inflate_bottom |
| 4 | upward_cascade | 23 | top_wide_cylinder | 42 | **rectangle** |
| 5 | downward_cascade | 24 | thin_curve_up1 | 43 | left_cylinder |
| 6 | reduce_right | 25 | thin_curve_up2 | 44 | cylinder |
| 7 | reduce_left | 26 | thin_curve_down1 | 45 | right_cylinder |
| 8 | isosceles_trapezoid | 27 | thin_curve_down2 | 46 | circle |
| 9 | inverted_isosceles_trapezoid | 28 | inversed_fingernail | 47 | curve_down |
| 10 | top_ribbon_rectangle | 29 | fingernail | 48 | arch_up |
| 11 | bottom_ribbon_rectangle | 30 | ginko_leaf1 | 49 | arch_down |
| 12 | chevron_down | 31 | ginko_leaf2 | 50 | single_line_circle1 |
| 13 | chevron | 32 | inflate_right | 51 | single_line_circle2 |
| 14 | bow_tie | 33 | inflate_left | 52 | triple_line_circle1 |
| 15 | hexagon | 34 | inflate_up_convex | 53 | triple_line_circle2 |
| 16 | wave1 | 35 | inflate_bottom_convex | 54 | double_line_circle |
| 17 | wave2 | 36 | deflate_top | | |
| 18 | wave3 | 37 | deflate_bottom | | |

## 작성 명세와 변환

- 작성 명세(v2)에서는 `{"kind": "text_art", ...}` 노드가 같은 인자를 받고 `insert_text_art`로 실행됩니다.
- `reference_to_spec`은 HWPML·HWPX의 글맵시를 `text_art` 노드로 옮깁니다. 내용, 글꼴, 스타일, 모양,
  정렬, 간격, 크기, 채우기(번짐 정도 포함), 윤곽선, 위치·바깥 여백이 대상입니다.
- 회전·뒤집기·기울이기, 글맵시 자체 그림자와 개체 그림자, TTF가 아닌 글꼴, 사용자 설명은 아직 재현하지
  않으므로 손실로 보고합니다.

## 한계

- 글꼴은 TTF만 다룹니다. 한양 HFT 글꼴은 `FontType=2`를 줘도 한/글이 TTF로 저장합니다.
- 글맵시 대화상자의 "그림자(비연속)"는 아직 지원하지 않습니다. `shadow`는 개체 그림자입니다.
- 한 명령은 한/글 Undo 2단계(생성 + 속성)이고, hwpctl `undo` 한 번으로 함께 되돌아갑니다.
- 실측 근거와 테스트 자료: [`tests/fixtures/textart`](../../tests/fixtures/textart/README.md),
  `hwpctl/textart.py`
