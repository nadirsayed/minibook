"""Calendars: cross-checked day by day against QuantLib (independent implementation)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
import QuantLib as ql
from dateutil.easter import easter
from hypothesis import given
from hypothesis import strategies as st

from minibook.dates.calendars import JP, TARGET, US, BusinessDayConvention, easter_sunday

QL = {
    "TARGET": (TARGET, ql.TARGET()),
    "US": (US, ql.UnitedStates(ql.UnitedStates.FederalReserve)),
    "JP": (JP, ql.Japan()),
}
# Margin so that rolling or advancing stays inside the supported years.
DATES = st.dates(min_value=date(2022, 2, 1), max_value=date(2030, 11, 30))


def qd(d: date) -> ql.Date:
    return ql.Date(d.day, d.month, d.year)


def pd_(d: ql.Date) -> date:
    return date(d.year(), d.month(), d.dayOfMonth())


@pytest.mark.parametrize("name", list(QL))
def test_business_days_match_quantlib_2022_2030(name: str) -> None:
    mine, ref = QL[name]
    d = date(2022, 1, 1)
    while d <= date(2030, 12, 31):
        assert mine.is_business_day(d) == ref.isBusinessDay(qd(d)), d
        d += timedelta(days=1)


def test_easter_matches_dateutil() -> None:
    for y in range(2022, 2100):
        assert easter_sunday(y) == easter(y)


@pytest.mark.parametrize(
    ("cal", "day", "why"),
    [
        (TARGET, date(2026, 4, 3), "Good Friday"),
        (TARGET, date(2026, 12, 26), "26 Dec"),
        (US, date(2026, 11, 11), "Veterans Day"),
        (US, date(2026, 11, 26), "Thanksgiving"),
        (JP, date(2026, 11, 3), "Culture Day"),
        (JP, date(2026, 9, 22), "citizens' holiday between 21 and 23 Sep"),
        (JP, date(2026, 5, 6), "substitute holiday for Sunday 3 May"),
        (JP, date(2026, 12, 31), "bank holiday"),
    ],
)
def test_known_holidays(cal: object, day: date, why: str) -> None:
    assert cal.is_holiday(day), why  # type: ignore[attr-defined]


def test_out_of_range_year_rejected() -> None:
    with pytest.raises(ValueError, match="implemented for"):
        TARGET.is_business_day(date(2001, 12, 31))


@pytest.mark.parametrize(
    ("conv", "qconv"),
    [
        (BusinessDayConvention.FOLLOWING, ql.Following),
        (BusinessDayConvention.MODIFIED_FOLLOWING, ql.ModifiedFollowing),
        (BusinessDayConvention.PRECEDING, ql.Preceding),
        (BusinessDayConvention.UNADJUSTED, ql.Unadjusted),
    ],
)
@given(d=DATES)
def test_adjust_matches_quantlib(conv: BusinessDayConvention, qconv: int, d: date) -> None:
    for mine, ref in QL.values():
        assert mine.adjust(d, conv) == pd_(ref.adjust(qd(d), qconv))


@given(d=DATES, n=st.integers(min_value=-10, max_value=10))
def test_advance_matches_quantlib(d: date, n: int) -> None:
    for mine, ref in QL.values():
        assert mine.advance(d, n) == pd_(ref.advance(qd(d), n, ql.Days))


def test_joint_calendar_and_business_days_between() -> None:
    joint = TARGET + US
    assert joint.is_holiday(date(2026, 11, 26))  # US only
    assert joint.is_holiday(date(2026, 12, 26))  # TARGET only (Saturday too)
    assert joint.name == "TARGET+US-FED"
    days = TARGET.business_days_between(date(2026, 12, 1), date(2026, 12, 31))
    assert len(days) == 22  # brief: 22 TARGET business days in December 2026
