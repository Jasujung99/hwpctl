"""한글 GUI 없이 쪽 단위 시각 대조.

한/글 래스터가 없으므로 다음을 함께 낸다.

1. ``hwpx_inspect`` JSON (문단·런·셀 서식 그룹)
2. ``python-hwpx`` 레이아웃 프리뷰 HTML (한컴 없는 정직 근사)
3. 원본 PNG + 재현 프리뷰 PNG 를 붙인 비교 시트
4. 그룹 체크리스트(크림 헤더, 빨간 밑줄 기한, 파란 URL)

LibreOffice ``hwpfilter`` 는 쓰지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from hwpctl.errors import HwpxError, UsageError
from hwpctl.hwpx.inspect import _attr, _children, _first_child, _local, _text_of, inspect_hwpx

A4_W_PX = 794
A4_H_PX = 1123


def _optional_preview_html(path: Path) -> tuple[str | None, list[str]]:
    warnings: list[str] = []
    try:
        from hwpx.experimental import render_layout_preview
    except Exception as exc:  # noqa: BLE001 — 실험 표면은 없어도 비교는 계속
        warnings.append(f"python-hwpx 레이아웃 프리뷰를 쓸 수 없습니다: {exc}")
        return None, warnings
    try:
        preview = render_layout_preview(str(path), mode="pages", title="hwpctl HWPX preview")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"레이아웃 프리뷰 렌더에 실패했습니다: {exc}")
        return None, warnings
    return preview.html, warnings + list(preview.warnings or [])


def _korean_fonts() -> tuple[str | None, str | None]:
    """고딕·명조에 가까운 시스템 글꼴 경로."""

    candidates_gothic = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]
    candidates_serif = [
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    gothic = next((p for p in candidates_gothic if Path(p).is_file()), None)
    serif = next((p for p in candidates_serif if Path(p).is_file()), None)
    return gothic, serif


def _parse_char_map(header: ET.Element) -> dict[str, dict[str, Any]]:
    fonts: dict[str, str] = {}
    for face in header.iter():
        if _local(face.tag) != "font":
            continue
        fid = _attr(face, "id")
        name = _attr(face, "face")
        if fid and name and fid not in fonts:
            fonts[fid] = name
    out: dict[str, dict[str, Any]] = {}
    for node in header.iter():
        if _local(node.tag) != "charPr":
            continue
        pr_id = _attr(node, "id")
        if not pr_id:
            continue
        font_ref = _first_child(node, "fontRef")
        font_id = _attr(font_ref, "hangul") if font_ref is not None else ""
        underline = _first_child(node, "underline")
        utype = (_attr(underline, "type") if underline is not None else "").upper()
        out[pr_id] = {
            "font": fonts.get(font_id, ""),
            "size_pt": (int(_attr(node, "height") or "1000") / 100),
            "bold": _first_child(node, "bold") is not None,
            "underline": bool(underline is not None and utype != "NONE"),
            "color": _attr(node, "textColor") or "#000000",
        }
    return out


def _parse_para_align(header: ET.Element) -> dict[str, str]:
    out: dict[str, str] = {}
    for node in header.iter():
        if _local(node.tag) != "paraPr":
            continue
        pr_id = _attr(node, "id")
        align = _first_child(node, "align")
        if pr_id and align is not None:
            out[pr_id] = (_attr(align, "horizontal") or "").upper()
    return out


def _parse_fill_map(header: ET.Element) -> dict[str, str]:
    fills: dict[str, str] = {}
    for node in header.iter():
        if _local(node.tag) != "borderFill":
            continue
        fill_id = _attr(node, "id")
        brush = _first_child(node, "fillBrush")
        color = ""
        if brush is not None:
            win = _first_child(brush, "winBrush")
            if win is not None:
                color = _attr(win, "faceColor")
        if fill_id:
            fills[fill_id] = color
    return fills


def _page_break_para_pr_ids(header: ET.Element) -> set[str]:
    ids: set[str] = set()
    for node in header.iter():
        if _local(node.tag) != "paraPr":
            continue
        pr_id = _attr(node, "id")
        for child in node.iter():
            if _attr(child, "pageBreakBefore") in {"1", "true", "TRUE"}:
                if pr_id:
                    ids.add(pr_id)
                break
    return ids


def _split_pages(section: ET.Element, break_ids: set[str]) -> list[list[ET.Element]]:
    pages: list[list[ET.Element]] = [[]]
    for para in list(section):
        if _local(para.tag) != "p":
            continue
        pr_id = _attr(para, "paraPrIDRef")
        if pages[-1] and (
            _attr(para, "pageBreakBefore").upper() in {"1", "TRUE"} or pr_id in break_ids
        ):
            pages.append([])
        pages[-1].append(para)
    return [page for page in pages if page]


def render_hwpx_preview_pngs(path: str | Path, out_dir: Path) -> list[Path]:
    """HWPX XML 을 Pillow 로 쪽 PNG 근사 렌더한다. 한/글 래스터가 아니다."""

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise HwpxError(
            "쪽 PNG 를 만들려면 Pillow 가 필요합니다. pip install pillow"
        ) from exc

    target = Path(path)
    gothic_path, serif_path = _korean_fonts()
    out_dir.mkdir(parents=True, exist_ok=True)

    with ZipFile(target) as archive:
        header_xml = archive.read("Contents/header.xml")
        section_names = sorted(
            name
            for name in archive.namelist()
            if name.replace("\\", "/").startswith("Contents/section") and name.endswith(".xml")
        )
        sections = [archive.read(name) for name in section_names]
    header = ET.fromstring(header_xml)
    char_map = _parse_char_map(header)
    fill_map = _parse_fill_map(header)
    align_map = _parse_para_align(header)
    break_ids = _page_break_para_pr_ids(header)

    def font_for(char_pr: str, *, prefer_gothic: bool = False) -> Any:
        info = char_map.get(char_pr) or {}
        size = max(10, int(round(float(info.get("size_pt") or 11) * 1.15)))
        face = info.get("font") or ""
        gothic = "돋움" in face or "고딕" in face or prefer_gothic or bool(info.get("bold"))
        path_used = gothic_path if gothic else (serif_path or gothic_path)
        if not path_used:
            return ImageFont.load_default()
        try:
            return ImageFont.truetype(path_used, size=size)
        except OSError:
            return ImageFont.load_default()

    written: list[Path] = []
    page_no = 0
    for raw in sections:
        section = ET.fromstring(raw)
        for page_paras in _split_pages(section, break_ids):
            page_no += 1
            img = Image.new("RGB", (A4_W_PX, A4_H_PX), "#FFFFFF")
            draw = ImageDraw.Draw(img)
            x0, y = 48, 40
            max_w = A4_W_PX - 96
            for para in page_paras:
                if y > A4_H_PX - 70:
                    break
                tables = [
                    child
                    for run in _children(para, "run")
                    for child in _children(run, "tbl")
                ]
                if tables:
                    for tbl in tables:
                        y = _draw_table(
                            draw, tbl, x0, y, max_w, char_map, fill_map, font_for
                        )
                    continue
                y = _draw_paragraph_line(
                    draw,
                    para,
                    x0,
                    y,
                    max_w,
                    char_map,
                    align_map,
                    font_for,
                )
            draw.text(
                (A4_W_PX / 2, A4_H_PX - 28),
                f"- {page_no} -",
                font=font_for("0"),
                fill="#333333",
                anchor="mm",
            )
            out = out_dir / f"rebuild_p{page_no}.png"
            img.save(out)
            written.append(out)
    return written


def _draw_run_line(
    draw: Any,
    runs: list[ET.Element],
    x0: int,
    y: int,
    max_w: int,
    char_map: dict[str, dict[str, Any]],
    font_for: Any,
    *,
    align: str = "LEFT",
) -> int:
    pieces: list[tuple[str, Any, str, bool]] = []
    for run in runs:
        text = _text_of(run).replace("\r", "")
        if not text:
            continue
        char_pr = _attr(run, "charPrIDRef")
        info = char_map.get(char_pr) or {}
        pieces.append((text, font_for(char_pr), info.get("color") or "#000000", bool(info.get("underline"))))
    if not pieces:
        return y + 8
    # wrap into visual lines
    lines: list[list[tuple[str, Any, str, bool]]] = [[]]
    line_w = 0
    for text, font, color, underline in pieces:
        remain = text
        while remain:
            avail = max_w - line_w
            chunk = remain
            while chunk and font.getlength(chunk) > avail and len(chunk) > 1:
                chunk = chunk[:-1]
            if not chunk:
                lines.append([])
                line_w = 0
                continue
            lines[-1].append((chunk, font, color, underline))
            line_w += font.getlength(chunk)
            remain = remain[len(chunk) :]
            if remain:
                lines.append([])
                line_w = 0
    yy = y
    for line in lines:
        if not line:
            continue
        width = sum(font.getlength(text) for text, font, _c, _u in line)
        if align == "CENTER":
            x = x0 + max(0, (max_w - int(width)) // 2)
        elif align == "RIGHT":
            x = x0 + max(0, max_w - int(width))
        else:
            x = x0
        line_h = 16
        for text, font, color, underline in line:
            draw.text((x, yy), text, font=font, fill=color)
            tw = font.getlength(text)
            if underline:
                draw.line((x, yy + font.size + 1, x + tw, yy + font.size + 1), fill=color, width=1)
            x += tw
            line_h = max(line_h, font.size + 6)
        yy += line_h
    return yy + 4


def _draw_paragraph_line(
    draw: Any,
    para: ET.Element,
    x0: int,
    y: int,
    max_w: int,
    char_map: dict[str, dict[str, Any]],
    align_map: dict[str, str],
    font_for: Any,
) -> int:
    runs = _children(para, "run")
    if not runs:
        return y + 8
    align = align_map.get(_attr(para, "paraPrIDRef"), "LEFT")
    return _draw_run_line(draw, runs, x0, y, max_w, char_map, font_for, align=align)


def _draw_table(
    draw: Any,
    tbl: ET.Element,
    x0: int,
    y: int,
    max_w: int,
    char_map: dict[str, dict[str, Any]],
    fill_map: dict[str, str],
    font_for: Any,
) -> int:
    rows = _children(tbl, "tr")
    if not rows:
        return y
    col_count = max(len(_children(row, "tc")) for row in rows)
    col_w = max_w // max(col_count, 1)
    yy = y
    for row in rows:
        cells = _children(row, "tc")
        para_lists: list[list[ET.Element]] = []
        fills: list[str] = []
        for cell in cells:
            fills.append(fill_map.get(_attr(cell, "borderFillIDRef"), ""))
            paras = [node for node in cell.iter() if _local(node.tag) == "p"]
            para_lists.append(paras)
        estimated = 28
        for paras in para_lists:
            estimated = max(estimated, 8 + 18 * max(1, len(paras)))
        estimated = min(estimated, 780)
        for col, cell in enumerate(cells):
            x = x0 + col * col_w
            fill = fills[col] if col < len(fills) else ""
            box = (x, yy, x + col_w, yy + estimated)
            if fill and fill.upper() not in {"#FFFFFF", "#NONE", "NONE"}:
                draw.rectangle(box, fill=fill, outline="#000000")
            else:
                draw.rectangle(box, outline="#000000")
            cy = yy + 4
            for para in para_lists[col] if col < len(para_lists) else []:
                cy = _draw_run_line(
                    draw,
                    _children(para, "run"),
                    x + 4,
                    cy,
                    col_w - 8,
                    char_map,
                    font_for,
                    align="LEFT",
                )
                if cy > yy + estimated - 8:
                    break
        yy += estimated
    return yy + 8


def _style_checklist(inspected: dict[str, Any]) -> list[dict[str, Any]]:
    runs = inspected.get("run_groups") or []
    cells = inspected.get("cell_fill_groups") or []
    texts = " ".join(str(g.get("sample_text") or "") for g in runs)

    def has_run(*, color: str = "", underline: bool | None = None, bold: bool | None = None) -> bool:
        for group in runs:
            if color and str(group.get("color") or "").upper() != color.upper():
                continue
            if underline is not None and bool(group.get("underline")) != underline:
                continue
            if bold is not None and bool(group.get("bold")) != bold:
                continue
            return True
        return False

    cream = any(
        str(g.get("fill") or "").upper() in {"#F5E6C8", "#F3E5C0", "#FFF2CC", "#FAE6B8"}
        for g in cells
    )
    any_fill = any(g.get("fill") for g in cells)
    return [
        {"id": "title_or_notice", "ok": "공고" in texts or "사업" in texts, "label": "제목/사업 문구"},
        {"id": "cream_header", "ok": cream or any_fill, "label": "크림/셀 배경"},
        {"id": "red_underline", "ok": has_run(color="#FF0000", underline=True), "label": "빨간 밑줄 기한"},
        {"id": "blue_underline", "ok": has_run(color="#0000FF", underline=True), "label": "파란 밑줄 URL"},
        {"id": "bold_run", "ok": any(g.get("bold") for g in runs), "label": "굵은 런"},
        {"id": "gothic_or_myeongjo", "ok": any("함초롬" in str(g.get("font") or "") for g in runs), "label": "함초롬 글꼴"},
    ]


def _composite_sheet(
    orig: Path | None,
    preview: Path | None,
    out: Path,
    *,
    title: str,
    notes: Sequence[str],
) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    gothic_path, _serif = _korean_fonts()
    try:
        font = ImageFont.truetype(gothic_path, 16) if gothic_path else ImageFont.load_default()
        small = ImageFont.truetype(gothic_path, 13) if gothic_path else ImageFont.load_default()
    except OSError:
        font = ImageFont.load_default()
        small = font

    panels: list[tuple[str, Image.Image]] = []
    if orig and orig.is_file():
        panels.append(("원본 (한글 스크린샷)", Image.open(orig).convert("RGB")))
    if preview and preview.is_file():
        panels.append(("재현 근사 (한/글 래스터 아님)", Image.open(preview).convert("RGB")))
    if not panels:
        raise HwpxError("비교할 PNG 가 없습니다.")

    target_h = 900
    resized = []
    for label, img in panels:
        ratio = target_h / img.height
        new = img.resize((max(1, int(img.width * ratio)), target_h))
        resized.append((label, new))
    gap = 16
    note_h = 80 + 18 * len(notes)
    width = sum(im.width for _, im in resized) + gap * (len(resized) + 1)
    height = 40 + target_h + note_h
    canvas = Image.new("RGB", (width, height), "#F4F4F4")
    draw = ImageDraw.Draw(canvas)
    draw.text((gap, 10), title, font=font, fill="#111111")
    x = gap
    y = 36
    for label, im in resized:
        canvas.paste(im, (x, y))
        draw.text((x, y + target_h + 6), label, font=small, fill="#333333")
        x += im.width + gap
    ny = y + target_h + 28
    for idx, note in enumerate(notes):
        draw.text((gap, ny + idx * 18), note, font=small, fill="#222222")
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return out


def compare_page_images(
    rebuilt: str | Path,
    *,
    orig_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
    pages: Sequence[int] | None = None,
) -> dict[str, Any]:
    """재현 ``.hwpx`` 와 원본 PNG 를 대조하고 산출물을 저장한다."""

    source = Path(rebuilt).expanduser()
    if not source.is_file():
        raise HwpxError(f"HWPX 파일을 찾을 수 없습니다: {source}")
    if source.suffix.lower() != ".hwpx":
        raise UsageError("쪽 비교는 .hwpx 경로가 필요합니다.")
    dest = Path(output_dir or (source.parent / "compare")).expanduser()
    dest.mkdir(parents=True, exist_ok=True)

    inspected = inspect_hwpx(source)
    inspect_path = dest / "inspect.json"
    inspect_path.write_text(json.dumps(inspected, ensure_ascii=False, indent=2), encoding="utf-8")

    html, preview_warnings = _optional_preview_html(source)
    html_path = None
    if html:
        html_path = dest / "layout_preview.html"
        html_path.write_text(html, encoding="utf-8")

    preview_dir = dest / "rebuild_pages"
    preview_pngs: list[Path] = []
    raster_warning = ""
    try:
        preview_pngs = render_hwpx_preview_pngs(source, preview_dir)
    except HwpxError as exc:
        raster_warning = exc.message

    checklist = _style_checklist(inspected)
    gold_dir = Path(orig_dir).expanduser() if orig_dir else None
    wanted = list(pages or [1, 2, 3])
    sheets: list[dict[str, Any]] = []
    gaps: list[str] = []
    for page in wanted:
        orig = None
        if gold_dir:
            candidate = gold_dir / f"orig_p{page}.png"
            orig = candidate if candidate.is_file() else None
            if orig is None:
                gaps.append(f"원본 PNG 없음: orig_p{page}.png")
        preview = preview_dir / f"rebuild_p{page}.png"
        preview = preview if preview.is_file() else None
        notes = [f"{item['label']}: {'OK' if item['ok'] else 'GAP'}" for item in checklist]
        notes.append("재현 PNG 는 HWPX XML 근사 렌더이며 한글 2022 화면이 아닙니다.")
        if orig or preview:
            try:
                sheet = _composite_sheet(
                    orig,
                    preview,
                    dest / f"compare_p{page}.png",
                    title=f"공고문 {page}쪽 비교",
                    notes=notes,
                )
                sheets.append({"page": page, "path": str(sheet), "orig": str(orig) if orig else None})
            except Exception as exc:  # noqa: BLE001 — 시트 실패해도 inspect JSON 은 남긴다
                gaps.append(f"{page}쪽 비교 시트 실패: {exc}")
        else:
            gaps.append(f"{page}쪽 비교 시트를 만들 수 없습니다.")

    if not all(item["ok"] for item in checklist):
        gaps.extend(item["label"] for item in checklist if not item["ok"])

    report = {
        "ok": True,
        "command": "hwpx_compare",
        "hangul_required": False,
        "lock_required": False,
        "backend": "owpml-xml+pillow",
        "rasterizer": "hwpctl XML preview (not Hangul, not LibreOffice hwpfilter)",
        "rebuilt": str(source),
        "inspect": str(inspect_path),
        "layout_preview_html": str(html_path) if html_path else None,
        "rebuild_pngs": [str(p) for p in preview_pngs],
        "compare_sheets": sheets,
        "checklist": checklist,
        "gaps": gaps,
        "warnings": preview_warnings + ([raster_warning] if raster_warning else []),
    }
    (dest / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# HWPX 쪽 비교 (한글 GUI 없음)",
        "",
        f"- 재현 파일: `{source}`",
        f"- 래스터: {report['rasterizer']}",
        "",
        "## 체크리스트",
        "",
    ]
    for item in checklist:
        mark = "OK" if item["ok"] else "GAP"
        lines.append(f"- [{mark}] {item['label']}")
    if gaps:
        lines.extend(["", "## 남은 간격", ""])
        lines.extend(f"- {gap}" for gap in gaps)
    (dest / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
