"""Daily P&L explain, t-1 -> t, per instrument (brief, M5).

Actual P&L
----------
    Actual_i = PV_i(t; mkt_t) - PV_i(t-1; mkt_{t-1}) + cashflows_i in (t-1, t]

Explained P&L (Greeks of t-1, market moves t-1 -> t)
-----------------------------------------------------
With u = ΔS/S for spots and EUR/ccy FX rates, Δσ in decimal, Δr in bp at each key pillar
(zero rates read on the same time-to-maturity grid) and Δt in calendar days:

    Explained_i = Σ_u [ D_1% (u/0.01) + ½ G_1% (u/0.01)² ]          equity and FX
                + Σ_u Vega_1pt (Δσ/0.01)
                + Theta_1d Δt
                + Σ_k KR_DV01_k Δr_k                               EUR, USD, JPY

    Unexplained_i = Actual_i - Explained_i

Unexplained is additive across instruments only. The factor-level attribution (the
components table) splits the *explained* part. Dividend yields are model assumptions held
constant (no term). The parallel DV01 is not used, since the key rates already span it.

A day is flagged when |Unexplained| > max(rel * |Actual|, abs) (``settings.pnl``).

Breach diagnostics (not part of Explained)
------------------------------------------
``omitted_2nd_order`` is the vanna + volga estimate for options (zero otherwise): the
spot-vol cross term and vol convexity that the brief's explain leaves out. With the EWMA vol
proxy they dominate the unexplained P&L on big-move days (methodology §4).
``residual_after_2nd`` = Unexplained - omitted_2nd_order. Each flagged row gets a ``note``
in plain words, built from these numbers and the largest revaluation step.

Revaluation step attribution (bonus)
------------------------------------
Full revaluation, moving one block of inputs at a time, in a fixed order: time (with the
cashflows of the window), rates, FX, equity spots, vols, then "other" (fixings, assumptions).
The steps add up exactly to Actual. They depend on the order and are a diagnostic for breaches.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

from minibook.config.settings import PnlSettings, RiskSettings
from minibook.dates.tenor import Tenor
from minibook.instruments.base import Instrument, Measure
from minibook.market.snapshot import MarketSnapshot
from minibook.risk.greeks import book_greeks, with_todays_fixings

PCT = 0.01
VOL_POINT = 0.01
BP = 1e-4


class Component(StrEnum):
    """Explained-P&L components."""

    THETA = "theta"
    EQ_DELTA = "eq_delta"
    EQ_GAMMA = "eq_gamma"
    VEGA = "vega"
    FX_DELTA = "fx_delta"
    FX_GAMMA = "fx_gamma"
    RATES = "rates"


class Step(StrEnum):
    """Revaluation step attribution, in application order."""

    TIME = "time"
    RATES = "rates"
    FX = "fx"
    EQUITY = "equity"
    VOL = "vol"
    OTHER = "other"


@dataclass(frozen=True)
class MarketMoves:
    """Factor moves from t-1 to t, keyed by risk-factor id as used in the Greeks table."""

    dt_days: int
    returns: dict[str, float]  # "EQ:SX5E", "FX:USD" -> u = ΔS/S
    vol_changes: dict[str, float]  # "VOL:SX5E" -> Δσ (decimal)
    rate_changes_bp: dict[str, float]  # "KR:EUR:5Y" -> Δr (bp)


def market_moves(prev: MarketSnapshot, curr: MarketSnapshot) -> MarketMoves:
    """Return the move of every factor between two snapshots (zeros at key-pillar times)."""
    dt = (curr.as_of - prev.as_of).days
    if dt < 0:
        raise ValueError(f"t ({curr.as_of}) must not be before t-1 ({prev.as_of})")
    returns = {f"EQ:{u}": curr.spots[u] / prev.spots[u] - 1.0 for u in prev.spots}
    returns |= {f"FX:{c}": curr.fx[c] / prev.fx[c] - 1.0 for c in prev.fx}
    vols = {f"VOL:{u}": curr.vols[u] - prev.vols[u] for u in prev.vols}
    rates = {}
    for ccy in prev.curves:
        for k in prev.key_pillars:
            t = Tenor.parse(k).years
            dz = float(curr.curve(ccy).zero(t)) - float(prev.curve(ccy).zero(t))
            rates[f"KR:{ccy}:{k}"] = dz / BP
    return MarketMoves(dt, returns, vols, rates)


def explain_components(greeks_prev: pd.DataFrame, moves: MarketMoves) -> pd.DataFrame:
    """Explained P&L by instrument, component and risk factor (long table, EUR)."""
    rows: list[tuple[str, Component, str, float]] = []
    for inst_id, m, factor, value in zip(
        greeks_prev["instrument_id"].astype(str).tolist(),
        greeks_prev["measure"].astype(str).tolist(),
        greeks_prev["risk_factor"].astype(str).tolist(),
        greeks_prev["value"].astype(float).tolist(),
        strict=True,
    ):
        measure = Measure(m)
        kind = factor.split(":", 1)[0]
        if measure is Measure.THETA_1D:
            rows.append((inst_id, Component.THETA, factor, value * moves.dt_days))
        elif measure in (Measure.DELTA_1PCT, Measure.GAMMA_1PCT):
            x = moves.returns[factor] / PCT
            is_delta = measure is Measure.DELTA_1PCT
            comp = {
                ("EQ", True): Component.EQ_DELTA,
                ("EQ", False): Component.EQ_GAMMA,
                ("FX", True): Component.FX_DELTA,
                ("FX", False): Component.FX_GAMMA,
            }[(kind, is_delta)]
            rows.append((inst_id, comp, factor, value * x if is_delta else 0.5 * value * x * x))
        elif measure is Measure.VEGA_1PT:
            rows.append(
                (
                    inst_id,
                    Component.VEGA,
                    factor,
                    value * moves.vol_changes[factor] / VOL_POINT,
                )
            )
        elif measure is Measure.KR_DV01:
            rows.append((inst_id, Component.RATES, factor, value * moves.rate_changes_bp[factor]))
        # DV01 (parallel, spanned by key rates) and DIV_10BP (q held constant): no term.
    return pd.DataFrame(
        [(i, c.value, f, v) for i, c, f, v in rows],
        columns=["instrument_id", "component", "risk_factor", "value"],
    )


def _pv_plus_cash(
    insts: Sequence[Instrument], market: MarketSnapshot, cash: dict[str, float]
) -> dict[str, float]:
    return {i.id: i.pv(market) + cash[i.id] for i in insts}


def step_attribution(
    insts: Sequence[Instrument], prev: MarketSnapshot, curr: MarketSnapshot, cash: dict[str, float]
) -> pd.DataFrame:
    """Full-revaluation steps (module docstring). Rows: instrument_id, step, value."""
    s0 = with_todays_fixings(insts, prev)
    s1 = dataclasses.replace(s0, as_of=curr.as_of)
    s2 = dataclasses.replace(s1, curves=curr.curves)
    s3 = dataclasses.replace(s2, fx=curr.fx)
    s4 = dataclasses.replace(s3, spots=curr.spots)
    s5 = dataclasses.replace(s4, vols=curr.vols)
    stages: list[tuple[Step, MarketSnapshot]] = [
        (Step.TIME, s1),
        (Step.RATES, s2),
        (Step.FX, s3),
        (Step.EQUITY, s4),
        (Step.VOL, s5),
        (Step.OTHER, curr),
    ]
    previous = _pv_plus_cash(insts, s0, {i.id: 0.0 for i in insts})
    rows: list[tuple[str, str, float]] = []
    for step, market in stages:
        current = _pv_plus_cash(insts, market, cash)
        rows += [(i.id, step.value, current[i.id] - previous[i.id]) for i in insts]
        previous = current
    return pd.DataFrame(rows, columns=["instrument_id", "step", "value"])


@runtime_checkable
class HasOmittedTerms(Protocol):
    """Instruments that can estimate the second-order terms omitted by the explain."""

    def omitted_second_order(self, prev: MarketSnapshot, curr: MarketSnapshot) -> float:
        """Vanna + volga estimate from t-1 Greeks (EUR)."""
        ...


def _breach_note(unexplained: float, omitted: float, steps: pd.DataFrame) -> str:
    """Plain-words explanation of a flagged instrument-day."""
    top = steps.reindex(steps["value"].abs().sort_values(ascending=False).index).iloc[0]
    parts = [f"unexplained {unexplained:+,.0f} EUR"]
    if omitted != 0.0:
        share = omitted / unexplained if unexplained else float("nan")
        parts.append(
            f"omitted vanna+volga (spot x EWMA-vol cross term, vol convexity) {omitted:+,.0f} "
            f"EUR = {share:.0%} of it; remainder {unexplained - omitted:+,.0f} EUR"
        )
    parts.append(f"largest revaluation step: {top['step']} {float(top['value']):+,.0f} EUR")
    return "; ".join(parts)


@dataclass(frozen=True)
class PnlExplain:
    """Result of one day's explain."""

    per_instrument: pd.DataFrame
    components: pd.DataFrame
    steps: pd.DataFrame
    moves: MarketMoves

    @property
    def book(self) -> dict[str, float]:
        """Book totals: actual, explained, unexplained (EUR)."""
        cols = ("actual", "explained", "unexplained")
        return {k: float(self.per_instrument[k].sum()) for k in cols}


def explain(
    insts: Sequence[Instrument],
    prev: MarketSnapshot,
    curr: MarketSnapshot,
    risk: RiskSettings,
    pnl: PnlSettings,
    greeks_prev: pd.DataFrame | None = None,
) -> PnlExplain:
    """Explain the P&L of ``insts`` from ``prev`` (t-1) to ``curr`` (t).

    ``prev`` and ``curr`` must carry the fixings known on their dates. Fixings due on t-1 are
    set on ``prev`` (curve proxy) before computing PV and Greeks, as the daily run does.
    """
    prev = with_todays_fixings(insts, prev)
    if greeks_prev is None:
        greeks_prev = book_greeks(insts, prev, risk)
    moves = market_moves(prev, curr)
    comps = explain_components(greeks_prev, moves)
    cash = {
        i.id: sum(cf.amount_eur for cf in i.cashflows(prev.as_of, curr.as_of, curr)) for i in insts
    }
    explained = comps.groupby("instrument_id")["value"].sum()
    steps = step_attribution(insts, prev, curr, cash)
    rows = []
    for i in insts:
        pv0, pv1 = i.pv(prev), i.pv(curr)
        actual = pv1 - pv0 + cash[i.id]
        expl = float(explained.get(i.id, 0.0))
        unexplained = actual - expl
        threshold = max(
            pnl.unexplained_rel_threshold * abs(actual), pnl.unexplained_abs_threshold_eur
        )
        omitted = i.omitted_second_order(prev, curr) if isinstance(i, HasOmittedTerms) else 0.0
        flagged = bool(abs(unexplained) > threshold)
        note = (
            _breach_note(unexplained, omitted, steps[steps.instrument_id == i.id])
            if flagged
            else ""
        )
        rows.append(
            (
                i.id,
                pv0,
                pv1,
                cash[i.id],
                actual,
                expl,
                unexplained,
                threshold,
                flagged,
                omitted,
                unexplained - omitted,
                note,
            )
        )
    per = pd.DataFrame(
        rows,
        columns=[
            "instrument_id",
            "pv_prev",
            "pv_curr",
            "cashflows",
            "actual",
            "explained",
            "unexplained",
            "threshold",
            "flagged",
            "omitted_2nd_order",
            "residual_after_2nd",
            "note",
        ],
    )
    if not np.allclose(
        steps.groupby("instrument_id")["value"].sum().reindex(per.instrument_id),
        per["actual"],
        rtol=0.0,
        atol=1e-6,
    ):
        raise RuntimeError("step attribution does not add up to actual P&L")
    return PnlExplain(per, comps, steps, moves)
