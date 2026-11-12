"""Hypothetical European cash-settled index option (BSM with continuous dividend yield).

These are *hypothetical* contracts: bespoke 3M/6M expiries and exact percentage strikes,
with the multipliers of the exchange-listed contracts (OESX, ODAX, PXA, MIBO). This is not
listed-contract replication.

Valuation at t0 = ``market.as_of``, T = ACT/365F(t0, expiry):

    PV_EUR = quantity * multiplier * BSM(S, K, T, r, q, sigma)

* S: index close on t0; sigma: flat vol proxy of the underlying (EWMA, ADR-002).
* r: EUR zero rate z(T) from the EUR AAA government curve (continuous compounding).
* q: trailing dividend yield from book.yaml. A missing q is a pricing error, so a report can
  never be produced with a placeholder.

On and after expiry the PV is 0. The cash settlement quantity * multiplier *
max(phi (S_expiry - K), 0) is paid on the expiry date, with S_expiry the closing level on
expiry. Simplification: listed contracts settle on an exchange settlement price, not the
close.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from minibook.config.settings import RiskSettings
from minibook.dates.daycount import DayCount, year_fraction
from minibook.instruments.base import Cashflow, GreekRow, Measure, PricingError
from minibook.instruments.bsm import BsmResult, OptionType, bsm
from minibook.market.snapshot import MarketSnapshot

CURRENCY = "EUR"
TIME_DC = DayCount.ACT_365F


@dataclass(frozen=True)
class EquityOption:
    """Immutable European cash-settled index option position."""

    id: str
    underlying: str
    option_type: OptionType
    quantity: float
    multiplier: float
    strike: float
    expiry: date

    def inputs(self, market: MarketSnapshot) -> tuple[float, float, float, float, float]:
        """(S, T, r, q, sigma) at ``market.as_of``."""
        u = self.underlying
        if u not in market.div_yields:
            raise PricingError(f"{self.id}: no dividend yield for {u} in the snapshot")
        t = year_fraction(market.as_of, self.expiry, TIME_DC)
        r = float(market.curve(CURRENCY).zero(max(t, 0.0)))
        return (float(market.spots[u]), t, r, float(market.div_yields[u]), float(market.vols[u]))

    def unit_result(self, market: MarketSnapshot) -> BsmResult:
        """BSM price and partials per unit of underlying (not scaled by position)."""
        s, t, r, q, sigma = self.inputs(market)
        return bsm(s, self.strike, t, r, q, sigma, self.option_type)

    @property
    def scale(self) -> float:
        """Quantity * multiplier: EUR per index point per unit of option value."""
        return self.quantity * self.multiplier

    def pv(self, market: MarketSnapshot) -> float:
        """PV in EUR; 0 on or after expiry (cash settled at expiry)."""
        if market.as_of >= self.expiry:
            return 0.0
        return self.scale * self.unit_result(market).price

    def analytic_greeks(self, market: MarketSnapshot, cfg: RiskSettings) -> list[GreekRow]:
        """Analytical BSM sensitivities in brief units (EUR); none on or after expiry.

        D = 0.01 S scale V_S, G = (0.01 S)^2 scale V_SS, Vega = 0.01 scale V_sigma,
        Div = cfg.div_yield_bump scale V_q (first order).
        """
        if market.as_of >= self.expiry:
            return []
        s = float(market.spots[self.underlying])
        res = self.unit_result(market)
        u = self.underlying
        return [
            GreekRow(self.id, Measure.DELTA_1PCT, f"EQ:{u}", 0.01 * s * self.scale * res.delta),
            GreekRow(
                self.id, Measure.GAMMA_1PCT, f"EQ:{u}", (0.01 * s) ** 2 * self.scale * res.gamma
            ),
            GreekRow(self.id, Measure.VEGA_1PT, f"VOL:{u}", 0.01 * self.scale * res.vega),
            GreekRow(
                self.id, Measure.DIV_10BP, f"DIV:{u}", cfg.div_yield_bump * self.scale * res.dq
            ),
        ]

    def cashflows(self, start: date, end: date, market: MarketSnapshot) -> list[Cashflow]:
        """Cash settlement at expiry if the expiry is in (start, end]."""
        if not start < self.expiry <= end:
            return []
        s = float(market.spots[self.underlying])
        payoff = max(self.option_type.phi * (s - self.strike), 0.0) * self.scale
        return [Cashflow(self.id, self.expiry, CURRENCY, payoff, payoff, "cash settlement")]
