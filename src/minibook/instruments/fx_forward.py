"""Outright FX forward on BASE/QUOTE (quote currency units per 1 base unit).

Dates (market conventions, settings ``fx_conventions``)
------------------------------------------------------
Spot date = trade date + ``spot_lag`` business days counted on the non-USD calendar(s),
then rolled forward to a day that is a business day in *every* settlement calendar (USD
holidays only matter on the spot date itself). Delivery = spot date + tenor, modified
following on the joint settlement calendar, with the end-of-month rule: if the spot date
is the last business day of its month, delivery is the last business day of its month.

Valuation at t0 = ``market.as_of``
----------------------------------
S = ECB-derived spot for value date s(t0) (the pair's spot date seen from t0), T = delivery:

    F        = S * [DF_base(T) / DF_base(s)] / [DF_quote(T) / DF_quote(s)]
    PV_quote = N_base (F - K) DF_quote(T)
    PV_EUR   = PV_quote / (EUR/QUOTE)

N_base is signed (+ buy base). The brief writes F = S DF_base(T)/DF_quote(T), with S for value
today. Discounting from the spot date is the market standard, since S settles at spot
(ADR-015). It changes F by about (r_base - r_quote) x 2 days. At inception PV = 0 either
way, because K is the outright computed the same way.

After delivery (t0 >= T) the PV is 0, and the settlement N_base (S_T - K), in quote currency,
appears once as a cashflow on T, using the spot of that date.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date

from minibook.config.settings import RiskSettings
from minibook.dates.calendars import BusinessDayConvention, Calendar
from minibook.dates.daycount import DayCount, year_fraction
from minibook.dates.tenor import Tenor, add_tenor
from minibook.instruments.base import Cashflow, GreekRow, Measure, to_eur
from minibook.market.snapshot import MarketSnapshot

TIME_DC = DayCount.ACT_365F


@dataclass(frozen=True)
class FxConvention:
    """Spot-date rule of a currency pair."""

    spot_lag: int
    lag_calendar: Calendar
    settlement_calendar: Calendar

    def spot_date(self, trade_date: date) -> date:
        """Spot value date for a trade on ``trade_date``."""
        d = self.lag_calendar.advance(trade_date, self.spot_lag)
        return self.settlement_calendar.adjust(d, BusinessDayConvention.FOLLOWING)

    def delivery_date(self, spot: date, tenor: Tenor) -> date:
        """Spot + tenor, modified following, end-of-month rule (see module docstring)."""
        cal = self.settlement_calendar
        if cal.advance(spot, 1).month != spot.month:  # spot is the month's last business day
            target = add_tenor(spot, tenor)
            last_day = monthrange(target.year, target.month)[1]
            month_end = date(target.year, target.month, last_day)
            return cal.adjust(month_end, BusinessDayConvention.PRECEDING)
        return add_tenor(spot, tenor, cal, BusinessDayConvention.MODIFIED_FOLLOWING)


@dataclass(frozen=True)
class FxForward:
    """Immutable outright FX forward."""

    id: str
    base: str
    quote: str
    base_notional: float
    strike: float
    delivery: date
    convention: FxConvention

    def forward_rate(self, market: MarketSnapshot) -> float:
        """Outright F for delivery, seen from ``market.as_of`` (quote per base)."""
        t0 = market.as_of
        spot_value = self.convention.spot_date(t0)
        t_s = year_fraction(t0, spot_value, TIME_DC)
        t_d = year_fraction(t0, self.delivery, TIME_DC)
        b, q = market.curve(self.base), market.curve(self.quote)
        growth_b = float(b.df(t_d)) / float(b.df(t_s))
        growth_q = float(q.df(t_d)) / float(q.df(t_s))
        return market.fx_rate(self.base, self.quote) * growth_b / growth_q

    def pv_quote(self, market: MarketSnapshot) -> float:
        """PV in quote currency: N (F - K) DF_quote(T); 0 on or after delivery."""
        if market.as_of >= self.delivery:
            return 0.0
        t_d = year_fraction(market.as_of, self.delivery, TIME_DC)
        df_q = float(market.curve(self.quote).df(t_d))
        return self.base_notional * (self.forward_rate(market) - self.strike) * df_q

    def pv(self, market: MarketSnapshot) -> float:
        """PV in EUR."""
        return to_eur(self.pv_quote(market), self.quote, market)

    def analytic_greeks(self, market: MarketSnapshot, cfg: RiskSettings) -> list[GreekRow]:
        """FX delta/gamma on the EUR crosses X_c = EUR/c, including EUR translation.

        With g = [DF_b(T)/DF_b(s)] / [DF_q(T)/DF_q(s)] (curves only) and X_EUR = 1,
            PV_EUR = N DF_q(T) (g / X_b - K / X_q),
        so, for a non-EUR base:  V_Xb = -N DF_q g / X_b^2,  V_XbXb = 2 N DF_q g / X_b^3,
        and for a non-EUR quote: V_Xq =  N DF_q K / X_q^2,  V_XqXq = -2 N DF_q K / X_q^3.
        Reported as D = 0.01 X V_X and G = (0.01 X)^2 V_XX. No cross-gamma (separable).
        """
        del cfg  # FX Greeks are analytic; no bump size needed
        if market.as_of >= self.delivery:
            return []
        t_d = year_fraction(market.as_of, self.delivery, TIME_DC)
        df_q = float(market.curve(self.quote).df(t_d))
        x_b, x_q = market.fx_rate("EUR", self.base), market.fx_rate("EUR", self.quote)
        g = self.forward_rate(market) * x_b / x_q
        n = self.base_notional
        rows = []
        for ccy, x, v1, v2 in (
            (self.base, x_b, -n * df_q * g / x_b**2, 2.0 * n * df_q * g / x_b**3),
            (
                self.quote,
                x_q,
                n * df_q * self.strike / x_q**2,
                -2.0 * n * df_q * self.strike / x_q**3,
            ),
        ):
            if ccy == "EUR":
                continue
            rows.append(GreekRow(self.id, Measure.DELTA_1PCT, f"FX:{ccy}", 0.01 * x * v1))
            rows.append(GreekRow(self.id, Measure.GAMMA_1PCT, f"FX:{ccy}", (0.01 * x) ** 2 * v2))
        return rows

    def cashflows(self, start: date, end: date, market: MarketSnapshot) -> list[Cashflow]:
        """Net settlement N (S_T - K) in quote currency if delivery is in (start, end]."""
        if not start < self.delivery <= end:
            return []
        amount = self.base_notional * (market.fx_rate(self.base, self.quote) - self.strike)
        return [
            Cashflow(
                self.id,
                self.delivery,
                self.quote,
                amount,
                to_eur(amount, self.quote, market),
                "net settlement",
            )
        ]
