"""Scenario artefact detector (owner decision after M8, ADR-028).

Historical simulation keeps every scenario: nothing is filtered. This module only *flags*
scenario days on which the EUR AAA government curve probably moved because of fitting or
sample effects rather than the market.

Signal: the gap g_t = AAA spot rate - all-ratings spot rate (ECB published SR series, in bp)
at each configured pillar. With daily changes Δg_t and their standard deviation sigma over the
scenario window, a scenario day t is flagged when, at some pillar,

    |Δg_t| > k sigma                                       (k = artefact_sigma_threshold), and
    -sign(Δg_t) (Δg_{t+1} + ... + Δg_{t+n}) >= f |Δg_t|  (n = artefact_reversal_days,
                                                          f = artefact_reversal_fraction)

i.e. a large move of the gap that mostly reverses within n business days. A day whose
reversal window extends past the valuation date is reported as *pending*, never as clean.
The AAA and all-ratings curves normally move together (daily 5Y changes correlate at
0.94, 2024-26), so a large, short-lived gap move points to the AAA fit rather than the market.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import pandas as pd

from minibook.config.settings import VarSettings

BP_PER_PERCENT = 100.0


@dataclass(frozen=True)
class ScenarioFlag:
    """One flagged (or pending) scenario day at one pillar."""

    scenario_date: date
    pillar: str
    gap_move_bp: float
    sigma_bp: float
    reversal_bp: float | None  # None while pending
    pending: bool

    @property
    def z(self) -> float:
        """Gap move in standard deviations."""
        return self.gap_move_bp / self.sigma_bp


def gap_series(rating_curves: pd.DataFrame, tenors: Sequence[str]) -> pd.DataFrame:
    """AAA minus all-ratings spot rate per pillar, in bp (index: observation date)."""
    return pd.DataFrame(
        {
            t: (rating_curves[f"AAA:{t}"] - rating_curves[f"ALL:{t}"]) * BP_PER_PERCENT
            for t in tenors
        }
    ).dropna()


def detect(
    gaps: pd.DataFrame, scenario_dates: Sequence[date], cfg: VarSettings
) -> list[ScenarioFlag]:
    """Flag scenario days with a > k sigma gap move that mostly reverses (module docstring).

    ``gaps`` must not extend beyond the valuation date (the caller passes as-of data).
    """
    if gaps.empty or not scenario_dates:
        return []
    start = int(gaps.index.searchsorted(pd.Timestamp(scenario_dates[0])))
    chunk = gaps.iloc[max(start - 1, 0) :]  # include the day before the first scenario
    moves = chunk.diff().iloc[1:]
    sigma = moves.std()
    wanted = {pd.Timestamp(d) for d in scenario_dates}
    n, f, k = (
        cfg.artefact_reversal_days,
        cfg.artefact_reversal_fraction,
        cfg.artefact_sigma_threshold,
    )
    flags: list[ScenarioFlag] = []
    for i, ts in enumerate(moves.index):
        if ts not in wanted:
            continue
        for pillar in moves.columns:
            dg, sd = float(moves.iloc[i][pillar]), float(sigma[pillar])
            if not (sd > 0 and abs(dg) > k * sd):
                continue
            later = moves[pillar].iloc[i + 1 : i + 1 + n]
            if len(later) < n:
                flags.append(ScenarioFlag(ts.date(), pillar, dg, sd, None, True))
                continue
            back = -math.copysign(1.0, dg) * float(later.sum())
            if back >= f * abs(dg):
                flags.append(ScenarioFlag(ts.date(), pillar, dg, sd, float(later.sum()), False))
    return flags


def flagged_dates(flags: Sequence[ScenarioFlag]) -> list[date]:
    """Distinct scenario days with a confirmed (not pending) flag, sorted."""
    return sorted({fl.scenario_date for fl in flags if not fl.pending})
