"""Scenario artefact detector (ADR-028) on SYNTHETIC gap series, and VaR with flags."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from minibook.config.settings import Settings
from minibook.risk.scenario_check import detect, flagged_dates, gap_series
from minibook.risk.var import es_from_pnl, summarize, var_from_pnl, with_flags

DAYS = pd.bdate_range("2026-01-05", periods=60)


def _gaps(moves: dict[int, float], seed: int = 3) -> pd.DataFrame:
    """SYNTHETIC gap (bp): small noise (sd 0.5 bp) plus given jumps at day indices."""
    dg = np.random.default_rng(seed).normal(scale=0.5, size=len(DAYS))
    for i, m in moves.items():
        dg[i] += m
    return pd.DataFrame({"SR_5Y": dg.cumsum()}, index=DAYS)


def _scen(start: int = 1) -> list[date]:
    return [d.date() for d in DAYS[start:]]


def test_spike_that_reverses_is_flagged(settings: Settings) -> None:
    flags = detect(_gaps({30: -10.0, 31: 6.0, 32: 4.0}), _scen(), settings.var)
    assert [(f.scenario_date, f.pillar, f.pending) for f in flags] == [
        (DAYS[30].date(), "SR_5Y", False)
    ]
    f = flags[0]
    assert f.z < -settings.var.artefact_sigma_threshold
    assert f.reversal_bp is not None and f.reversal_bp > 0.5 * abs(f.gap_move_bp)
    assert flagged_dates(flags) == [DAYS[30].date()]


def test_lasting_move_or_small_move_is_not_flagged(settings: Settings) -> None:
    assert detect(_gaps({30: -10.0}), _scen(), settings.var) == []  # no reversal
    assert detect(_gaps({30: -1.0, 31: 1.0}), _scen(), settings.var) == []  # < 5 sigma


def test_move_near_the_end_is_pending_not_clean(settings: Settings) -> None:
    flags = detect(_gaps({59: -10.0}), _scen(), settings.var)
    assert len(flags) == 1 and flags[0].pending and flags[0].reversal_bp is None
    assert flagged_dates(flags) == []  # pending never changes the with/without figures


def test_only_scenario_days_are_checked(settings: Settings) -> None:
    gaps = _gaps({30: -10.0, 31: 10.0})
    assert detect(gaps, _scen(40), settings.var) == []
    assert detect(gaps.iloc[:0], _scen(), settings.var) == []
    assert detect(gaps, [], settings.var) == []


def test_gap_series_in_bp() -> None:
    # SYNTHETIC rates in percent, as published by the ECB.
    rc = pd.DataFrame({"AAA:SR_5Y": [2.0, 2.1], "ALL:SR_5Y": [2.5, 2.5]}, index=DAYS[:2])
    assert gap_series(rc, ["SR_5Y"])["SR_5Y"].tolist() == pytest.approx([-50.0, -40.0])


def test_with_flags_keeps_the_scenario_and_reports_both(settings: Settings) -> None:
    # SYNTHETIC P&L: 500 scenarios, one extreme loss on the flagged day.
    idx = pd.Index([d.date() for d in pd.bdate_range("2025-01-01", periods=500)])
    pnl = np.random.default_rng(1).normal(scale=1000.0, size=500)
    pnl[100] = -50_000.0
    frame = pd.DataFrame({"A": pnl}, index=idx.rename("scenario_date"))
    res = summarize(frame, settings.var, date(2026, 11, 11))
    gaps = pd.DataFrame(
        {"SR_5Y": np.r_[np.zeros(100), -10.0, 0.0, np.zeros(398)].cumsum()},
        index=pd.DatetimeIndex(idx),
    )
    gaps.iloc[101:, 0] = 0.0  # full reversal on the next day
    gaps.iloc[:, 0] += np.random.default_rng(2).normal(scale=0.1, size=500)
    flags = detect(gaps, list(idx), settings.var)
    assert flagged_dates(flags) == [idx[100]]
    out = with_flags(res, flags, settings.var)
    assert out.var == res.var and out.es == res.es  # never altered (owner decision 21)
    kept = np.delete(pnl, 100)
    assert out.var_ex_flagged == var_from_pnl(kept, settings.var.var_confidence)
    assert out.es_ex_flagged == es_from_pnl(kept, settings.var.es_confidence)
    assert out.es_ex_flagged < res.es
    empty = with_flags(res, [], settings.var)
    assert empty.flags == () and empty.var_ex_flagged is None
