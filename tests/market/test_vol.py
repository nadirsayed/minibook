from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from minibook.market.vol import ewma_vol


def closes(returns: list[float]) -> pd.Series:
    """SYNTHETIC price path from log returns."""
    return pd.Series(100.0 * np.exp(np.concatenate([[0.0], np.cumsum(returns)])))


def test_constant_magnitude_returns() -> None:
    # |r| = 1% every day => variance stays 1e-4 => vol = 0.01 * sqrt(252).
    r = [0.01, -0.01] * 50
    assert ewma_vol(closes(r), 0.94, 20, 252) == pytest.approx(0.01 * np.sqrt(252))


def test_recursion_weights() -> None:
    # Seed variance 0 (zero returns), then one shock r: var = (1 - lam) * r^2.
    r = [0.0] * 10 + [0.02]
    vol = ewma_vol(closes(r), 0.94, 10, 252)
    assert vol == pytest.approx(np.sqrt(252 * 0.06 * 0.02**2))


def test_only_past_data_matters() -> None:
    base = list(np.random.default_rng(1).normal(0, 0.01, 80))
    s = closes(base)
    assert ewma_vol(s.iloc[:70], 0.94, 60, 252) == ewma_vol(closes(base[:69]), 0.94, 60, 252)


@pytest.mark.parametrize(
    ("series", "lam", "msg"),
    [
        (closes([0.01] * 5), 0.94, "at least"),
        (closes([0.01] * 30), 1.0, "lambda"),
        (pd.Series([100.0, -1.0, 101.0]), 0.94, "positive"),
    ],
)
def test_invalid_inputs(series: pd.Series, lam: float, msg: str) -> None:
    with pytest.raises(ValueError, match=msg):
        ewma_vol(series, lam, 20, 252)


def test_vol_series_equals_per_date_recursion() -> None:
    """The one-pass series is causal: element k equals ewma_vol on closes[: k + 1]."""
    from minibook.market.vol import ewma_vol_series  # noqa: PLC0415

    prices = closes(list(np.random.default_rng(3).normal(0, 0.01, 120))).to_numpy()  # SYNTHETIC
    series = ewma_vol_series(prices, 0.94, 60, 252)
    assert np.all(np.isnan(series[:61]))
    for k in range(61, prices.size):
        assert series[k] == ewma_vol(pd.Series(prices[: k + 1]), 0.94, 60, 252)
    assert np.all(np.isnan(ewma_vol_series(prices[:30], 0.94, 60, 252)))
    with pytest.raises(ValueError, match="lambda"):
        ewma_vol_series(prices, 1.5, 60, 252)
    with pytest.raises(ValueError, match="positive"):
        ewma_vol_series(np.array([1.0, -1.0, 2.0]), 0.94, 1, 252)
