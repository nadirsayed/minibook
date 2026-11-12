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


class PricingError(RuntimeError):
    """An instrument cannot be priced with the given snapshot (missing input)."""


def to_eur(amount: float, currency: str, market: MarketSnapshot) -> float:
    """Convert ``amount`` in ``currency`` to EUR at the snapshot's ECB reference rates."""
    return amount / market.fx_rate("EUR", currency)
