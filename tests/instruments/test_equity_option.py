from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from minibook.instruments.base import PricingError
from minibook.instruments.bsm import OptionType, bsm
from minibook.instruments.equity_option import EquityOption
from minibook.market.snapshot import MarketSnapshot

EXPIRY = date(2027, 2, 2)


def option(
    snap: MarketSnapshot, kind: OptionType = OptionType.CALL, qty: float = 50
) -> EquityOption:
    return EquityOption("O", "SX5E", kind, qty, 10.0, snap.spots["SX5E"], EXPIRY)


def test_pv_is_scaled_bsm(trade_snap: MarketSnapshot) -> None:
    o = option(trade_snap)
    t = (EXPIRY - trade_snap.as_of).days / 365
    r = float(trade_snap.curve("EUR").zero(t))
    ref = bsm(
        trade_snap.spots["SX5E"],
        o.strike,
        t,
        r,
        trade_snap.div_yields["SX5E"],
        trade_snap.vols["SX5E"],
        OptionType.CALL,
    ).price
    assert o.pv(trade_snap) == pytest.approx(500 * ref, rel=1e-14)
    assert option(trade_snap, qty=-50).pv(trade_snap) == pytest.approx(-o.pv(trade_snap))


def test_missing_dividend_yield_is_an_error(trade_snap: MarketSnapshot) -> None:
    no_q = dataclasses.replace(trade_snap, div_yields={})
    with pytest.raises(PricingError, match="no dividend yield"):
        option(trade_snap).pv(no_q)


def test_expiry_and_settlement(trade_snap: MarketSnapshot) -> None:
    o = dataclasses.replace(option(trade_snap, OptionType.PUT), strike=1e6)  # deep ITM put
    at = dataclasses.replace(trade_snap, as_of=EXPIRY)
    assert o.pv(at) == 0.0
    (cf,) = o.cashflows(date(2027, 2, 1), EXPIRY, at)
    assert cf.amount == pytest.approx(500 * (1e6 - at.spots["SX5E"]))
    assert o.cashflows(EXPIRY, date(2027, 3, 1), at) == []
