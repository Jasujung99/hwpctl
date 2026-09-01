# 공고문 1쪽 품질 산출물

한글 2022 없이 `scripts/recreate_gongo.py` 가 만든 파일입니다.
품질 판정은 Pillow 픽셀이 아니라 `inspect.json`(OWPML) 입니다.

| 파일 | 설명 |
|---|---|
| `rebuild_p1.hwpx` | **1쪽만** 조립. `휴먼명조`/`HY헤드라인M`, 크림 `#FCF5E7`, 빨간 기한 밑줄 |
| `inspect.json` | 문단·런·셀 서식 그룹 |
| `layout_preview.html` | python-hwpx 레이아웃 프리뷰 (한컴 없는 정직 근사) |
| `rebuild_pages/rebuild_p1.png` | HWPX XML → Pillow 근사 렌더. **한글 래스터 아님** |
| `compare_p1.png` | 원본 스크린샷 \| 재현 근사 |
| `report.json` / `report.md` | inspect 체크리스트와 남은 간격 |

다시 만들기:

```bash
python scripts/recreate_gongo.py --out artifacts/gongo
```

2–3쪽까지 같은 엔진을 쓰려면 `--pages 1,2,3`. 4쪽 이후는 만들지 않습니다.
