"""ECB Svensson yield curve (AAA euro area central government bonds).

ECB parametrisation (``SV_C_YM``: continuous compounding, parameters in percent):

    z(m) = b0 + b1 L1 + b2 (L1 - e^{-m/t1}) + b3 (L2 - e^{-m/t2}),
    Lk  = (1 - e^{-m/tk}) / (m/tk),

with m the residual maturity in years and z(m) in percent. Source: ECB, "Euro area yield
curves - technical notes",
https://www.ecb.europa.eu/stats/financial_markets_and_interest_rates/euro_area_yield_curves/html/technical_notes.pdf

minibook sets m = t, with t the ACT/365F time from the valuation date, and divides by 100
to get decimal rates.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from minibook.dates.tenor import Tenor
from minibook.market.curves import FloatArray, ZeroCurve

PERCENT = 100.0
BP_PER_PERCENT = 100.0


@dataclass(frozen=True)
class SvenssonParams:
    """Svensson parameters as published by the ECB (betas in percent, taus in years)."""

    beta0: float
    beta1: float
    beta2: float
    beta3: float
    tau1: float
    tau2: float

    @classmethod
    def from_ecb(cls, row: Mapping[str, float]) -> SvenssonParams:
        """Build from a mapping with keys BETA0..BETA3, TAU1, TAU2 (ECB series names)."""
        return cls(row["BETA0"], row["BETA1"], row["BETA2"], row["BETA3"], row["TAU1"], row["TAU2"])

    def zero_pct(self, m: float | FloatArray) -> FloatArray:
        """Continuously compounded spot rate in percent at maturity m > 0 (years)."""
        m = np.asarray(m, dtype=float)
        x1, x2 = m / self.tau1, m / self.tau2
        l1 = (1.0 - np.exp(-x1)) / x1
        l2 = (1.0 - np.exp(-x2)) / x2
        return np.asarray(
            self.beta0
            + self.beta1 * l1
            + self.beta2 * (l1 - np.exp(-x1))
            + self.beta3 * (l2 - np.exp(-x2)),
            dtype=float,
        )

    def zero(self, m: float | FloatArray) -> FloatArray:
        """Continuously compounded spot rate as a decimal (percent / 100)."""
        return self.zero_pct(m) / PERCENT


def svensson_curve(params: SvenssonParams, pillars: list[str], currency: str = "EUR") -> ZeroCurve:
    """Sample the Svensson curve at ``pillars`` (tenor labels) into a :class:`ZeroCurve`."""
    tenors = [Tenor.parse(p) for p in pillars]
    times = np.array([t.years for t in tenors])
    return ZeroCurve(
        currency, tuple(map(float, times)), tuple(map(float, params.zero(times))), tuple(pillars)
    )


def validation_errors_bp(
    params: SvenssonParams, published_pct: Mapping[str, float]
) -> dict[str, float]:
    """Rebuilt minus published spot rate, in bp, for each ``SR_<tenor>`` key.

    Example key: ``"SR_5Y"`` -> m = 5.
    """
    out = {}
    for key, value in published_pct.items():
        m = Tenor.parse(key.removeprefix("SR_")).years
        out[key] = float((params.zero_pct(m) - value) * BP_PER_PERCENT)
    return out
