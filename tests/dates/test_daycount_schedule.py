"""Day counts, tenors and schedules, cross-checked against QuantLib."""

from __future__ import annotations

from datetime import date

import pytest
import QuantLib as ql
from hypothesis import given
from hypothesis import strategies as st

from minibook.dates.calendars import TARGET, BusinessDayConvention
from minibook.dates.daycount import DayCount, year_fraction
from minibook.dates.schedule import periods, schedule_dates
from minibook.dates.tenor import Tenor, add_months, add_tenor

QL_DC = {
    DayCount.ACT_360: ql.Actual360(),
    DayCount.ACT_365F: ql.Actual365Fixed(),
    DayCount.THIRTY_360_BOND: ql.Thirty360(ql.Thirty360.BondBasis),
}
DATES = st.dates(min_value=date(2000, 1, 1), max_value=date(2060, 12, 31))


def qd(d: date) -> ql.Date:
    return ql.Date(d.day, d.month, d.year)


@pytest.mark.parametrize("dc", list(DayCount))
@given(d1=DATES, d2=DATES)
def test_year_fraction_matches_quantlib(dc: DayCount, d1: date, d2: date) -> None:
    assert year_fraction(d1, d2, dc) == pytest.approx(
        QL_DC[dc].yearFraction(qd(d1), qd(d2)), abs=1e-14
    )


@pytest.mark.parametrize(
    ("d1", "d2", "days"),
    [
        # ISDA 2006 4.16(f): D1=31 -> 30; D2=31 -> 30 only if D1 is 30 (after adjustment).
        (date(2026, 1, 31), date(2026, 3, 31), 60),
        (date(2026, 2, 28), date(2026, 3, 31), 33),
        (date(2026, 1, 30), date(2026, 3, 31), 60),
        (date(2026, 1, 29), date(2026, 3, 31), 62),
    ],
)
def test_thirty_360_bond_basis_end_of_month(d1: date, d2: date, days: int) -> None:
    assert year_fraction(d1, d2, DayCount.THIRTY_360_BOND) * 360 == pytest.approx(days)


def test_tenor_parsing_and_years() -> None:
    assert Tenor.parse("3m") == Tenor(3, "M")
    assert str(Tenor.parse("10Y")) == "10Y"
    assert Tenor.parse("18M").years == 1.5
    assert Tenor.parse("1M").years == pytest.approx(1 / 12)
    assert Tenor.parse("2W").years == pytest.approx(14 / 365)
    assert Tenor.parse("2D").years == pytest.approx(2 / 365)
    with pytest.raises(ValueError, match="invalid tenor"):
        Tenor.parse("5X")
    with pytest.raises(ValueError, match="no whole number"):
        _ = Tenor.parse("2D").months


def test_add_months_clips_month_end() -> None:
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 30), -12) == date(2025, 11, 30)
    assert add_tenor(date(2026, 11, 2), Tenor.parse("2D")) == date(2026, 11, 4)
    assert add_tenor(date(2026, 11, 2), Tenor.parse("1W")) == date(2026, 11, 9)
    assert add_tenor(
        date(2026, 5, 30), Tenor.parse("1M"), TARGET, BusinessDayConvention.MODIFIED_FOLLOWING
    ) == date(2026, 6, 30)


@pytest.mark.parametrize("effective", [date(2026, 11, 4), date(2026, 11, 30), date(2027, 2, 26)])
@pytest.mark.parametrize("period", ["1Y", "6M", "3M"])
def test_schedule_matches_quantlib_backward(effective: date, period: str) -> None:
    maturity = add_months(effective, 60)
    mine = schedule_dates(
        effective, maturity, Tenor.parse(period), TARGET, BusinessDayConvention.MODIFIED_FOLLOWING
    )
    ref = ql.Schedule(
        qd(effective),
        qd(maturity),
        ql.Period(period),
        ql.TARGET(),
        ql.ModifiedFollowing,
        ql.ModifiedFollowing,
        ql.DateGeneration.Backward,
        False,
    )
    assert mine == [date(d.year(), d.month(), d.dayOfMonth()) for d in ref]
    ps = periods(mine)
    assert ps[0].start == mine[0] and ps[-1].end == mine[-1]


def test_schedule_with_front_stub() -> None:
    dates = schedule_dates(
        date(2026, 11, 4),
        date(2027, 6, 4),
        Tenor.parse("6M"),
        TARGET,
        BusinessDayConvention.MODIFIED_FOLLOWING,
    )
    assert dates == [date(2026, 11, 4), date(2026, 12, 4), date(2027, 6, 4)]
