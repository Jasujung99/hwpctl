"""Exact cell-span constraints. Never fill unknown tracks by a heuristic.

This is geometry evidence, not an automatic layout engine. Shape extents and cell
tracks may describe different boxes; callers must not silently rescale one to the other.
"""
from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable


@dataclass(frozen=True)
class GridEvidence:
    status: str  # exact, underdetermined, inconsistent
    tracks_hwp: tuple[Fraction | None, ...]
    constraint_count: int


def solve_grid_tracks(count: int, constraints: Iterable[tuple[int, int, int]]) -> GridEvidence:
    """Solve sum(tracks[start:start+span]) == raw HU width, without rounding.

    Inputs must be integer HU facts. Contradictory measurements stay contradictory;
    callers can explicitly compare tolerances later but this solver invents none.
    """
    if type(count) is not int or not 0 < count <= 256:
        raise ValueError("track count must be an integer in 1..256")
    equations = list(constraints)
    matrix = []
    for start, span, width in equations:
        if any(type(value) is not int for value in (start, span, width)):
            raise ValueError("grid facts must be integer HU and indexes")
        if start < 0 or span < 1 or start + span > count or width <= 0:
            raise ValueError("invalid cell-span constraint")
        matrix.append([Fraction(int(start <= i < start + span)) for i in range(count)] + [Fraction(width)])
    pivot_rows = {}
    row = 0
    for col in range(count):
        pivot = next((i for i in range(row, len(matrix)) if matrix[i][col]), None)
        if pivot is None:
            continue
        matrix[row], matrix[pivot] = matrix[pivot], matrix[row]
        divisor = matrix[row][col]
        matrix[row] = [value / divisor for value in matrix[row]]
        for i in range(len(matrix)):
            if i != row and matrix[i][col]:
                factor = matrix[i][col]
                matrix[i] = [a - factor * b for a, b in zip(matrix[i], matrix[row])]
        pivot_rows[col] = row
        row += 1
    empty = (None,) * count
    if any(not any(values[:-1]) and values[-1] for values in matrix):
        return GridEvidence("inconsistent", empty, len(equations))
    free = set(range(count)) - pivot_rows.keys()
    tracks = tuple(
        matrix[pivot_rows[col]][-1]
        if col in pivot_rows and not any(matrix[pivot_rows[col]][i] for i in free)
        else None
        for col in range(count)
    )
    if any(value is not None and value <= 0 for value in tracks):
        return GridEvidence("inconsistent", empty, len(equations))
    return GridEvidence("underdetermined" if free else "exact", tracks, len(equations))
