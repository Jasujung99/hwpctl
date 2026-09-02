"""ID·빈 문단에 강한 HWPML 구조 비교.

이 비교기는 페이지 이미지나 PDF를 만들지 않는다. 따라서 ``status == "pass"``는
구조적으로 비교 가능한 항목이 일치한다는 뜻일 뿐, 시각적 동일성을 뜻하지 않는다.
도형·그라데이션처럼 여기서 해석하지 않는 요소가 있으면 결과는 ``inconclusive``로
낮춘다.
"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from typing import Any, Iterable

from hwpctl.reference.model import Cell, NormalizedDocument, ParagraphBlock, Table, normalize_hwpml


_SCHEMA = "hwpctl.reference-compare/1"


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=repr).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text_summary(value: str) -> dict[str, Any]:
    return {"length": len(value), "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest()}


def _safe_value(value: Any) -> Any:
    """보고서에 원문 문구를 흘리지 않는 값 표현."""

    if value is None or isinstance(value, (bool, int, float)):
        return value
    return {"sha256": _fingerprint(value)}


class _Differences:
    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("max_differences는 1 이상이어야 합니다.")
        self.limit = limit
        self.items: list[dict[str, Any]] = []
        self.truncated = False

    def add(self, kind: str, location: dict[str, Any], **details: Any) -> None:
        if len(self.items) >= self.limit:
            self.truncated = True
            return
        item = {"kind": kind, "location": location}
        item.update(details)
        self.items.append(item)


def _table_anchor(table: Table) -> tuple[Any, ...]:
    """크기·테두리와 무관하게 같은 표를 찾아내는 의미 지문."""

    cells = []
    for cell in table.cells:
        visible = "".join(_block_visible_text(paragraph) for paragraph in cell.paragraphs)
        cells.append((cell.key, _text_summary(visible)["sha256"]))
    return (table.rows, table.columns, tuple(cells))


def _block_visible_text(block: ParagraphBlock) -> str:
    if block.table is None:
        return block.visible_text
    return block.visible_text + "".join(
        _block_visible_text(paragraph)
        for cell in block.table.cells
        for paragraph in cell.paragraphs
    )


def _block_anchor(block: ParagraphBlock) -> tuple[Any, ...]:
    if block.is_blank:
        return ("blank",)
    if block.table is not None:
        return ("table", _text_summary(_block_visible_text(block))["sha256"], _table_anchor(block.table))
    return ("paragraph", _text_summary(block.visible_text)["sha256"])


def _longest_increasing_pairs(pairs: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """참조 순서와 후보 순서를 동시에 지키는 고유 앵커만 남긴다."""

    ordered = sorted(pairs)
    if not ordered:
        return []
    lengths = [1] * len(ordered)
    previous = [-1] * len(ordered)
    for right in range(len(ordered)):
        for left in range(right):
            if ordered[left][1] < ordered[right][1] and lengths[left] + 1 > lengths[right]:
                lengths[right] = lengths[left] + 1
                previous[right] = left
    current = max(range(len(ordered)), key=lambda index: lengths[index])
    result: list[tuple[int, int]] = []
    while current != -1:
        result.append(ordered[current])
        current = previous[current]
    result.reverse()
    return result


def _match_blocks(
    reference: tuple[ParagraphBlock, ...],
    candidate: tuple[ParagraphBlock, ...],
) -> tuple[list[tuple[int, int]], set[int], set[int], list[str]]:
    """빈 문단 삽입이 뒤 표를 밀지 않도록 보수적으로 블록을 맞춘다."""

    reference_keys = [_block_anchor(block) for block in reference]
    candidate_keys = [_block_anchor(block) for block in candidate]
    reference_positions: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    candidate_positions: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    for index, key in enumerate(reference_keys):
        reference_positions[key].append(index)
    for index, key in enumerate(candidate_keys):
        candidate_positions[key].append(index)

    unique_pairs = [
        (reference_positions[key][0], candidate_positions[key][0])
        for key in reference_positions.keys() & candidate_positions.keys()
        if key != ("blank",)
        and len(reference_positions[key]) == 1
        and len(candidate_positions[key]) == 1
    ]
    pairs = _longest_increasing_pairs(unique_pairs)
    paired_reference = {index for index, _ in pairs}
    paired_candidate = {index for _, index in pairs}

    # 빈 문단은 보이는 내용으로는 앵커가 될 수 없지만, 양쪽 동일 구간에서는
    # 순서대로 비교해 서식 차이는 계속 보고한다.
    sentinels = [(-1, -1), *pairs, (len(reference), len(candidate))]
    for (reference_start, candidate_start), (reference_end, candidate_end) in zip(
        sentinels, sentinels[1:]
    ):
        reference_blanks = [
            index
            for index in range(reference_start + 1, reference_end)
            if reference[index].is_blank and index not in paired_reference
        ]
        candidate_blanks = [
            index
            for index in range(candidate_start + 1, candidate_end)
            if candidate[index].is_blank and index not in paired_candidate
        ]
        for reference_index, candidate_index in zip(reference_blanks, candidate_blanks):
            pairs.append((reference_index, candidate_index))
            paired_reference.add(reference_index)
            paired_candidate.add(candidate_index)

    ambiguous: list[str] = []
    for key in reference_positions.keys() & candidate_positions.keys():
        if key == ("blank",):
            continue
        ref_unmatched = [index for index in reference_positions[key] if index not in paired_reference]
        cand_unmatched = [index for index in candidate_positions[key] if index not in paired_candidate]
        if ref_unmatched and cand_unmatched:
            ambiguous.append(_fingerprint(key))
    return sorted(pairs), paired_reference, paired_candidate, sorted(set(ambiguous))


def _format_difference(
    differences: _Differences,
    kind: str,
    location: dict[str, Any],
    reference: Any,
    candidate: Any,
) -> None:
    if reference != candidate:
        differences.add(
            kind,
            location,
            reference=_safe_value(reference),
            candidate=_safe_value(candidate),
        )


def _border_parts(cell: Cell) -> tuple[Any, dict[str, str | None]]:
    mapping = dict(cell.border)
    return mapping.get("fill"), dict(mapping.get("sides", ()))


def _physical_borders(table: Table) -> tuple[dict[tuple[str, int, int], Any], list[tuple[str, int, int]]]:
    """칸 속성이 아니라 실제 격자 경계 기준으로 테두리를 정규화한다."""

    styles: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    for cell in table.cells:
        _, sides = _border_parts(cell)
        top = sides.get("top")
        bottom = sides.get("bottom")
        left = sides.get("left")
        right = sides.get("right")
        for column in range(cell.column, cell.column + cell.column_span):
            if top is not None:
                styles[("h", cell.row, column)].add(top)
            if bottom is not None:
                styles[("h", cell.row + cell.row_span, column)].add(bottom)
        for row in range(cell.row, cell.row + cell.row_span):
            if left is not None:
                styles[("v", row, cell.column)].add(left)
            if right is not None:
                styles[("v", row, cell.column + cell.column_span)].add(right)

    normalized: dict[tuple[str, int, int], Any] = {}
    conflicts: list[tuple[str, int, int]] = []
    for edge, edge_styles in styles.items():
        ordered = tuple(sorted(edge_styles))
        normalized[edge] = ordered[0] if len(ordered) == 1 else ordered
        if len(ordered) > 1:
            conflicts.append(edge)
    return normalized, sorted(conflicts)


def _compare_table(
    reference: Table,
    candidate: Table,
    location: dict[str, Any],
    differences: _Differences,
) -> None:
    _format_difference(differences, "table_dimensions", location, (reference.rows, reference.columns), (candidate.rows, candidate.columns))
    _format_difference(differences, "table_formatting", location, reference.formatting, candidate.formatting)

    reference_cells = {cell.key: cell for cell in reference.cells}
    candidate_cells = {cell.key: cell for cell in candidate.cells}
    for key in sorted(reference_cells.keys() - candidate_cells.keys()):
        differences.add("missing_cell", {**location, "cell": key})
    for key in sorted(candidate_cells.keys() - reference_cells.keys()):
        differences.add("extra_cell", {**location, "cell": key})
    for key in sorted(reference_cells.keys() & candidate_cells.keys()):
        reference_cell = reference_cells[key]
        candidate_cell = candidate_cells[key]
        cell_location = {**location, "cell": key}
        _format_difference(
            differences,
            "cell_geometry",
            cell_location,
            (reference_cell.width_hwp, reference_cell.height_hwp),
            (candidate_cell.width_hwp, candidate_cell.height_hwp),
        )
        _format_difference(
            differences,
            "cell_vertical_align",
            cell_location,
            reference_cell.vertical_align,
            candidate_cell.vertical_align,
        )
        reference_fill, _ = _border_parts(reference_cell)
        candidate_fill, _ = _border_parts(candidate_cell)
        _format_difference(differences, "cell_fill", cell_location, reference_fill, candidate_fill)
        _compare_block_sequence(
            reference_cell.paragraphs,
            candidate_cell.paragraphs,
            {**cell_location, "container": "cell"},
            differences,
            [],
        )

    reference_edges, reference_conflicts = _physical_borders(reference)
    candidate_edges, candidate_conflicts = _physical_borders(candidate)
    for edge in reference_conflicts:
        differences.add("reference_border_conflict", {**location, "edge": edge})
    for edge in candidate_conflicts:
        differences.add("candidate_border_conflict", {**location, "edge": edge})
    for edge in sorted(reference_edges.keys() | candidate_edges.keys()):
        _format_difference(
            differences,
            "grid_border",
            {**location, "edge": edge},
            reference_edges.get(edge),
            candidate_edges.get(edge),
        )


def _compare_block(
    reference: ParagraphBlock,
    candidate: ParagraphBlock,
    location: dict[str, Any],
    differences: _Differences,
) -> None:
    if reference.kind != candidate.kind:
        differences.add(
            "block_kind",
            location,
            reference=reference.kind,
            candidate=candidate.kind,
        )
        return
    _format_difference(
        differences,
        "paragraph_formatting",
        location,
        reference.paragraph_formatting,
        candidate.paragraph_formatting,
    )
    _format_difference(differences, "page_break", location, reference.page_break, candidate.page_break)
    if reference.visible_text != candidate.visible_text:
        differences.add(
            "visible_text",
            location,
            reference=_text_summary(reference.visible_text),
            candidate=_text_summary(candidate.visible_text),
        )
    reference_runs = tuple((run.text_digest, run.formatting) for run in reference.runs)
    candidate_runs = tuple((run.text_digest, run.formatting) for run in candidate.runs)
    _format_difference(differences, "run_formatting", location, reference_runs, candidate_runs)
    if reference.table is not None and candidate.table is not None:
        _compare_table(reference.table, candidate.table, location, differences)


def _compare_block_sequence(
    reference: tuple[ParagraphBlock, ...],
    candidate: tuple[ParagraphBlock, ...],
    location: dict[str, Any],
    differences: _Differences,
    ambiguous_out: list[str],
) -> None:
    pairs, paired_reference, paired_candidate, ambiguous = _match_blocks(reference, candidate)
    ambiguous_out.extend(ambiguous)
    ambiguous_set = set(ambiguous)
    for fingerprint in ambiguous:
        differences.add("ambiguous_block_alignment", location, fingerprint=fingerprint)
    for index, block in enumerate(reference):
        if index in paired_reference:
            continue
        if _fingerprint(_block_anchor(block)) in ambiguous_set:
            continue
        differences.add(
            "missing_blank_paragraph" if block.is_blank else "missing_block",
            {**location, "reference_block": index},
            fingerprint=_fingerprint(_block_anchor(block)),
        )
    for index, block in enumerate(candidate):
        if index in paired_candidate:
            continue
        if _fingerprint(_block_anchor(block)) in ambiguous_set:
            continue
        differences.add(
            "extra_blank_paragraph" if block.is_blank else "extra_block",
            {**location, "candidate_block": index},
            fingerprint=_fingerprint(_block_anchor(block)),
        )
    for reference_index, candidate_index in pairs:
        _compare_block(
            reference[reference_index],
            candidate[candidate_index],
            {**location, "reference_block": reference_index, "candidate_block": candidate_index},
            differences,
        )


def _count_tables(blocks: Iterable[ParagraphBlock]) -> int:
    count = 0
    for block in blocks:
        if block.table is None:
            continue
        count += 1
        count += _count_tables(
            paragraph for cell in block.table.cells for paragraph in cell.paragraphs
        )
    return count


def compare_structure(
    reference: NormalizedDocument,
    candidate: NormalizedDocument,
    *,
    max_differences: int = 100,
) -> dict[str, Any]:
    """두 정규 문서의 비교 가능한 구조를 대조한다.

    결과에는 원문 문자열과 로컬 경로를 넣지 않는다. ``complete``는 전체 시각
    재현의 완료 여부이므로 PDF/PPM 비교를 실행하지 않은 이 함수에서는 항상
    ``False``다. ``structural_complete``만 이 계층의 커버리지 상태다.
    """

    differences = _Differences(max_differences)
    ambiguous: list[str] = []
    _format_difference(differences, "page_setup", {"scope": "document"}, reference.page, candidate.page)
    _compare_block_sequence(
        reference.blocks,
        candidate.blocks,
        {"scope": "body"},
        differences,
        ambiguous,
    )

    unsupported = sorted(reference.unsupported | candidate.unsupported)
    coverage = {
        "page_setup": "compared",
        "text": "compared",
        "paragraph_formatting": "compared",
        "run_formatting": "compared",
        "tables": "compared",
        "cell_geometry": "compared",
        "borders": "compared",
        "drawings": "unsupported" if "drawings" in unsupported else "not_present",
        "gradients": "unsupported" if "gradients" in unsupported else "not_present",
        "visual_layout": "not_run",
    }
    structural_complete = not unsupported and not ambiguous
    definite_difference = any(
        item["kind"] != "ambiguous_block_alignment" for item in differences.items
    )
    if definite_difference:
        status = "different"
    elif unsupported or ambiguous:
        status = "inconclusive"
    else:
        status = "pass"
    return {
        "schema": _SCHEMA,
        "comparison_scope": "structural",
        "status": status,
        "complete": False,
        "structural_complete": structural_complete,
        "coverage": coverage,
        "summary": {
            "reference_blocks": len(reference.blocks),
            "candidate_blocks": len(candidate.blocks),
            "reference_tables": _count_tables(reference.blocks),
            "candidate_tables": _count_tables(candidate.blocks),
            "reference_visible_text": _text_summary(reference.visible_text),
            "candidate_visible_text": _text_summary(candidate.visible_text),
            "ambiguous_block_signatures": len(set(ambiguous)),
            "unsupported_features": unsupported,
        },
        "differences": differences.items,
        "truncated": differences.truncated,
    }


def compare_hwpml(
    reference_hwpml: str,
    candidate_hwpml: str,
    *,
    max_differences: int = 100,
) -> dict[str, Any]:
    """HWPML 문자열 두 개를 정규화한 뒤 구조 비교한다."""

    return compare_structure(
        normalize_hwpml(reference_hwpml),
        normalize_hwpml(candidate_hwpml),
        max_differences=max_differences,
    )


__all__ = ["compare_hwpml", "compare_structure"]
