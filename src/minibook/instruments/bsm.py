"""Black-Scholes-Merton with continuous dividend yield: price and analytical partials.

With phi = +1 for a call and -1 for a put, forward F = S e^{(r-q)T}:

    d1 = [ln(S/K) + (r - q + sigma^2/2) T] / (sigma sqrt(T)),   d2 = d1 - sigma sqrt(T)
    V  = phi [S e^{-qT} N(phi d1) - K e^{-rT} N(phi d2)]

Partials (per unit of underlying):

    dV/dS       = phi e^{-qT} N(phi d1)
    d2V/dS2     = e^{-qT} n(d1) / (S sigma sqrt(T))
    dV/dsigma   = S e^{-qT} n(d1) sqrt(T)
    theta       = dV/dt = -dV/dT
                = -S e^{-qT} n(d1) sigma / (2 sqrt(T))
                  + phi [q S e^{-qT} N(phi d1) - r K e^{-rT} N(phi d2)]

(theta is per year, as calendar time t passes and time to expiry T shrinks.)

Limits. For T <= 0 the value is the intrinsic value max(phi (S - K), 0). For
sigma sqrt(T) below ``SIGMA_SQRT_T_MIN`` the value is the discounted deterministic payoff
max(phi (S e^{-qT} - K e^{-rT}), 0). Both cases have zero gamma and vega.

Reference: J. C. Hull, *Options, Futures, and Other Derivatives*; E. G. Haug, *The Complete
Guide to Option Pricing Formulas*, 2nd ed. (2007), generalized BSM.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from scipy.special import ndtr

SIGMA_SQRT_T_MIN = 1e-12
_INV_SQRT_2PI = 1.0 / math.sqrt(2.0 * math.pi)


class OptionType(StrEnum):
    """Call or put."""

    CALL = "call"
    PUT = "put"

    @property
    def phi(self) -> float:
        """+1 for a call, -1 for a put."""
        return 1.0 if self is OptionType.CALL else -1.0


@dataclass(frozen=True)
class BsmResult:
    """Price and analytical partials per unit of underlying (see module docstring)."""

    price: float
    delta: float
    gamma: float
    vega: float
    theta: float


def _pdf(x: float) -> float:
    return _INV_SQRT_2PI * math.exp(-0.5 * x * x)


def _cdf(x: float) -> float:
    return float(ndtr(x))


def bsm(
    spot: float, strike: float, t: float, r: float, q: float, sigma: float, option_type: OptionType
) -> BsmResult:
    """Generalized BSM price and partials.

    Parameters
    ----------
    spot, strike
        Underlying level S > 0 and strike K > 0.
    t
        Time to expiry T in years (ACT/365F in minibook).
    r, q
        Continuously compounded risk-free rate and dividend yield (decimals).
    sigma
        Volatility (decimal, annualized), >= 0.
    option_type
        Call or put.
    """
    if spot <= 0 or strike <= 0 or sigma < 0:
        raise ValueError("spot and strike must be positive and sigma nonnegative")
    phi = option_type.phi
    if t <= 0:
        itm = phi * (spot - strike) > 0
        return BsmResult(max(phi * (spot - strike), 0.0), phi if itm else 0.0, 0.0, 0.0, 0.0)
    df_q, df_r = math.exp(-q * t), math.exp(-r * t)
    sst = sigma * math.sqrt(t)
    if sst < SIGMA_SQRT_T_MIN:
        fwd_value = phi * (spot * df_q - strike * df_r)
        itm = fwd_value > 0
        theta = phi * (q * spot * df_q - r * strike * df_r) if itm else 0.0
        return BsmResult(max(fwd_value, 0.0), phi * df_q if itm else 0.0, 0.0, 0.0, theta)
    d1 = (math.log(spot / strike) + (r - q + 0.5 * sigma * sigma) * t) / sst
    d2 = d1 - sst
    n_d1 = _pdf(d1)
    cdf1, cdf2 = _cdf(phi * d1), _cdf(phi * d2)
    price = phi * (spot * df_q * cdf1 - strike * df_r * cdf2)
    delta = phi * df_q * cdf1
    gamma = df_q * n_d1 / (spot * sst)
    vega = spot * df_q * n_d1 * math.sqrt(t)
    theta = -spot * df_q * n_d1 * sigma / (2.0 * math.sqrt(t)) + phi * (
        q * spot * df_q * cdf1 - r * strike * df_r * cdf2
    )
    return BsmResult(price, delta, gamma, vega, theta)
