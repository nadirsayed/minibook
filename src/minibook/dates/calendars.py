"""Business-day calendars: TARGET, US (Federal Reserve) and Japan (Tokyo).

Rules are implemented from their official definitions and cross-checked against QuantLib
in the tests (TARGET, ``UnitedStates.FederalReserve`` and ``Japan``, years 2022-2030).

Supported years
---------------
:data:`MIN_YEAR` to :data:`MAX_YEAR`. Outside that range a ``ValueError`` is raised instead
of giving silently wrong answers. Rule changes before 2022 are not modelled: TARGET's
31 Dec closures in 1999-2001, and Japan's 2020/2021 Olympic holiday moves. The Japanese
equinox formula is the standard approximation; the official dates are announced each year.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from functools import cache

MIN_YEAR, MAX_YEAR = 2022, 2099
SATURDAY, SUNDAY = 5, 6
MONDAY, THURSDAY = 0, 3


class BusinessDayConvention(StrEnum):
    """How a date falling on a holiday is rolled."""

    FOLLOWING = "following"
    MODIFIED_FOLLOWING = "modified_following"
    PRECEDING = "preceding"
    UNADJUSTED = "unadjusted"


def easter_sunday(year: int) -> date:
    """Gregorian Easter Sunday (anonymous Gregorian algorithm, Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month, day = divmod(h + ell - 7 * m + 114, 31)
    return date(year, month, day + 1)


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the n-th (1-based) ``weekday`` (Mon=0) of a month; ``n = -1`` gives the last."""
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    nxt = date(year + month // 12, month % 12 + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _check_year(year: int) -> None:
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise ValueError(f"calendar rules implemented for {MIN_YEAR}-{MAX_YEAR}, got {year}")


# ----------------------------------------------------------------------------- TARGET
@cache
def target_holidays(year: int) -> frozenset[date]:
    """TARGET2 closing days (ECB, in force since 2002), weekends excluded.

    New Year's Day, Good Friday, Easter Monday, 1 May, 25 and 26 December.
    """
    _check_year(year)
    easter = easter_sunday(year)
    return frozenset(
        {
            date(year, 1, 1),
            easter - timedelta(days=2),
            easter + timedelta(days=1),
            date(year, 5, 1),
            date(year, 12, 25),
            date(year, 12, 26),
        }
    )


# ----------------------------------------------------------------------- US (Fed Reserve)
def _fed_observed(d: date) -> date | None:
    """Federal Reserve observance: Sunday -> Monday; a Saturday holiday is not observed."""
    if d.weekday() == SUNDAY:
        return d + timedelta(days=1)
    if d.weekday() == SATURDAY:
        return None
    return d


@cache
def us_fed_holidays(year: int) -> frozenset[date]:
    """Federal Reserve Bank holidays (Fedwire, USD settlement).

    Fixed-date holidays: New Year's Day, Juneteenth (since 2022), Independence Day,
    Veterans Day, Christmas. They move to Monday when they fall on a Sunday and are not
    observed when they fall on a Saturday. Floating holidays: MLK Day (3rd Mon Jan),
    Presidents Day (3rd Mon Feb), Memorial Day (last Mon May), Labor Day (1st Mon Sep),
    Columbus Day (2nd Mon Oct), Thanksgiving (4th Thu Nov).
    Source: https://www.federalreserve.gov/aboutthefed/k8.htm
    """
    _check_year(year)
    fixed = [
        date(year, 1, 1),
        date(year, 6, 19),
        date(year, 7, 4),
        date(year, 11, 11),
        date(year, 12, 25),
    ]
    observed = {o for o in (_fed_observed(d) for d in fixed) if o is not None}
    floating = {
        nth_weekday(year, 1, MONDAY, 3),
        nth_weekday(year, 2, MONDAY, 3),
        nth_weekday(year, 5, MONDAY, -1),
        nth_weekday(year, 9, MONDAY, 1),
        nth_weekday(year, 10, MONDAY, 2),
        nth_weekday(year, 11, THURSDAY, 4),
    }
    return frozenset(observed | floating)


# ------------------------------------------------------------------------------- Japan
def _vernal_equinox(year: int) -> date:
    """Approximate vernal equinox day in Japan (standard formula, valid 1980-2099)."""
    y = year - 1980
    return date(year, 3, int(20.8431 + 0.242194 * y - y // 4))


def _autumnal_equinox(year: int) -> date:
    """Approximate autumnal equinox day in Japan (standard formula, valid 1980-2099)."""
    y = year - 1980
    return date(year, 9, int(23.2488 + 0.242194 * y - y // 4))


@cache
def japan_holidays(year: int) -> frozenset[date]:
    """Tokyo bank holidays: national holidays plus 31 Dec and 1-3 Jan.

    National holidays follow the Act on National Holidays (rules in force since 2020):
    a holiday on Sunday moves to the next non-holiday weekday (substitute holiday), and a
    weekday sandwiched between two holidays is a holiday (citizens' holiday).
    Bank closures on 31 Dec and 2-3 Jan: Banking Act Enforcement Order, art. 5.
    """
    _check_year(year)
    national = {
        date(year, 1, 1),
        nth_weekday(year, 1, MONDAY, 2),  # Coming of Age Day
        date(year, 2, 11),  # National Foundation Day
        date(year, 2, 23),  # Emperor's Birthday (since 2020)
        _vernal_equinox(year),
        date(year, 4, 29),  # Showa Day
        date(year, 5, 3),  # Constitution Memorial Day
        date(year, 5, 4),  # Greenery Day
        date(year, 5, 5),  # Children's Day
        nth_weekday(year, 7, MONDAY, 3),  # Marine Day
        date(year, 8, 11),  # Mountain Day
        nth_weekday(year, 9, MONDAY, 3),  # Respect for the Aged Day
        _autumnal_equinox(year),
        nth_weekday(year, 10, MONDAY, 2),  # Sports Day
        date(year, 11, 3),  # Culture Day
        date(year, 11, 23),  # Labour Thanksgiving Day
    }
    # Both rules below derive from national holidays proper (Act art. 3(2) and 3(3)), so
    # neither feeds into the other.
    # Substitute holiday: a national holiday on Sunday -> next day that is not one.
    substitutes = set()
    for d in sorted(national):
        if d.weekday() == SUNDAY:
            sub = d + timedelta(days=1)
            while sub in national:
                sub += timedelta(days=1)
            substitutes.add(sub)
    # Citizens' holiday: a day whose previous and next days are national holidays
    # (e.g. 22 Sep 2026, between Respect for the Aged Day and the autumnal equinox).
    citizens = {
        d + timedelta(days=1)
        for d in national
        if d + timedelta(days=1) not in national and d + timedelta(days=2) in national
    }
    bank = {date(year, 1, 2), date(year, 1, 3), date(year, 12, 31)}
    return frozenset(national | substitutes | citizens | bank)


# ------------------------------------------------------------------ equity exchanges
def _easter_closures(year: int) -> set[date]:
    easter = easter_sunday(year)
    return {easter - timedelta(days=2), easter + timedelta(days=1)}


@cache
def euronext_paris_holidays(year: int) -> frozenset[date]:
    """Euronext Paris cash-market closures.

    1 Jan, Good Friday, Easter Monday, 1 May, 25 and 26 Dec. On 24 and 31 Dec the market
    closes early but still publishes a close.

    Checked against the CAC 40 daily closes, 2023-01..2026-11 (tests).
    """
    _check_year(year)
    return frozenset(
        {date(year, 1, 1), date(year, 5, 1), date(year, 12, 25), date(year, 12, 26)}
        | _easter_closures(year)
    )


@cache
def xetra_holidays(year: int) -> frozenset[date]:
    """Xetra / Eurex closures: as Euronext Paris, plus 24 and 31 Dec.

    Checked against the DAX daily closes, 2023-01..2026-11 (tests).
    """
    return euronext_paris_holidays(year) | {date(year, 12, 24), date(year, 12, 31)}


@cache
def borsa_italiana_holidays(year: int) -> frozenset[date]:
    """Borsa Italiana closures: as Xetra, plus 15 Aug (Ferragosto).

    Checked against the FTSE MIB daily closes, 2023-01..2026-11 (tests).
    """
    return xetra_holidays(year) | {date(year, 8, 15)}


# --------------------------------------------------------------------------- Calendar
@dataclass(frozen=True)
class Calendar:
    """A business-day calendar defined by a per-year holiday function.

    A day is a business day if it is a weekday and not a holiday of *any* of the component
    holiday functions (joint calendar).
    """

    name: str
    holiday_fns: tuple[Callable[[int], frozenset[date]], ...] = field(repr=False)

    def is_holiday(self, d: date) -> bool:
        """Return True if ``d`` is a weekend day or a holiday."""
        if d.weekday() >= SATURDAY:
            return True
        return any(d in fn(d.year) for fn in self.holiday_fns)

    def is_business_day(self, d: date) -> bool:
        """Return True if ``d`` is a business day."""
        return not self.is_holiday(d)

    def adjust(self, d: date, convention: BusinessDayConvention) -> date:
        """Roll ``d`` to a business day.

        Modified following: the following business day, unless it falls in the next month,
        in which case the preceding business day.
        """
        if convention is BusinessDayConvention.UNADJUSTED or self.is_business_day(d):
            return d
        if convention is BusinessDayConvention.PRECEDING:
            return self._roll(d, -1)
        following = self._roll(d, 1)
        if convention is BusinessDayConvention.MODIFIED_FOLLOWING and following.month != d.month:
            return self._roll(d, -1)
        return following

    def _roll(self, d: date, step: int) -> date:
        while self.is_holiday(d):
            d += timedelta(days=step)
        return d

    def advance(self, d: date, n: int) -> date:
        """Move ``n`` business days (``n`` may be negative). ``n = 0`` rolls forward."""
        if n == 0:
            return self._roll(d, 1)
        step = 1 if n > 0 else -1
        for _ in range(abs(n)):
            d += timedelta(days=step)
            d = self._roll(d, step)
        return d

    def business_days_between(self, start: date, end: date) -> list[date]:
        """Return the business days in [start, end]."""
        out, d = [], start
        while d <= end:
            if self.is_business_day(d):
                out.append(d)
            d += timedelta(days=1)
        return out

    def __add__(self, other: Calendar) -> Calendar:
        """Joint calendar: holiday in either calendar."""
        return Calendar(f"{self.name}+{other.name}", self.holiday_fns + other.holiday_fns)


TARGET = Calendar("TARGET", (target_holidays,))
US = Calendar("US-FED", (us_fed_holidays,))
JP = Calendar("JP", (japan_holidays,))
EURONEXT_PARIS = Calendar("EURONEXT_PARIS", (euronext_paris_holidays,))
XETRA = Calendar("XETRA", (xetra_holidays,))
# Eurex (EURO STOXX 50 derivatives and index calculation days) follows the Xetra calendar.
EUREX = Calendar("EUREX", (xetra_holidays,))
BORSA_ITALIANA = Calendar("BORSA_ITALIANA", (borsa_italiana_holidays,))

CALENDARS: dict[str, Calendar] = {
    c.name: c for c in (TARGET, US, JP, EURONEXT_PARIS, XETRA, EUREX, BORSA_ITALIANA)
}
