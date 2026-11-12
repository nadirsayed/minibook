from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from scipy.stats import binom, chi2

from minibook.config.settings import Settings
from minibook.risk.backtest import backtest, kupiec_pof, traffic_light


def obs(n: int, hits: list[int]) -> pd.DataFrame:
    """SYNTHETIC: VaR 100 every day, P&L -150 on the hit indices, +10 otherwise."""
    pnl = np.full(n, 10.0)
    pnl[hits] = -150.0
    dates = [date(2026, 1, 1) + timedelta(days=k) for k in range(n)]
    return pd.DataFrame({"date": dates, "var_prev": 100.0, "pnl": pnl})


@pytest.mark.parametrize(("n", "x"), [(250, 0), (250, 2), (250, 5), (250, 12), (40, 1)])
def test_kupiec_matches_binomial_likelihood_ratio(n: int, x: int) -> None:
    """Independent formulation: 2 [log L(x/n) - log L(p)] with scipy's binomial pmf."""
    lr, pval = kupiec_pof(n, x, 0.01)
    ref = (
        2.0 * (binom.logpmf(x, n, x / n) - binom.logpmf(x, n, 0.01))
        if x
        else -2.0 * n * np.log(0.99)
    )
    assert lr == pytest.approx(ref, rel=1e-12, abs=1e-12)
    assert pval == pytest.approx(chi2.sf(ref, 1))


def test_traffic_light_zones(settings: Settings) -> None:
    cfg = settings.backtest
    assert [traffic_light(x, cfg) for x in (0, 4, 5, 9, 10, 15)] == [
        "green",
        "green",
        "yellow",
        "yellow",
        "red",
        "red",
    ]


def test_small_sample_never_shows_a_zone(settings: Settings) -> None:
    res = backtest(obs(40, []), 0.99, settings.backtest)
    assert res.zone is None and res.kupiec_reject is None
    assert res.status == "insufficient observations (N = 40)"
    assert res.n == 40 and res.exceptions == 0 and res.expected == pytest.approx(0.4)
    empty = backtest(obs(0, []), 0.99, settings.backtest)
    assert empty.status == "insufficient observations (N = 0)" and empty.zone is None


def test_full_sample_zone_uses_last_250(settings: Settings) -> None:
    # 6 exceptions, but only 3 of them in the last 250 of 300 observations -> green.
    res = backtest(obs(300, [0, 10, 20, 100, 200, 299]), 0.99, settings.backtest)
    assert res.exceptions == 6 and res.zone == "green"
    assert res.exception_dates[0] == date(2026, 1, 1)
    assert "green zone (3 exceptions in the last 250 days)" in res.status
    red = backtest(obs(250, list(range(0, 250, 25))), 0.99, settings.backtest)
    assert red.zone == "red" and red.kupiec_reject is True
