# 조판·문단 보기와 보수적 서식 정리

```powershell
hwpctl set_edit_marks
hwpctl set_edit_marks --no-control-marks --no-paragraph-marks
```

MCP: `set_edit_marks(control_marks=true, paragraph_marks=true)`.
OptionFlag의 2/4 비트를 설정하고 읽어서 확인한다. 나머지 보기 비트, 문서 본문, 캐럿은 변경하지 않는다. 조판부호 on / 문단부호 off 조합은 한/글 표시 의미상 모호하므로 거부한다. 보기 설정은 문서 Undo 이력에 넣지 않는다.

근거: https://raw.githubusercontent.com/hancom-io/devcenter-archive/main/hwp-automation/ParameterSetObject.pdf

`hwpctl.edit_support.compact_formatting_xml(parts)`는 서명되지 않은 HWPX의 **모든 XML/HPF 파트**를 받은 뒤 참조되지 않은 글자/문단 모양 정의만 제거하고 ID 참조를 재매핑한다. 기본 0번 정의와 이름 있는 스타일의 참조를 보존한다. UINT32_MAX paraHead 상속 참조도 보존한다. 잘못된 참조·중복 정의·DTD는 거부한다. 호출자가 원본과 다른 경로로 ZIP을 저장하고 한/글에서 열어 출력 검수해야 한다. 이 함수는 공개 CLI/MCP 파일 수정 도구가 아니라 재사용 가능한 내부 순수 함수다.

빈 문단은 개체 앵커일 수 있으므로 보이는 글자가 없다는 이유만으로 지우지 않는다. 페이지 나눔·표·그림·필드·각주 등의 컨트롤을 반드시 검사한다. HAEON 사례에서는 기존 3개 앵커를 모두 보존했고 새 페이지 제작 중 생긴 빈 문단만 쪽 나눔을 이전한 후 제거했다.
