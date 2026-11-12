"""VaR backtesting: exceptions, Kupiec POF test, Basel traffic light.

An exception on day t is a P&L below minus the VaR computed on t-1: P&L_t < -VaR_{t-1}.

Kupiec (1995) proportion-of-failures test, x exceptions in N days, expected rate p:

    LR_POF = -2 ln[(1-p)^{N-x} p^x] + 2 ln[(1-x/N)^{N-x} (x/N)^x]   ~ chi2(1),

with 0 ln 0 = 0. Source: P. Kupiec, "Techniques for Verifying the Accuracy of Risk
Measurement Models", Journal of Derivatives 3(2), 1995.

Basel traffic light (99% VaR, 250 observations): green 0-4, yellow 5-9, red >= 10
exceptions. Basel Committee on Banking Supervision (1996), "Supervisory framework for the use
of backtesting in conjunction with the internal models approach to market risk capital
requirements".

**Small samples (owner rule).** The zones are defined on 250 observations, and Kupiec has
almost no power on a few dozen. With N < ``min_observations``, no zone and no test conclusion
is given: the status is "insufficient observations (N = x)". A misleading green is never
shown. With N >= 250, the zone uses the most recent 250 observations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import pandas as pd
from scipy.stats import chi2

from minibook.config.settings import BacktestSettings


def _xlogy(x: float, y: float) -> float:
    return 0.0 if x == 0 else x * math.log(y)


def kupiec_pof(n: int, x: int, p: float) -> tuple[float, float]:
    """(LR_POF, p-value) for x exceptions in n observations at expected rate p."""
    if not 0 <= x <= n or n <= 0:
        raise ValueError(f"need 0 <= x <= n and n > 0, got x={x}, n={n}")
    log_l0 = _xlogy(n - x, 1.0 - p) + _xlogy(x, p)
    phat = x / n
    log_l1 = _xlogy(n - x, 1.0 - phat) + _xlogy(x, phat)
    lr = max(0.0, -2.0 * (log_l0 - log_l1))
    return lr, float(chi2.sf(lr, df=1))


def traffic_light(exceptions: int, cfg: BacktestSettings) -> str:
    """Basel zone for the exceptions in 250 observations."""
    if exceptions >= cfg.red_from:
        return "red"
    return "yellow" if exceptions >= cfg.yellow_from else "green"


@dataclass(frozen=True)
class BacktestResult:
    """Backtest summary. ``zone`` and ``kupiec_reject`` are None when N is too small."""

    n: int
    exceptions: int
    exception_dates: tuple[date, ...]
    expected: float
    kupiec_lr: float | None
    kupiec_pvalue: float | None
    kupiec_reject: bool | None
    zone: str | None
    status: str


def backtest(obs: pd.DataFrame, var_confidence: float, cfg: BacktestSettings) -> BacktestResult:
    """Backtest P&L against the previous day's VaR.

    Parameters
    ----------
    obs
        Columns ``date`` (day t), ``var_prev`` (VaR of t-1, positive) and ``pnl`` (P&L of t).
    """
    obs = obs.sort_values("date").reset_index(drop=True)
    n = len(obs)
    p = 1.0 - var_confidence
    hits = obs["pnl"] < -obs["var_prev"]
    x = int(hits.sum())
    dates = tuple(obs.loc[hits, "date"])
    if n == 0:
        return BacktestResult(
            0, 0, (), 0.0, None, None, None, None, "insufficient observations (N = 0)"
        )
    lr, pval = kupiec_pof(n, x, p)
    if n < cfg.min_observations:
        return BacktestResult(
            n, x, dates, n * p, lr, pval, None, None, f"insufficient observations (N = {n})"
        )
    recent = int(hits.iloc[-cfg.min_observations :].sum())
    zone = traffic_light(recent, cfg)
    reject = pval < cfg.kupiec_significance
    status = (
        f"{zone} zone ({recent} exceptions in the last {cfg.min_observations} days); "
        f"Kupiec POF {'rejects' if reject else 'does not reject'} "
        f"(p = {pval:.3f}, N = {n})"
    )
    return BacktestResult(n, x, dates, n * p, lr, pval, reject, zone, status)
