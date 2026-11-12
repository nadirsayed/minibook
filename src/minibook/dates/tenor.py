"""Tenors such as ``"3M"``, ``"5Y"``, ``"2D"``: parsing, date arithmetic and year length."""

from __future__ import annotations

import calendar as _cal
import re
from dataclasses import dataclass
from datetime import date, timedelta

from minibook.dates.calendars import BusinessDayConvention, Calendar

MONTHS_PER_YEAR = 12
DAYS_PER_YEAR_NOMINAL = 365.0
_TENOR_RE = re.compile(r"^(\d+)([DWMY])$")


@dataclass(frozen=True, order=True)
class Tenor:
    """A period of ``n`` units, unit in D (calendar days), W, M or Y."""

    n: int
    unit: str

    @classmethod
    def parse(cls, text: str) -> Tenor:
        """Parse ``"3M"``-style text."""
        m = _TENOR_RE.match(text.strip().upper())
        if m is None:
            raise ValueError(f"invalid tenor {text!r}")
        return cls(int(m.group(1)), m.group(2))

    def __str__(self) -> str:
        """Return the canonical text form, e.g. ``"3M"``."""
        return f"{self.n}{self.unit}"

    @property
    def months(self) -> int:
        """Length in months (``ValueError`` for day/week tenors)."""
        if self.unit == "M":
            return self.n
        if self.unit == "Y":
            return self.n * MONTHS_PER_YEAR
        raise ValueError(f"tenor {self} has no whole number of months")

    @property
    def years(self) -> float:
        """Nominal length in years: n/12 for months, n for years, n/365 for days.

        This is the curve-pillar time convention: a 3M pillar sits at t = 0.25.
        """
        if self.unit == "D":
            return self.n / DAYS_PER_YEAR_NOMINAL
        if self.unit == "W":
            return 7 * self.n / DAYS_PER_YEAR_NOMINAL
        return self.months / MONTHS_PER_YEAR


def add_months(d: date, months: int) -> date:
    """Calendar month arithmetic, clipping the day to the end of the target month."""
    total = d.year * MONTHS_PER_YEAR + (d.month - 1) + months
    year, month0 = divmod(total, MONTHS_PER_YEAR)
    last = _cal.monthrange(year, month0 + 1)[1]
    return date(year, month0 + 1, min(d.day, last))


def add_tenor(
    d: date,
    tenor: Tenor,
    calendar: Calendar | None = None,
    convention: BusinessDayConvention = BusinessDayConvention.UNADJUSTED,
) -> date:
    """``d + tenor``, then adjusted on ``calendar`` (if given) with ``convention``."""
    if tenor.unit == "D":
        out = d + timedelta(days=tenor.n)
    elif tenor.unit == "W":
        out = d + timedelta(weeks=tenor.n)
    else:
        out = add_months(d, tenor.months)
    return out if calendar is None else calendar.adjust(out, convention)
