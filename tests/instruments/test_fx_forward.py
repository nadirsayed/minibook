"""FX forwards: spot/delivery dates, PV at the outright, CIP, triangular consistency, signs."""

from __future__ import annotations

import dataclasses
import math
from datetime import date

import pytest

from minibook.config.settings import Settings
from minibook.dates.calendars import JP, TARGET, US
from minibook.dates.tenor import Tenor
from minibook.instruments.factory import fx_convention
from minibook.instruments.fx_forward import FxConvention, FxForward
from minibook.market.snapshot import FxSpot, MarketSnapshot

TRADE = date(2026, 11, 2)


@pytest.mark.parametrize(
    ("pair", "trade", "spot"),
    [
        ("EURUSD", TRADE, date(2026, 11, 4)),
        ("USDJPY", TRADE, date(2026, 11, 5)),  # 3 Nov Culture Day: JP lag skips it
        ("EURUSD", date(2026, 11, 9), date(2026, 11, 12)),  # 11 Nov US holiday on spot
        ("USDJPY", date(2026, 11, 24), date(2026, 11, 27)),  # 26 Nov Thanksgiving on spot
    ],
)
def test_spot_dates(settings: Settings, pair: str, trade: date, spot: date) -> None:
    assert fx_convention(settings, pair).spot_date(trade) == spot


def test_delivery_dates_and_end_of_month(settings: Settings) -> None:
    eurusd = fx_convention(settings, "EURUSD")
    assert eurusd.delivery_date(date(2026, 11, 4), Tenor.parse("6M")) == date(2027, 5, 4)
    usdjpy = fx_convention(settings, "USDJPY")
    assert usdjpy.delivery_date(date(2026, 11, 5), Tenor.parse("3M")) == date(2027, 2, 5)
    # End-of-month rule: spot on the last business day of November -> last of February.
    assert eurusd.delivery_date(date(2026, 11, 30), Tenor.parse("3M")) == date(2027, 2, 26)


def outright(
    snap: MarketSnapshot, base: str, quote: str, n: float, conv: FxConvention, tenor: str = "6M"
) -> FxForward:
    delivery = conv.delivery_date(conv.spot_date(snap.as_of), Tenor.parse(tenor))
    probe = FxForward("X", base, quote, n, 1.0, delivery, conv)
    return dataclasses.replace(probe, strike=probe.forward_rate(snap))


def test_struck_at_outright_has_zero_pv(trade_snap: MarketSnapshot, settings: Settings) -> None:
    for base, quote, n in (("EUR", "USD", 5e6), ("USD", "JPY", -3e6)):
        f = outright(trade_snap, base, quote, n, fx_convention(settings, base + quote))
        assert abs(f.pv(trade_snap)) < 1e-6


def test_covered_interest_parity(trade_snap: MarketSnapshot, settings: Settings) -> None:
    conv = fx_convention(settings, "EURUSD")
    f = outright(trade_snap, "EUR", "USD", 1.0, conv)
    t_s = (conv.spot_date(TRADE) - TRADE).days / 365
    t_d = (f.delivery - TRADE).days / 365
    eur, usd = trade_snap.curve("EUR"), trade_snap.curve("USD")
    carry = math.exp(
        (float(usd.zero(t_d)) * t_d - float(usd.zero(t_s)) * t_s)
        - (float(eur.zero(t_d)) * t_d - float(eur.zero(t_s)) * t_s)
    )
    # Recorded ECB EUR/USD 2026-11-02 = 1.1216 (fixture); USD rates above EUR: F > S.
    assert f.strike == pytest.approx(1.1216 * carry, rel=1e-14)
    assert f.strike > 1.1216


def test_triangular_consistency(trade_snap: MarketSnapshot) -> None:
    joint = FxConvention(2, TARGET + JP, TARGET + US + JP)
    f_eurusd = outright(trade_snap, "EUR", "USD", 1.0, joint)
    f_usdjpy = outright(trade_snap, "USD", "JPY", 1.0, joint)
    f_eurjpy = outright(trade_snap, "EUR", "JPY", 1.0, joint)
    assert f_eurusd.strike * f_usdjpy.strike == pytest.approx(f_eurjpy.strike, rel=1e-13)


def test_signs_and_eur_translation(trade_snap: MarketSnapshot, settings: Settings) -> None:
    long_eur = outright(trade_snap, "EUR", "USD", 5e6, fx_convention(settings, "EURUSD"))
    up = trade_snap.bump(FxSpot("USD"), 0.01)  # EUR/USD +1% (log)
    assert long_eur.pv(up) > 0
    assert long_eur.pv(up) == pytest.approx(long_eur.pv_quote(up) / up.fx["USD"])
    short_usd = outright(trade_snap, "USD", "JPY", -3e6, fx_convention(settings, "USDJPY"))
    jpy_up = trade_snap.bump(FxSpot("JPY"), 0.01)  # EUR/JPY +1% => USD/JPY +1%
    assert short_usd.pv(jpy_up) < 0
    assert short_usd.pv(jpy_up) == pytest.approx(short_usd.pv_quote(jpy_up) / jpy_up.fx["JPY"])


def test_after_delivery(trade_snap: MarketSnapshot, settings: Settings) -> None:
    f = outright(trade_snap, "EUR", "USD", 5e6, fx_convention(settings, "EURUSD"))
    at = dataclasses.replace(trade_snap, as_of=f.delivery)
    assert f.pv(at) == 0.0
    flows = f.cashflows(TRADE, f.delivery, at)
    assert len(flows) == 1 and flows[0].currency == "USD"
    assert flows[0].amount == pytest.approx(5e6 * (at.fx["USD"] - f.strike))
    assert f.cashflows(f.delivery, date(2028, 1, 1), at) == []
