"""Immutable market snapshot and risk factors.

A :class:`MarketSnapshot` holds everything a pricer may read for one valuation date:
zero curves per currency, ECB FX reference rates (units of currency per 1 EUR), equity
index spots, flat vols and dividend yields. Valuation is a pure function of
(instrument, snapshot).

Risk factors and shock units
----------------------------
The units match the VaR shock definitions in the brief, so Greeks, P&L explain and VaR
all move the market through the same :meth:`MarketSnapshot.apply`.

==================  ==========================  =============================================
Factor              ``id``                      shock ``x`` applied as
==================  ==========================  =============================================
ZeroRate(ccy, p)    ``ZR:EUR:5Y``               z_p += x   (one pillar, tent to neighbours)
KeyRate(ccy, k)     ``KR:EUR:5Y``               z(t) += x * tent_k(t) over the key pillars
Parallel(ccy)       ``PAR:EUR``                 z(t) += x
FxSpot(ccy)         ``FX:USD``                  EURccy *= exp(x)        (log return)
EquitySpot(u)       ``EQ:SX5E``                 S *= exp(x)             (log return)
Vol(u)              ``VOL:SX5E``                sigma += x              (absolute)
==================  ==========================  =============================================

Rates are decimals (1bp = 1e-4). USD/JPY is never stored: it is derived as
EURJPY / EURUSD, which keeps the three FX rates triangularly consistent.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from types import MappingProxyType

import numpy as np

from minibook.dates.tenor import Tenor
from minibook.market.curves import ZeroCurve, parallel, tent

REPORTING_CCY = "EUR"


# --------------------------------------------------------------------------- factors
@dataclass(frozen=True)
class ZeroRate:
    """Zero rate at one curve pillar."""

    currency: str
    pillar: str

    @property
    def id(self) -> str:
        """Stable string id."""
        return f"ZR:{self.currency}:{self.pillar}"


@dataclass(frozen=True)
class KeyRate:
    """Key-rate shape centred on a key pillar (bump shape, not a VaR factor)."""

    currency: str
    pillar: str

    @property
    def id(self) -> str:
        """Stable string id."""
        return f"KR:{self.currency}:{self.pillar}"


@dataclass(frozen=True)
class Parallel:
    """Parallel shift of a whole curve (bump shape, not a VaR factor)."""

    currency: str

    @property
    def id(self) -> str:
        """Stable string id."""
        return f"PAR:{self.currency}"


@dataclass(frozen=True)
class FxSpot:
    """ECB reference rate EUR/ccy (units of ccy per 1 EUR)."""

    currency: str

    @property
    def id(self) -> str:
        """Stable string id."""
        return f"FX:{self.currency}"


@dataclass(frozen=True)
class EquitySpot:
    """Equity index level."""

    underlying: str

    @property
    def id(self) -> str:
        """Stable string id."""
        return f"EQ:{self.underlying}"


@dataclass(frozen=True)
class Vol:
    """Flat implied-vol proxy of an underlying."""

    underlying: str

    @property
    def id(self) -> str:
        """Stable string id."""
        return f"VOL:{self.underlying}"


RiskFactor = ZeroRate | KeyRate | Parallel | FxSpot | EquitySpot | Vol


# --------------------------------------------------------------------- data quality
@dataclass(frozen=True)
class FillRecord:
    """One forward-filled input: what was used for ``target_date`` and why."""

    dataset: str
    series: str
    target_date: date
    obs_date: date
    age_days: int
    reason: str


def _frozen(m: Mapping[str, object]) -> MappingProxyType[str, object]:
    return MappingProxyType(dict(m))


# -------------------------------------------------------------------------- snapshot
@dataclass(frozen=True)
class MarketSnapshot:
    """Immutable market state for one valuation date. See module docstring."""

    as_of: date
    curves: Mapping[str, ZeroCurve]
    fx: Mapping[str, float]
    spots: Mapping[str, float]
    vols: Mapping[str, float]
    div_yields: Mapping[str, float]
    key_pillars: tuple[str, ...]
    fills: tuple[FillRecord, ...] = ()
    data_timestamps: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze mappings and validate key pillars and positivity."""
        for name in ("curves", "fx", "spots", "vols", "div_yields", "data_timestamps"):
            object.__setattr__(self, name, _frozen(getattr(self, name)))
        for ccy, curve in self.curves.items():
            missing = [k for k in self.key_pillars if k not in curve.labels]
            if missing:
                raise ValueError(f"{ccy} curve lacks key pillars {missing}")
        if any(v <= 0 for v in (*self.fx.values(), *self.spots.values(), *self.vols.values())):
            raise ValueError("FX rates, spots and vols must be positive")

    # ---------------------------------------------------------------- accessors
    def curve(self, currency: str) -> ZeroCurve:
        """Zero curve of ``currency``."""
        try:
            return self.curves[currency]
        except KeyError as exc:
            raise KeyError(f"no {currency} curve in snapshot {self.as_of}") from exc

    def fx_rate(self, base: str, quote: str) -> float:
        """Units of ``quote`` per 1 ``base``, derived from the EUR crosses."""

        def per_eur(ccy: str) -> float:
            if ccy == REPORTING_CCY:
                return 1.0
            try:
                return float(self.fx[ccy])
            except KeyError as exc:
                raise KeyError(f"no EUR/{ccy} rate in snapshot {self.as_of}") from exc

        return per_eur(quote) / per_eur(base)

    def value(self, factor: RiskFactor) -> float:
        """Return the current level of a VaR risk factor (zero rate, FX, spot or vol)."""
        match factor:
            case ZeroRate(ccy, pillar):
                c = self.curve(ccy)
                return c.zeros[c.label_index(pillar)]
            case FxSpot(ccy):
                return float(self.fx[ccy])
            case EquitySpot(u):
                return float(self.spots[u])
            case Vol(u):
                return float(self.vols[u])
        raise TypeError(f"{factor} is a bump shape, not a risk-factor level")

    def risk_factors(self) -> list[RiskFactor]:
        """All VaR risk factors, in a deterministic order."""
        out: list[RiskFactor] = []
        for ccy in sorted(self.curves):
            out.extend(ZeroRate(ccy, lab) for lab in self.curves[ccy].labels)
        out.extend(FxSpot(c) for c in sorted(self.fx))
        out.extend(EquitySpot(u) for u in sorted(self.spots))
        out.extend(Vol(u) for u in sorted(self.vols))
        return out

    # ------------------------------------------------------------------- shocks
    def bump(self, factor: RiskFactor, size: float) -> MarketSnapshot:
        """Return a new snapshot with one factor shocked (units: module docstring)."""
        return self.apply({factor: size})

    def apply(
        self, shocks: Mapping[RiskFactor, float] | Iterable[tuple[RiskFactor, float]]
    ) -> MarketSnapshot:
        """Return a new snapshot with several shocks applied together (additive)."""
        items = shocks.items() if isinstance(shocks, Mapping) else shocks
        curves = dict(self.curves)
        fx, spots, vols = dict(self.fx), dict(self.spots), dict(self.vols)
        for factor, x in items:
            match factor:
                case ZeroRate(ccy, pillar):
                    c = curves[ccy]
                    curves[ccy] = c.shifted(tent(c.times, c.label_index(pillar), x))
                case KeyRate(ccy, pillar):
                    knots = [Tenor.parse(k).years for k in self.key_pillars]
                    curves[ccy] = curves[ccy].shifted(
                        tent(knots, self.key_pillars.index(pillar), x)
                    )
                case Parallel(ccy):
                    curves[ccy] = curves[ccy].shifted(parallel(x))
                case FxSpot(ccy):
                    fx[ccy] = fx[ccy] * float(np.exp(x))
                case EquitySpot(u):
                    spots[u] = spots[u] * float(np.exp(x))
                case Vol(u):
                    vols[u] = vols[u] + x
                case _:
                    raise TypeError(f"unknown risk factor {factor!r}")
        return replace(self, curves=curves, fx=fx, spots=spots, vols=vols)
