"""Joint historical scenarios for 1-day historical-simulation VaR.

For valuation date D and N scenarios, take the N + 1 consecutive TARGET business days
d_0 < ... < d_N = D and their market snapshots (each built only from data dated on or
before its own date: no look-ahead). Scenario i (labelled d_i) is the 1-day move
d_{i-1} -> d_i of every risk factor, with the brief's shock types:

* zero rate at each curve pillar, per currency: absolute change, z(d_i) - z(d_{i-1});
* FX rates (EUR/ccy) and equity index levels: log return, ln(X(d_i) / X(d_{i-1}));
* vols: absolute change.

The shocks are applied jointly to the snapshot of D with ``MarketSnapshot.apply``, which
uses the same units, so a scenario preserves the cross-factor co-movement of its day. The
valuation date stays D: time decay and cashflows are not part of VaR.

Days on which a market was closed carry the last value (forward-fill rules, ADR-011), so
that factor has a zero shock and the reopening day carries the whole multi-day move
(methodology §1).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from minibook.dates.calendars import TARGET
from minibook.market.snapshot import EquitySpot, FxSpot, MarketSnapshot, RiskFactor, Vol, ZeroRate

LOG_SHOCK = (FxSpot, EquitySpot)
ABS_SHOCK = (ZeroRate, Vol)


@dataclass(frozen=True)
class ScenarioSet:
    """N joint shocks: ``shocks[i, j]`` is the move of ``factors[j]`` on ``dates[i]``."""

    as_of: date
    dates: tuple[date, ...]
    factors: tuple[RiskFactor, ...]
    shocks: np.ndarray

    def __len__(self) -> int:
        """Return the number of scenarios."""
        return len(self.dates)

    def as_mapping(self, i: int) -> dict[RiskFactor, float]:
        """Shocks of scenario ``i`` keyed by risk factor (input of ``MarketSnapshot.apply``)."""
        return dict(zip(self.factors, self.shocks[i].tolist(), strict=True))


def transformed_level(snap: MarketSnapshot, factor: RiskFactor) -> float:
    """Level in shock space: log for FX and equity, raw for zero rates and vols."""
    level = snap.value(factor)
    if isinstance(factor, LOG_SHOCK):
        return float(np.log(level))
    if isinstance(factor, ABS_SHOCK):
        return level
    raise TypeError(f"{factor!r} is not a VaR risk factor")


def scenario_dates(as_of: date, n: int) -> list[date]:
    """Return the N + 1 TARGET business days ending at ``as_of`` (inclusive)."""
    if not TARGET.is_business_day(as_of):
        raise ValueError(f"{as_of} is not a TARGET business day")
    start = TARGET.advance(as_of, -n)
    days = TARGET.business_days_between(start, as_of)
    if len(days) != n + 1:
        raise RuntimeError(f"expected {n + 1} TARGET days, got {len(days)}")
    return days


def historical_scenarios(
    snapshot_for: Callable[[date], MarketSnapshot],
    as_of: date,
    n: int,
    factors: Sequence[RiskFactor] | None = None,
) -> ScenarioSet:
    """Build N joint 1-day shocks ending at ``as_of`` (module docstring).

    Parameters
    ----------
    snapshot_for
        Returns the snapshot of a date, built from data on or before that date.
    as_of
        Valuation date D (its snapshot provides the factor list if ``factors`` is None).
    n
        Number of scenarios (brief: 500, so 501 aligned snapshots are needed).
    """
    days = scenario_dates(as_of, n)
    snaps = [snapshot_for(d) for d in days]
    facs = tuple(factors if factors is not None else snaps[-1].risk_factors())
    levels = np.array([[transformed_level(s, f) for f in facs] for s in snaps])
    return ScenarioSet(as_of, tuple(days[1:]), facs, np.diff(levels, axis=0))
