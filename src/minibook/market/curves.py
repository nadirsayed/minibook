"""Zero curves: continuously compounded zero rates on pillars, linear interpolation.

Conventions (docs/decisions.md, ADR-009)
----------------------------------------
* Time t is in years from the valuation date: ACT/365F for dates, ``Tenor.years`` for
  pillars (3M -> 0.25).
* DF(t) = exp(-z(t) * t), so DF(0) = 1.
* z(t) is linear in t between pillars and flat outside them (flat-zero extrapolation).
* Instantaneous forwards are not guaranteed nonnegative: real curves can have negative
  forwards, so DF monotonicity is only tested on curves with nonnegative forwards.

Shifts. ``shifted(f)`` adds f(t_i) to each pillar zero. When f is piecewise linear with
knots on the pillars (parallel shift, single-pillar tent, key-rate tent with key tenors
included in the pillars), the shifted curve equals z(t) + f(t) at *every* t, not only at
the pillars.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
TIME_TOL = 1e-12


@dataclass(frozen=True)
class ZeroCurve:
    """Immutable zero curve.

    Parameters
    ----------
    currency
        ISO code, e.g. ``"EUR"``.
    times
        Strictly increasing positive pillar times (years).
    zeros
        Continuously compounded zero rates at the pillars (decimal, 0.025 = 2.5%).
    labels
        Optional pillar labels (e.g. ``"5Y"``), same length as ``times``.
    """

    currency: str
    times: tuple[float, ...]
    zeros: tuple[float, ...]
    labels: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        """Validate pillars and rates."""
        t = np.asarray(self.times, dtype=float)
        if len(self.times) == 0 or len(self.times) != len(self.zeros):
            raise ValueError("times and zeros must be non-empty and of equal length")
        if self.labels and len(self.labels) != len(self.times):
            raise ValueError("labels must match times")
        if t[0] <= 0 or np.any(np.diff(t) <= 0):
            raise ValueError(f"pillar times must be positive and increasing: {self.times}")
        if not np.all(np.isfinite(self.zeros)):
            raise ValueError("zero rates must be finite")

    # ----------------------------------------------------------------- evaluation
    def zero(self, t: float | FloatArray) -> float | FloatArray:
        """z(t): linear between pillars, flat outside."""
        out = np.interp(t, self.times, self.zeros)
        return float(out) if np.ndim(out) == 0 else np.asarray(out, dtype=float)

    def df(self, t: float | FloatArray) -> float | FloatArray:
        """DF(t) = exp(-z(t) t)."""
        z = np.asarray(self.zero(t), dtype=float)
        out = np.exp(-z * np.asarray(t, dtype=float))
        return float(out) if np.ndim(out) == 0 else out

    def forward_rate(self, t1: float, t2: float) -> float:
        """Continuously compounded forward rate between t1 and t2 (t2 > t1)."""
        if t2 - t1 <= TIME_TOL:
            raise ValueError("forward_rate needs t2 > t1")
        return float(np.log(float(self.df(t1)) / float(self.df(t2))) / (t2 - t1))

    def label_index(self, label: str) -> int:
        """Index of the pillar with ``label``."""
        try:
            return self.labels.index(label)
        except ValueError as exc:
            raise KeyError(f"{self.currency} curve has no pillar {label!r}") from exc

    # ------------------------------------------------------------- transformations
    def shifted(self, shift: Callable[[FloatArray], FloatArray]) -> ZeroCurve:
        """Return a new curve with z_i + shift(t_i) at every pillar."""
        t = np.asarray(self.times, dtype=float)
        dz = np.asarray(shift(t), dtype=float)
        return ZeroCurve(
            self.currency, self.times, tuple(map(float, np.add(self.zeros, dz))), self.labels
        )

    def with_pillars(self, times: Sequence[float], labels: Sequence[str]) -> ZeroCurve:
        """Insert extra pillars at their interpolated values; the curve is unchanged."""
        existing = dict(zip(self.times, self.labels or [""] * len(self.times), strict=True))
        for t, lab in zip(times, labels, strict=True):
            match = next((x for x in existing if abs(x - t) < TIME_TOL), None)
            if match is None:
                existing[float(t)] = lab
            elif not existing[match]:
                existing[match] = lab
        new_t = sorted(existing)
        new_z = [float(self.zero(t)) for t in new_t]
        return ZeroCurve(
            self.currency, tuple(new_t), tuple(new_z), tuple(existing[t] for t in new_t)
        )


def parallel(size: float) -> Callable[[FloatArray], FloatArray]:
    """Shift function: +size at every t."""
    return lambda t: np.full_like(t, size, dtype=float)


def tent(knots: Sequence[float], i: int, size: float) -> Callable[[FloatArray], FloatArray]:
    """Key-rate shape: ``size`` at ``knots[i]``, linear to 0 at the neighbouring knots.

    The first knot's shape is flat to the left and the last knot's is flat to the right,
    so the tents over all knots add up to a parallel shift.
    """
    k = np.asarray(knots, dtype=float)
    unit = np.zeros(len(k))
    unit[i] = size

    def f(t: FloatArray) -> FloatArray:
        return np.asarray(np.interp(t, k, unit), dtype=float)

    return f
