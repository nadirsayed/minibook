"""Common instrument protocol and cashflow record.

Every instrument is an immutable dataclass. Its value is a pure function of
(instrument, MarketSnapshot):

    pv(market) -> float      present value in EUR at ``market.as_of``
    cashflows(start, end, market) -> list[Cashflow]
        cash paid or received in the window (start, end], converted to EUR with ``market``.
        Used by P&L explain: Actual = PV_t - PV_{t-1} + cashflows in (t-1, t].

Sign convention: positive = value to the book (asset), negative = liability.
Cashflows: positive = received, negative = paid.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol, runtime_checkable

from minibook.market.snapshot import MarketSnapshot


@dataclass(frozen=True)
class Cashflow:
    """A settled cashflow, in its own currency and in EUR."""

    instrument_id: str
    pay_date: date
    currency: str
    amount: float
    amount_eur: float
    description: str


@runtime_checkable
class Instrument(Protocol):
    """Protocol shared by every instrument of the book."""

    @property
    def id(self) -> str:
        """Unique instrument id (as in book.yaml)."""
        ...

    def pv(self, market: MarketSnapshot) -> float:
        """Present value in EUR."""
        ...

    def cashflows(self, start: date, end: date, market: MarketSnapshot) -> list[Cashflow]:
        """Cashflows with pay date in (start, end], converted to EUR at ``market``."""
        ...


class Measure(StrEnum):
    """Sensitivity measures, all in EUR (sign-convention table in the README).

    DELTA_1PCT  D = 0.01 S V_S                    (EUR per +1% move of the factor)
    GAMMA_1PCT  G = (0.01 S)^2 V_SS               (Taylor gamma, EUR)
    VEGA_1PT    0.01 V_sigma                       (EUR per +1 vol point)
    THETA_1D    PV(t + 1d) + CF(t, t + 1d] - PV(t) (EUR per calendar day, market constant)
    DV01        PV(curve + 1bp) - PV(curve)        (parallel, per currency)
    KR_DV01     PV(curve + 1bp key-rate tent) - PV (per currency and key pillar)
    DIV_10BP    0.001 V_q                          (EUR per +10bp of dividend yield)
    """

    DELTA_1PCT = "delta_1pct"
    GAMMA_1PCT = "gamma_1pct"
    VEGA_1PT = "vega_1pt"
    THETA_1D = "theta_1d"
    DV01 = "dv01"
    KR_DV01 = "kr_dv01"
    DIV_10BP = "div_10bp"


@dataclass(frozen=True)
class GreekRow:
    """One sensitivity of one instrument to one risk factor (EUR)."""

    instrument_id: str
    measure: Measure
    risk_factor: str
    value: float


class PricingError(RuntimeError):
    """An instrument cannot be priced with the given snapshot (missing input)."""


def to_eur(amount: float, currency: str, market: MarketSnapshot) -> float:
    """Convert ``amount`` in ``currency`` to EUR at the snapshot's ECB reference rates."""
    return amount / market.fx_rate("EUR", currency)
