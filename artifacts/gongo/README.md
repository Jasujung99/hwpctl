# 공고문 재현 산출물

한글 2022 없이 `scripts/recreate_gongo.py` 가 만든 파일입니다.

| 파일 | 설명 |
|---|---|
| `rebuild_p1_10.hwpx` | 1–10·27–29쪽 조립본. 1–3쪽 충실, 나머지 골격 |
| `inspect.json` | 문단·런·셀 서식 그룹 |
| `layout_preview.html` | python-hwpx 레이아웃 프리뷰 (한컴 없는 정직 근사) |
| `rebuild_pages/rebuild_pN.png` | HWPX XML → Pillow 근사 렌더. **한글 래스터 아님** |
| `compare_p1.png`–`compare_p3.png` | 원본 스크린샷 \| 재현 근사 |
| `report.json` / `report.md` | 체크리스트와 남은 간격 |

다시 만들기:

```bash
python scripts/recreate_gongo.py --out artifacts/gongo
```
