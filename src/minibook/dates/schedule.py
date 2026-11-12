"""Regular coupon schedules (backward generation from maturity, no stub expected).

Unadjusted dates are ``maturity - k * period`` (k = 0, 1, ...) down to the effective date,
then each date is adjusted with the business-day convention. A short front stub is created
if the period does not divide the tenor. This matches QuantLib's
``DateGeneration.Backward`` with ``endOfMonth = False`` (cross-checked in tests).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import pairwise

from minibook.dates.calendars import BusinessDayConvention, Calendar
from minibook.dates.tenor import Tenor, add_months


@dataclass(frozen=True)
class Period:
    """One accrual period with adjusted start/end dates (payment on ``end``)."""

    start: date
    end: date


def schedule_dates(
    effective: date,
    maturity_unadjusted: date,
    period: Tenor,
    calendar: Calendar,
    convention: BusinessDayConvention,
) -> list[date]:
    """Return adjusted schedule dates, effective date first, maturity last."""
    months = period.months
    unadjusted = [maturity_unadjusted]
    k = 1
    while True:
        d = add_months(maturity_unadjusted, -k * months)
        if d <= effective:
            break
        unadjusted.append(d)
        k += 1
    unadjusted.append(effective)
    unadjusted.reverse()
    adjusted = [calendar.adjust(d, convention) for d in unadjusted]
    if len(set(adjusted)) != len(adjusted):
        raise ValueError(f"degenerate schedule: {adjusted}")
    return adjusted


def periods(dates: list[date]) -> list[Period]:
    """Consecutive accrual periods from schedule dates."""
    return [Period(a, b) for a, b in pairwise(dates)]


__all__ = ["BusinessDayConvention", "Period", "periods", "schedule_dates"]
