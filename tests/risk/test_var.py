"""VaR/ES definitions, Gaussian check, scenarios, full revaluation vs delta-gamma."""

from __future__ import annotations

import dataclasses
import math
from datetime import date

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st
from scipy.stats import norm

from minibook.config.settings import Settings, VarSettings
from minibook.dates.calendars import TARGET
from minibook.instruments.bsm import OptionType
from minibook.instruments.equity_option import EquityOption
from minibook.market.snapshot import EquitySpot, FxSpot, MarketSnapshot, Vol, ZeroRate
from minibook.risk.scenarios import historical_scenarios, scenario_dates
from minibook.risk.var import (
    es_from_pnl,
    historical_var,
    summarize,
    tail_count,
    var_from_pnl,
)
from tests.risk.test_greeks import flat_snapshot

D = date(2026, 11, 11)


def test_tail_count_is_robust_to_floating_point() -> None:
    assert math.ceil((1 - 0.99) * 500) == 6  # the naive formula is off by one
    assert tail_count(0.99, 500) == 5  # brief: 5th worst for N = 500
    assert tail_count(0.975, 500) == 13  # ceil(12.5)
    assert tail_count(0.99, 50) == 1


def test_definitions_on_known_ranks() -> None:
    pnl = np.random.default_rng(0).permutation(np.arange(500.0) - 250.0)  # SYNTHETIC
    assert var_from_pnl(pnl, 0.99) == 246.0  # 5th worst of -250..249 is -246
    assert es_from_pnl(pnl, 0.975) == pytest.approx(-np.mean(np.arange(-250.0, -237.0)))


def test_gaussian_pnl() -> None:
    """SYNTHETIC N(0, sigma) P&L. Closed forms: VaR99 = sigma z_0.99 = 2.3263 sigma;
    ES97.5 = sigma phi(z_0.975) / 0.025 = 2.3378 sigma (reference values from scipy.stats)."""
    sigma = 10_000.0
    pnl = np.random.default_rng(42).normal(0.0, sigma, 2_000_000)
    z99 = norm.ppf(0.99)
    es975 = norm.pdf(norm.ppf(0.975)) / 0.025
    assert z99 == pytest.approx(2.3263, abs=1e-4) and es975 == pytest.approx(2.3378, abs=1e-4)
    # Sampling error of the 1% quantile with 2e6 draws is ~0.1%; tolerance 0.5%.
    assert var_from_pnl(pnl, 0.99) == pytest.approx(z99 * sigma, rel=5e-3)
    assert es_from_pnl(pnl, 0.975) == pytest.approx(es975 * sigma, rel=5e-3)


@given(
    st.lists(st.floats(-1e6, 1e6), min_size=40, max_size=600), st.sampled_from([0.95, 0.975, 0.99])
)
def test_es_at_least_var_at_same_confidence(values: list[float], conf: float) -> None:
    pnl = np.array(values)
    assert es_from_pnl(pnl, conf) >= var_from_pnl(pnl, conf) - 1e-9


def test_diversification_can_be_negative() -> None:
    """SYNTHETIC classic non-subadditivity: two positions each losing 100 in 4 of 500
    scenarios (0.8% < 1%), never together. Standalone VaR99 = 0, combined VaR99 = 100."""
    a, b = np.zeros(500), np.zeros(500)
    a[:4], b[4:8] = -100.0, -100.0
    pnl = pd.DataFrame({"A": a, "B": b}, index=pd.RangeIndex(500, name="scenario_date"))
    res = summarize(
        pnl,
        VarSettings(
            n_scenarios=500,
            var_confidence=0.99,
            es_confidence=0.975,
            n_worst=5,
            bootstrap_resamples=200,
            bootstrap_seed=1,
            bootstrap_ci=0.9,
        ),
        D,
    )
    assert list(res.standalone["var"]) == [0.0, 0.0]
    assert res.var == 100.0 and res.diversification_var == -100.0
    assert list(res.worst["total"]) == [-100.0] * 5


def history(levels: dict[date, float]) -> dict[date, MarketSnapshot]:
    """SYNTHETIC snapshots whose EUR 5Y zero, EUR/USD, SX5E and SX5E vol follow ``levels``."""
    base = flat_snapshot()
    out = {}
    for d, x in levels.items():
        snap = dataclasses.replace(base, as_of=d).apply(
            {
                ZeroRate("EUR", "5Y"): 1e-4 * x,
                FxSpot("USD"): 0.001 * x,
                EquitySpot("SX5E"): 0.002 * x,
                Vol("SX5E"): 0.0005 * x,
            }
        )
        out[d] = snap
    return out


def test_scenarios_shock_types_and_no_look_ahead() -> None:
    days = scenario_dates(D, 20)
    assert len(days) == 21 and days[-1] == D and all(TARGET.is_business_day(d) for d in days)
    path = np.random.default_rng(1).normal(size=len(days)).cumsum()
    snaps = history(dict(zip(days, path, strict=True)))
    asked: list[date] = []

    def snapshot_for(d: date) -> MarketSnapshot:
        asked.append(d)
        return snaps[d]

    sc = historical_scenarios(snapshot_for, D, 20)
    assert max(asked) == D and sc.dates == tuple(days[1:])
    j = {f.id: k for k, f in enumerate(sc.factors)}
    dx = np.diff(path)
    np.testing.assert_allclose(sc.shocks[:, j["ZR:EUR:5Y"]], 1e-4 * dx, atol=1e-15)  # abs
    np.testing.assert_allclose(sc.shocks[:, j["FX:USD"]], 0.001 * dx, atol=1e-12)  # log
    np.testing.assert_allclose(sc.shocks[:, j["EQ:SX5E"]], 0.002 * dx, atol=1e-12)  # log
    np.testing.assert_allclose(sc.shocks[:, j["VOL:SX5E"]], 0.0005 * dx, atol=1e-15)  # abs
    assert np.all(sc.shocks[:, j["ZR:EUR:3Y"]] == 0.0)
    with pytest.raises(ValueError, match="TARGET"):
        scenario_dates(date(2026, 11, 14), 20)


def test_full_revaluation_vs_delta_gamma(settings: Settings) -> None:
    days = scenario_dates(D, 500)
    path = np.random.default_rng(7).normal(scale=0.5, size=len(days)).cumsum()  # SYNTHETIC
    snaps = history(dict(zip(days, path, strict=True)))
    sc = historical_scenarios(lambda d: snaps[d], D, 500)
    opt = EquityOption("O", "SX5E", OptionType.CALL, 50, 10.0, 5000.0, date(2027, 2, 2))
    res = historical_var([opt], snaps[D], sc, settings.var, settings.risk)
    assert res.n_scenarios == 500 and res.var > 0 and res.es > 0
    # Small daily moves: delta-gamma VaR within 2% of full revaluation (third-order terms).
    assert res.delta_gamma_var == pytest.approx(res.var, rel=0.02)
    assert res.diversification_var == pytest.approx(0.0)  # single instrument
    with pytest.raises(ValueError, match="expected 500"):
        historical_var(
            [opt],
            snaps[D],
            dataclasses.replace(sc, dates=sc.dates[:10], shocks=sc.shocks[:10]),
            settings.var,
        )
    with pytest.raises(ValueError, match="base snapshot"):
        historical_var([opt], snaps[days[-2]], sc, settings.var)


def test_apply_pillar_shocks_equals_tents() -> None:
    from minibook.market.curves import tent  # noqa: PLC0415

    snap = flat_snapshot()
    shocks = {
        ZeroRate("EUR", lab): 1e-4 * (k + 1) for k, lab in enumerate(snap.curve("EUR").labels)
    }
    fast = snap.apply(shocks).curve("EUR")
    slow = snap.curve("EUR")
    for k in range(len(slow.times)):
        slow = slow.shifted(tent(slow.times, k, 1e-4 * (k + 1)))
    grid = np.linspace(0.0, 35.0, 701)
    np.testing.assert_allclose(fast.zero(grid), slow.zero(grid), atol=1e-15)


def test_bootstrap_intervals(settings: Settings) -> None:
    """SYNTHETIC N(0, 1) sample of 500: seeded intervals are deterministic, contain the point
    estimates, and VaR99 (one order statistic) is noisier than ES97.5 (mean of 13)."""
    from minibook.risk.var import bootstrap_ci  # noqa: PLC0415

    pnl = np.random.default_rng(11).normal(size=500)
    cfg = settings.var
    (v_lo, v_hi), (e_lo, e_hi) = bootstrap_ci(pnl, cfg)
    assert ((v_lo, v_hi), (e_lo, e_hi)) == bootstrap_ci(pnl, cfg)  # deterministic
    var, es = var_from_pnl(pnl, cfg.var_confidence), es_from_pnl(pnl, cfg.es_confidence)
    assert v_lo <= var <= v_hi and e_lo <= es <= e_hi
    assert (v_hi - v_lo) / var > (e_hi - e_lo) / es
    other = cfg.model_copy(update={"bootstrap_seed": cfg.bootstrap_seed + 1})
    assert bootstrap_ci(pnl, other) != bootstrap_ci(pnl, cfg)
