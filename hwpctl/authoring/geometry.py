"""Recover table tracks from raw cell measurements, never from outer extents.

This is a model/validation boundary, not a renderer.  Callers retain the original
HU values and must check ``exact`` before generating native authoring commands.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from hwpctl.reference.grid import GridEvidence, solve_grid_tracks


@dataclass(frozen=True)
class CellMeasurement:
    row: int
    column: int
    row_span: int
    column_span: int
    width_hu: int | None
    height_hu: int | None
    source: str


@dataclass(frozen=True)
class TableGeometry:
    columns: GridEvidence
    rows: GridEvidence
    issues: tuple[str, ...]
    sources: tuple[str, ...]

    @property
    def exact(self) -> bool:
        return not self.issues and self.columns.status == self.rows.status == "exact"


def recover_table_geometry(
    rows: int, columns: int, cells: Iterable[CellMeasurement],
) -> TableGeometry:
    """Solve both axes using every cell and validate the merge partition.

    Missing dimensions contribute no equation. Unknown tracks remain unknown;
    covered merge cells must not be supplied as independent cells. Sparse cell
    coverage is reported even when remaining measurements determine all tracks.
    ``source`` is an opaque location, such as a part name and XPath.
    """
    if any(type(n) is not int or not 1 <= n <= 256 for n in (rows, columns)):
        raise ValueError("table dimensions must be integers in 1..256")
    measurements = tuple(cells)
    occupied: dict[tuple[int, int], str] = {}
    widths: list[tuple[int, int, int]] = []
    heights: list[tuple[int, int, int]] = []
    issues: list[str] = []
    for cell in measurements:
        if not isinstance(cell, CellMeasurement):
            raise ValueError("expected CellMeasurement")
        if not isinstance(cell.source, str) or not cell.source:
            raise ValueError("each cell requires a source location")
        if any(type(n) is not int for n in (cell.row, cell.column, cell.row_span, cell.column_span)):
            raise ValueError(f"{cell.source}: cell addresses and spans must be integers")
        if (cell.row < 0 or cell.column < 0 or cell.row_span < 1 or cell.column_span < 1
                or cell.row + cell.row_span > rows or cell.column + cell.column_span > columns):
            raise ValueError(f"{cell.source}: cell span is outside table")
        for value in (cell.width_hu, cell.height_hu):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(f"{cell.source}: raw HU measurements must be positive integers or absent")
        for row in range(cell.row, cell.row + cell.row_span):
            for column in range(cell.column, cell.column + cell.column_span):
                previous = occupied.get((row, column))
                if previous is not None:
                    issues.append(f"overlap at ({row},{column}): {previous}, {cell.source}")
                else:
                    occupied[(row, column)] = cell.source
        if cell.width_hu is not None:
            widths.append((cell.column, cell.column_span, cell.width_hu))
        if cell.height_hu is not None:
            heights.append((cell.row, cell.row_span, cell.height_hu))
    missing = rows * columns - len(occupied)
    if missing:
        issues.append(f"incomplete cell coverage: {missing} grid slots")
    return TableGeometry(
        solve_grid_tracks(columns, widths), solve_grid_tracks(rows, heights),
        tuple(issues), tuple(cell.source for cell in measurements),
    )
