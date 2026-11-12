"""Par-yield to zero-curve bootstrap (USD Treasury CMT, JPY MoF constant maturity).

Instruments (docs/decisions.md, ADR-008 and ADR-010)
----------------------------------------------------
Money-market tenors (USD 1M, 3M, 6M: Treasury bills, bond-equivalent yields):
    DF(T) = 1 / (1 + y T)            =>  z(T) = ln(1 + y T) / T

Coupon tenors (USD >= 1Y, JPY all tenors): a par bond paying y/f, f times a year, on the
regular grid t_i = i/f, i = 1 .. f T:
    1 = (y / f) * sum_i DF(t_i) + DF(T)

The bootstrap is sequential. For each new pillar T_k the unknown is z(T_k). Coupon dates
between pillars use linear interpolation between z(T_{k-1}) and z(T_k), and dates before the
first pillar use flat-zero extrapolation, which is the same rule as :class:`ZeroCurve`. Each
step is a 1-D root solve (Brent). Every input instrument therefore reprices exactly with
the returned curve.

Simplifications: pillar times are nominal (``Tenor.years``), not actual settlement dates,
and CMT yields are treated as exact par yields of hypothetical bonds.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
from scipy.optimize import brentq

from minibook.dates.tenor import Tenor
from minibook.market.curves import ZeroCurve

ROOT_BRACKET = (-0.5, 1.0)  # zero-rate search interval (decimal); far beyond any market
ROOT_XTOL = 1e-15


def coupon_times(maturity: float, frequency: int) -> np.ndarray:
    """Regular coupon times i/f, i = 1 .. f*T (T must be a multiple of 1/f)."""
    n = round(maturity * frequency)
    if abs(n / frequency - maturity) > 1e-9:
        raise ValueError(f"maturity {maturity} is not a multiple of 1/{frequency}")
    return np.arange(1, n + 1, dtype=float) / frequency


def par_yield(curve: ZeroCurve, maturity: float, frequency: int) -> float:
    """Par yield of a bond with coupons ``frequency`` times a year, from ``curve``."""
    t = coupon_times(maturity, frequency)
    dfs = np.asarray(curve.df(t), dtype=float)
    return float(frequency * (1.0 - dfs[-1]) / dfs.sum())


def money_market_yield(curve: ZeroCurve, maturity: float) -> float:
    """Return the simple yield y such that DF(T) = 1 / (1 + y T)."""
    return float((1.0 / float(curve.df(maturity)) - 1.0) / maturity)


def bootstrap_par_curve(
    currency: str,
    quotes: Mapping[str, float],
    money_market: Sequence[str],
    frequency: int,
) -> ZeroCurve:
    """Bootstrap a zero curve from par / money-market yields.

    Parameters
    ----------
    currency
        Curve currency.
    quotes
        Tenor label -> yield as a decimal (0.045 = 4.5%).
    money_market
        Labels quoted as simple money-market yields. All other labels are par coupon yields.
    frequency
        Coupons per year of the par instruments (2 for UST and JGB).

    Returns
    -------
    ZeroCurve
        Pillars at ``Tenor.years`` of each label, in increasing order.
    """
    items = sorted(((Tenor.parse(k).years, k, v) for k, v in quotes.items()), key=lambda x: x[0])
    times: list[float] = []
    zeros: list[float] = []
    labels: list[str] = []
    for t_k, label, y in items:
        if label in money_market:
            z_k = float(np.log1p(y * t_k) / t_k)
        else:
            cpn = coupon_times(t_k, frequency)

            def residual(
                z: float, cpn: np.ndarray = cpn, y: float = y, t_k: float = t_k, label: str = label
            ) -> float:
                trial = ZeroCurve(currency, (*times, t_k), (*zeros, z), (*labels, label))
                dfs = np.asarray(trial.df(cpn), dtype=float)
                return float(y / frequency * dfs.sum() + dfs[-1] - 1.0)

            z_k = float(brentq(residual, *ROOT_BRACKET, xtol=ROOT_XTOL))
        times.append(t_k)
        zeros.append(z_k)
        labels.append(label)
    return ZeroCurve(currency, tuple(times), tuple(zeros), tuple(labels))
