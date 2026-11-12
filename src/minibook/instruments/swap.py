"""Vanilla EUR interest rate swap: fixed vs EURIBOR 6M (single-curve).

Conventions (book.yaml, matching QuantLib ``EuriborSwapIsdaFixA``)
-------------------------------------------------------------------
* Effective date: trade date + 2 TARGET business days. Maturity: effective + tenor.
* Fixed leg: annual, 30/360 Bond Basis. Float leg: semi-annual, ACT/360, EURIBOR 6M fixed
  2 TARGET business days before each accrual start. Modified following on TARGET,
  backward schedule generation, payment on the adjusted accrual end.

Valuation at t0 = ``market.as_of`` (only payments with pay date > t0 are included)
-------------------------------------------------------------------------------------
    PV_fixed = N K       sum_i tau_i^{30/360}  DF(t_i)
    PV_float = N         sum_j L_j tau_j^{ACT/360} DF(t_j)
    PV       = s (PV_float - PV_fixed),   s = +1 payer (pay fixed), -1 receiver

with DF from the EUR zero curve and t = ACT/365F(t0, date). The coupon rate L_j is:
* fixing date < t0: the stored fixing (missing => error, never recomputed);
* fixing date = t0: the stored fixing if present, otherwise the curve proxy below;
* fixing date > t0: the projected forward over the accrual period,
      L_j = (DF(s_j) / DF(e_j) - 1) / tau_j^{ACT/360}.

Single-curve simplification: the EUR AAA government curve is used both to discount and to
project EURIBOR. There is no EURIBOR-€STR basis, and accrual-period forwards stand in for
the index-tenor forwards ("par coupon" approximation).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from minibook.dates.calendars import TARGET, BusinessDayConvention
from minibook.dates.daycount import DayCount, year_fraction
from minibook.dates.schedule import Period, periods, schedule_dates
from minibook.dates.tenor import Tenor, add_tenor
from minibook.instruments.base import Cashflow, PricingError
from minibook.market.curves import ZeroCurve
from minibook.market.snapshot import MarketSnapshot

CURRENCY = "EUR"
TIME_DC = DayCount.ACT_365F


@dataclass(frozen=True)
class FloatCoupon:
    """A floating accrual period and its fixing date."""

    period: Period
    fixing_date: date


@dataclass(frozen=True)
class InterestRateSwap:
    """Immutable fixed-vs-float swap. Build with :meth:`create`."""

    id: str
    notional: float
    fixed_rate: float
    pay_fixed: bool
    index: str
    effective: date
    maturity: date
    fixed_periods: tuple[Period, ...]
    float_coupons: tuple[FloatCoupon, ...]
    fixed_day_count: DayCount = DayCount.THIRTY_360_BOND
    float_day_count: DayCount = DayCount.ACT_360

    @classmethod
    def create(
        cls,
        id: str,  # noqa: A002 - matches book.yaml field
        trade_date: date,
        notional: float,
        fixed_rate: float,
        pay_fixed: bool,
        tenor: str = "5Y",
        fixed_frequency: str = "1Y",
        float_frequency: str = "6M",
        spot_lag: int = 2,
        fixing_lag: int = 2,
        index: str = "EURIBOR6M",
        convention: BusinessDayConvention = BusinessDayConvention.MODIFIED_FOLLOWING,
    ) -> InterestRateSwap:
        """Generate the schedules from the trade date (TARGET calendar)."""
        effective = TARGET.advance(trade_date, spot_lag)
        end = add_tenor(effective, Tenor.parse(tenor))
        fixed = periods(
            schedule_dates(effective, end, Tenor.parse(fixed_frequency), TARGET, convention)
        )
        flt = periods(
            schedule_dates(effective, end, Tenor.parse(float_frequency), TARGET, convention)
        )
        coupons = tuple(FloatCoupon(p, TARGET.advance(p.start, -fixing_lag)) for p in flt)
        return cls(
            id,
            notional,
            fixed_rate,
            pay_fixed,
            index,
            effective,
            fixed[-1].end,
            tuple(fixed),
            coupons,
        )

    # ------------------------------------------------------------------ helpers
    @property
    def sign(self) -> float:
        """+1 for a payer swap (pay fixed, receive float), -1 for a receiver."""
        return 1.0 if self.pay_fixed else -1.0

    def _df(self, curve: ZeroCurve, as_of: date, d: date) -> float:
        return float(curve.df(year_fraction(as_of, d, TIME_DC)))

    def projected_rate(self, coupon: FloatCoupon, market: MarketSnapshot) -> float:
        """Curve forward over the accrual period (also the fixing proxy on its fixing date)."""
        curve = market.curve(CURRENCY)
        tau = year_fraction(coupon.period.start, coupon.period.end, self.float_day_count)
        df_s = self._df(curve, market.as_of, coupon.period.start)
        df_e = self._df(curve, market.as_of, coupon.period.end)
        return (df_s / df_e - 1.0) / tau

    def coupon_rate(self, coupon: FloatCoupon, market: MarketSnapshot) -> float:
        """Rate of a floating coupon at ``market.as_of`` (see module docstring)."""
        stored = market.fixing(self.index, coupon.fixing_date)
        if coupon.fixing_date < market.as_of:
            if stored is None:
                raise PricingError(
                    f"{self.id}: no stored {self.index} fixing for {coupon.fixing_date}; past "
                    "fixings are never recomputed from a later curve"
                )
            return stored
        if coupon.fixing_date == market.as_of and stored is not None:
            return stored
        return self.projected_rate(coupon, market)

    # ---------------------------------------------------------------- valuation
    def annuity(self, market: MarketSnapshot) -> float:
        """sum_i N tau_i DF(t_i) over unpaid fixed periods (EUR per unit rate)."""
        curve = market.curve(CURRENCY)
        return sum(
            self.notional
            * year_fraction(p.start, p.end, self.fixed_day_count)
            * self._df(curve, market.as_of, p.end)
            for p in self.fixed_periods
            if p.end > market.as_of
        )

    def fixed_leg_pv(self, market: MarketSnapshot) -> float:
        """PV of the fixed leg (positive number, EUR)."""
        return self.fixed_rate * self.annuity(market)

    def float_leg_pv(self, market: MarketSnapshot) -> float:
        """PV of the floating leg (positive number, EUR)."""
        curve = market.curve(CURRENCY)
        total = 0.0
        for c in self.float_coupons:
            if c.period.end <= market.as_of:
                continue
            tau = year_fraction(c.period.start, c.period.end, self.float_day_count)
            total += (
                self.notional
                * self.coupon_rate(c, market)
                * tau
                * self._df(curve, market.as_of, c.period.end)
            )
        return total

    def pv(self, market: MarketSnapshot) -> float:
        """PV in EUR: sign * (PV_float - PV_fixed)."""
        return self.sign * (self.float_leg_pv(market) - self.fixed_leg_pv(market))

    def par_rate(self, market: MarketSnapshot) -> float:
        """Return the fixed rate that makes PV = 0: PV_float / annuity."""
        return self.float_leg_pv(market) / self.annuity(market)

    def cashflows(self, start: date, end: date, market: MarketSnapshot) -> list[Cashflow]:
        """Coupons paid in (start, end]: fixed (sign -s), floating (sign +s).

        Floating amounts use the coupon's stored fixing, which must exist because its
        fixing date is before the pay date.
        """
        out = []
        for p in self.fixed_periods:
            if start < p.end <= end:
                amt = (
                    -self.sign
                    * self.notional
                    * self.fixed_rate
                    * year_fraction(p.start, p.end, self.fixed_day_count)
                )
                out.append(Cashflow(self.id, p.end, CURRENCY, amt, amt, "fixed coupon"))
        for c in self.float_coupons:
            if start < c.period.end <= end:
                rate = market.fixing(self.index, c.fixing_date)
                if rate is None:
                    raise PricingError(f"{self.id}: missing fixing {c.fixing_date} for coupon")
                amt = (
                    self.sign
                    * self.notional
                    * rate
                    * year_fraction(c.period.start, c.period.end, self.float_day_count)
                )
                out.append(Cashflow(self.id, c.period.end, CURRENCY, amt, amt, "float coupon"))
        return out
