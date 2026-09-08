"""Explicit physical-unit conversions; no document-specific margin corrections."""
from math import isfinite

HWP_UNITS_PER_INCH = 7200
MM_PER_INCH = 25.4


def finite_number(value: float, *, label: str = "value") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    number = float(value)
    if not isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def mm_to_hwpunit(value: float) -> int:
    """Round once to the nearest HU (Python ties-to-even). Signed offsets allowed."""
    return round(finite_number(value) * HWP_UNITS_PER_INCH / MM_PER_INCH)


def hwpunit_to_mm(value: float) -> float:
    return finite_number(value) * MM_PER_INCH / HWP_UNITS_PER_INCH


def hwpunit_to_points(value: float) -> float:
    return finite_number(value) / 100
