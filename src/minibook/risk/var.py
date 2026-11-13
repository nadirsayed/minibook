"""Historical-simulation VaR and ES by full revaluation (brief, M6).

For each scenario i, the book is revalued at the shocked market with the valuation date held
at D:

    P&L_i = Σ_instruments [PV(apply(mkt_D, shock_i)) - PV(mkt_D)]

With the P&Ls sorted ascending, P_(1) <= ... <= P_(N):

    VaR_99  = -P_(k),                       k = ceil(0.01 N)      (5th worst for N = 500)
    ES_97.5 = -(1/m) Σ_{j<=m} P_(j),        m = ceil(0.025 N)     (worst 13 for N = 500)

The same definitions are applied to each instrument alone (standalone VaR/ES). Diversification
benefit = Σ standalone VaR - total VaR. It is reported as it is and may be negative: VaR is
not subadditive.

Bonus: delta-gamma VaR uses the Greeks of D and the P&L-explain formula with Δt = 0 on each
scenario's moves, so the comparison with full revaluation shows the non-linearity that the
Greeks miss.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from minibook.config.settings import RiskSettings, VarSettings
from minibook.instruments.base import Instrument
from minibook.market.snapshot import MarketSnapshot
from minibook.pnl.explain import explain_components, market_moves
from minibook.risk.greeks import book_greeks, with_todays_fixings
from minibook.risk.scenarios import ScenarioSet

ROUND_DIGITS = 9  # (1 - 0.99) * 500 = 5.000000000000004 in floating point: round first


def tail_count(confidence: float, n: int) -> int:
    """ceil((1 - confidence) N), robust to floating-point noise; at least 1."""
    return max(1, math.ceil(round((1.0 - confidence) * n, ROUND_DIGITS)))


def var_from_pnl(pnl: np.ndarray, confidence: float) -> float:
    """VaR = -(k-th worst P&L), k = ceil((1 - confidence) N)."""
    p = np.sort(np.asarray(pnl, dtype=float))
    return float(-p[tail_count(confidence, p.size) - 1])


def es_from_pnl(pnl: np.ndarray, confidence: float) -> float:
    """ES = -mean of the worst m P&Ls, m = ceil((1 - confidence) N)."""
    p = np.sort(np.asarray(pnl, dtype=float))
    return float(-p[: tail_count(confidence, p.size)].mean())


def bootstrap_ci(
    pnl: np.ndarray, cfg: VarSettings
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Seeded nonparametric bootstrap intervals for VaR and ES.

    Resample the N scenario P&Ls with replacement B times (``cfg.bootstrap_resamples``,
    generator seeded with ``cfg.bootstrap_seed``), recompute VaR and ES on each resample, and
    return the two-sided ``cfg.bootstrap_ci`` percentile intervals ((VaR lo, hi), (ES lo, hi)).

    VaR99 is one order statistic (the 5th worst of 500), while ES97.5 averages 13, so the
    VaR interval is typically wider relative to its level. The i.i.d. bootstrap of an
    extreme quantile is crude (bootstrap VaRs can only take sample values), so the intervals
    indicate sampling noise; they are not exact coverage statements.
    """
    p = np.asarray(pnl, dtype=float)
    rng = np.random.default_rng(cfg.bootstrap_seed)
    draws = np.sort(p[rng.integers(0, p.size, size=(cfg.bootstrap_resamples, p.size))], axis=1)
    k = tail_count(cfg.var_confidence, p.size)
    m = tail_count(cfg.es_confidence, p.size)
    var_b = -draws[:, k - 1]
    es_b = -draws[:, :m].mean(axis=1)
    lo, hi = 50 * (1 - cfg.bootstrap_ci), 50 * (1 + cfg.bootstrap_ci)
    return (
        (float(np.percentile(var_b, lo)), float(np.percentile(var_b, hi))),
        (float(np.percentile(es_b, lo)), float(np.percentile(es_b, hi))),
    )


def scenario_pnl(
    insts: Sequence[Instrument], base: MarketSnapshot, scen: ScenarioSet
) -> pd.DataFrame:
    """Full-revaluation P&L matrix: index = scenario date, columns = instrument ids (EUR)."""
    base = with_todays_fixings(insts, base)
    pv0 = np.array([i.pv(base) for i in insts])
    rows = np.empty((len(scen), len(insts)))
    for k in range(len(scen)):
        shocked = base.apply(scen.as_mapping(k))
        rows[k] = [i.pv(shocked) for i in insts]
    return pd.DataFrame(
        rows - pv0, index=pd.Index(scen.dates, name="scenario_date"), columns=[i.id for i in insts]
    )


def delta_gamma_pnl(
    insts: Sequence[Instrument], base: MarketSnapshot, scen: ScenarioSet, risk: RiskSettings
) -> pd.Series:
    """Total P&L per scenario from the Greeks of D (explain formula, Δt = 0)."""
    base = with_todays_fixings(insts, base)
    greeks = book_greeks(insts, base, risk)
    out = []
    for k in range(len(scen)):
        moves = market_moves(base, base.apply(scen.as_mapping(k)))
        out.append(float(explain_components(greeks, moves)["value"].sum()))
    return pd.Series(out, index=pd.Index(scen.dates, name="scenario_date"), name="delta_gamma")


@dataclass(frozen=True)
class VarResult:
    """VaR/ES of the book and of each instrument (EUR, positive = loss)."""

    as_of: date
    n_scenarios: int
    var_confidence: float
    es_confidence: float
    var: float
    es: float
    standalone: pd.DataFrame  # index instrument_id, columns var, es
    diversification_var: float
    worst: pd.DataFrame  # n_worst scenarios: total and per-instrument P&L, by date
    pnl: pd.DataFrame  # full matrix: scenario date x instrument
    var_ci: tuple[float, float] | None = None
    es_ci: tuple[float, float] | None = None
    ci_level: float | None = None
    delta_gamma_var: float | None = None
    delta_gamma_es: float | None = None


def summarize(pnl: pd.DataFrame, cfg: VarSettings, as_of: date) -> VarResult:
    """VaR/ES, standalone figures, diversification and worst scenarios from a P&L matrix."""
    total = pnl.sum(axis=1).to_numpy()
    standalone = pd.DataFrame(
        {
            "var": [var_from_pnl(pnl[c].to_numpy(), cfg.var_confidence) for c in pnl.columns],
            "es": [es_from_pnl(pnl[c].to_numpy(), cfg.es_confidence) for c in pnl.columns],
        },
        index=pd.Index(pnl.columns, name="instrument_id"),
    )
    var = var_from_pnl(total, cfg.var_confidence)
    order = np.argsort(total, kind="stable")[: cfg.n_worst]
    worst = pnl.iloc[order].assign(total=total[order])
    var_ci, es_ci = bootstrap_ci(total, cfg)
    return VarResult(
        as_of=as_of,
        n_scenarios=len(pnl),
        var_confidence=cfg.var_confidence,
        es_confidence=cfg.es_confidence,
        var=var,
        es=es_from_pnl(total, cfg.es_confidence),
        standalone=standalone,
        diversification_var=float(standalone["var"].sum()) - var,
        worst=worst,
        pnl=pnl,
        var_ci=var_ci,
        es_ci=es_ci,
        ci_level=cfg.bootstrap_ci,
    )


def historical_var(
    insts: Sequence[Instrument],
    base: MarketSnapshot,
    scen: ScenarioSet,
    cfg: VarSettings,
    risk: RiskSettings | None = None,
) -> VarResult:
    """Full-revaluation VaR/ES (and delta-gamma VaR/ES if ``risk`` is given)."""
    if len(scen) != cfg.n_scenarios:
        raise ValueError(f"expected {cfg.n_scenarios} scenarios, got {len(scen)}")
    if scen.as_of != base.as_of:
        raise ValueError(f"scenarios end {scen.as_of}, base snapshot is {base.as_of}")
    result = summarize(scenario_pnl(insts, base, scen), cfg, base.as_of)
    if risk is None:
        return result
    dg = delta_gamma_pnl(insts, base, scen, risk).to_numpy()
    return dataclasses.replace(
        result,
        delta_gamma_var=var_from_pnl(dg, cfg.var_confidence),
        delta_gamma_es=es_from_pnl(dg, cfg.es_confidence),
    )
