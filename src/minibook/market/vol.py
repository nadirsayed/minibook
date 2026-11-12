"""Realized-volatility proxy: EWMA (RiskMetrics) of daily log returns.

    r_t      = ln(S_t / S_{t-1})
    s2_0     = mean(r_1^2 .. r_W^2)                     (seed over the warm-up window W)
    s2_t     = lam * s2_{t-1} + (1 - lam) * r_t^2       (t > W)
    sigma_t  = sqrt(A * s2_t)                           (A = trading days per year)

This is the vol *proxy* used for all four indices while VSTOXX is unavailable (ADR-002). It is
a flat (strike- and expiry-independent) volatility and is labelled as a proxy everywhere.
Only closes dated on or before the valuation date may be passed in (no look-ahead).

Reference: J.P. Morgan/Reuters, "RiskMetrics - Technical Document", 4th ed. (1996), which sets
lambda = 0.94 for daily data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ewma_vol_series(
    prices: np.ndarray, lam: float, warmup: int, annualization: float
) -> np.ndarray:
    """Annualized EWMA vol at every close (NaN until ``warmup + 1`` returns exist).

    Element k equals ``ewma_vol(prices[: k + 1], ...)``: the recursion is causal, so a value
    depends only on closes up to its own date (no look-ahead). One pass instead of one
    recursion per date.
    """
    if not 0.0 < lam < 1.0:
        raise ValueError(f"lambda must be in (0, 1), got {lam}")
    p = np.asarray(prices, dtype=float)
    if np.any(~np.isfinite(p)) or np.any(p <= 0):
        raise ValueError("closes must be finite and positive")
    r = np.diff(np.log(p))
    out = np.full(p.size, np.nan)
    if r.size < warmup + 1:
        return out
    var = float(np.mean(r[:warmup] ** 2))
    for j in range(warmup, r.size):  # return j belongs to close j + 1
        var = lam * var + (1.0 - lam) * r[j] * r[j]
        out[j + 1] = np.sqrt(annualization * var)
    return out


def ewma_vol(closes: pd.Series, lam: float, warmup: int, annualization: float) -> float:
    """Annualized EWMA volatility at the last date of ``closes``.

    Parameters
    ----------
    closes
        Close prices sorted by date, without gaps filled (one row per trading day).
    lam
        Decay factor, 0 < lam < 1.
    warmup
        Number of returns W used to seed the variance. Needs at least W + 1 returns.
    annualization
        Trading days per year A.

    Raises
    ------
    ValueError
        If there are too few observations, or a non-positive price.
    """
    if not 0.0 < lam < 1.0:
        raise ValueError(f"lambda must be in (0, 1), got {lam}")
    prices = closes.to_numpy(dtype=float)
    if np.any(~np.isfinite(prices)) or np.any(prices <= 0):
        raise ValueError("closes must be finite and positive")
    returns = np.diff(np.log(prices))
    if returns.size < warmup + 1:
        raise ValueError(f"need at least {warmup + 1} returns, got {returns.size}")
    var = float(np.mean(returns[:warmup] ** 2))
    for r in returns[warmup:]:
        var = lam * var + (1.0 - lam) * r * r
    return float(np.sqrt(annualization * var))
