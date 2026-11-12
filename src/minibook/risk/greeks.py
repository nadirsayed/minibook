"""Sensitivities of the book, all in EUR, all through the instruments' own pricers.

Sources of each measure (definitions in :class:`minibook.instruments.base.Measure`):

* analytical, from the instrument (checked against central finite differences in tests):
  option delta/gamma/vega/dividend sensitivity; FX forward delta/gamma on EUR/USD, EUR/JPY;
* revaluation, for every instrument:
  - THETA_1D = PV(market rolled 1 day) + cashflows in (t, t+1d] - PV(market), market held
    constant (ADR-020);
  - DV01 = [PV(curve + 1bp) - PV(curve - 1bp)] / 2, parallel, for EUR, USD and JPY;
  - KR_DV01 = the same with a key-rate tent at each key pillar.

Rows that are exactly zero (e.g. an option's USD DV01) are omitted.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Protocol, runtime_checkable

import pandas as pd

from minibook.config.settings import RiskSettings
from minibook.instruments.base import GreekRow, Instrument, Measure
from minibook.market.snapshot import KeyRate, MarketSnapshot, Parallel

COLUMNS = ["instrument_id", "measure", "risk_factor", "value"]


@runtime_checkable
class HasAnalyticGreeks(Protocol):
    """Instruments with analytical sensitivities (options, FX forwards)."""

    def analytic_greeks(self, market: MarketSnapshot, cfg: RiskSettings) -> list[GreekRow]:
        """Analytical sensitivities in brief units (EUR)."""
        ...


@runtime_checkable
class HasFixings(Protocol):
    """Instruments whose coupons fix on index fixings (swaps)."""

    def fixings_due(self, market: MarketSnapshot) -> dict[tuple[str, date], float]:
        """Return fixings dated ``market.as_of`` not yet in the snapshot."""
        ...


def with_todays_fixings(insts: Iterable[Instrument], market: MarketSnapshot) -> MarketSnapshot:
    """Snapshot with every fixing due today set (curve proxy, ADR-016)."""
    due: dict[tuple[str, date], float] = {}
    for inst in insts:
        if isinstance(inst, HasFixings):
            due.update(inst.fixings_due(market))
    return market.with_fixings({**market.fixings, **due}) if due else market


def theta(inst: Instrument, market: MarketSnapshot, days: int) -> float:
    """PV(t + days) + cashflows in (t, t + days] - PV(t), with the market held constant.

    Fixings due today are set first: rolling would otherwise turn them into past fixings.
    """
    market = with_todays_fixings([inst], market)
    rolled = market.roll(days)
    paid = sum(cf.amount_eur for cf in inst.cashflows(market.as_of, rolled.as_of, rolled))
    return inst.pv(rolled) + paid - inst.pv(market)


def central(
    inst: Instrument, market: MarketSnapshot, shape: KeyRate | Parallel, bump: float
) -> float:
    """[PV(+bump) - PV(-bump)] / 2 for a rate bump shape."""
    return 0.5 * (inst.pv(market.bump(shape, bump)) - inst.pv(market.bump(shape, -bump)))


def rate_sensitivities(inst: Instrument, market: MarketSnapshot, bump: float) -> list[GreekRow]:
    """Parallel DV01 and key-rate DV01 per currency, central differences (owner, ADR-020).

        DV01 = [PV(curve + 1bp) - PV(curve - 1bp)] / 2     (EUR per +1bp)

    The central difference has an O(bp^2) error, where the brief's original one-sided
    difference had an O(bp) convexity bias.
    """
    rows = []
    for ccy in sorted(market.curves):
        dv01 = central(inst, market, Parallel(ccy), bump)
        if dv01 == 0.0:
            continue
        rows.append(GreekRow(inst.id, Measure.DV01, f"PAR:{ccy}", dv01))
        for pillar in market.key_pillars:
            kr = central(inst, market, KeyRate(ccy, pillar), bump)
            if kr != 0.0:
                rows.append(GreekRow(inst.id, Measure.KR_DV01, f"KR:{ccy}:{pillar}", kr))
    return rows


def instrument_greeks(
    inst: Instrument, market: MarketSnapshot, cfg: RiskSettings
) -> list[GreekRow]:
    """All sensitivities of one instrument."""
    rows: list[GreekRow] = []
    if isinstance(inst, HasAnalyticGreeks):
        rows += inst.analytic_greeks(market, cfg)
    rows.append(GreekRow(inst.id, Measure.THETA_1D, "TIME", theta(inst, market, cfg.theta_days)))
    rows += rate_sensitivities(inst, market, cfg.rate_bump)
    return rows


def book_greeks(
    instruments: Iterable[Instrument], market: MarketSnapshot, cfg: RiskSettings
) -> pd.DataFrame:
    """Long table: instrument_id, measure, risk_factor, value (EUR)."""
    rows = [r for inst in instruments for r in instrument_greeks(inst, market, cfg)]
    return pd.DataFrame(
        [(r.instrument_id, r.measure.value, r.risk_factor, r.value) for r in rows],
        columns=COLUMNS,
    )


def by_risk_factor(greeks: pd.DataFrame) -> pd.DataFrame:
    """Book totals per (measure, risk factor)."""
    out = greeks.groupby(["measure", "risk_factor"], sort=True).agg(value=("value", "sum"))
    return out.reset_index()
