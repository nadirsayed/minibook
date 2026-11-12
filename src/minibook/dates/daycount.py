"""Day-count conventions.

ACT/360:   tau = (d2 - d1) / 360
ACT/365F:  tau = (d2 - d1) / 365
30/360 Bond Basis (ISDA 2006 Definitions, section 4.16(f)):
    tau = [360 (Y2 - Y1) + 30 (M2 - M1) + (D2 - D1)] / 360,
    with D1 = 30 if D1 = 31, and D2 = 30 if D2 = 31 and D1 (after adjustment) is 30.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

DAYS_360, DAYS_365 = 360.0, 365.0
MONTHS_PER_YEAR = 12
THIRTY, THIRTY_ONE = 30, 31


class DayCount(StrEnum):
    """Supported day-count conventions."""

    ACT_360 = "ACT/360"
    ACT_365F = "ACT/365F"
    THIRTY_360_BOND = "30/360 Bond Basis"


def _thirty_360_bond(d1: date, d2: date) -> float:
    dd1, dd2 = d1.day, d2.day
    if dd1 == THIRTY_ONE:
        dd1 = THIRTY
    if dd2 == THIRTY_ONE and dd1 == THIRTY:
        dd2 = THIRTY
    days = 360 * (d2.year - d1.year) + 30 * (d2.month - d1.month) + (dd2 - dd1)
    return days / DAYS_360


def year_fraction(d1: date, d2: date, convention: DayCount) -> float:
    """Accrual fraction from ``d1`` to ``d2`` (negative if ``d2 < d1``)."""
    if convention is DayCount.ACT_360:
        return (d2 - d1).days / DAYS_360
    if convention is DayCount.ACT_365F:
        return (d2 - d1).days / DAYS_365
    return _thirty_360_bond(d1, d2)
