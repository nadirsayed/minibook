from __future__ import annotations

import dataclasses
from datetime import date

import numpy as np
import pytest

from minibook.market.curves import ZeroCurve
from minibook.market.snapshot import (
    EquitySpot,
    FxSpot,
    KeyRate,
    MarketSnapshot,
    Parallel,
    Vol,
    ZeroRate,
)

KEYS = ("3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y")
KEY_T = (0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0)


def curve(ccy: str, level: float) -> ZeroCurve:
    """SYNTHETIC upward-sloping curve with the key pillars plus a 20Y pillar."""
    times = (*KEY_T, 20.0)
    zeros = tuple(level + 0.001 * t for t in times)
    return ZeroCurve(ccy, times, zeros, (*KEYS, "20Y"))


def snap() -> MarketSnapshot:
    """SYNTHETIC snapshot."""
    return MarketSnapshot(
        as_of=date(2026, 11, 2),
        curves={"EUR": curve("EUR", 0.02), "USD": curve("USD", 0.04), "JPY": curve("JPY", 0.01)},
        fx={"USD": 1.12, "JPY": 177.0},
        spots={"SX5E": 5000.0},
        vols={"SX5E": 0.18},
        div_yields={"SX5E": 0.03},
        key_pillars=KEYS,
    )


def test_immutable() -> None:
    s = snap()
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.as_of = date(2026, 1, 1)  # type: ignore[misc]
    with pytest.raises(TypeError):
        s.fx["USD"] = 2.0  # type: ignore[index]


def test_bump_returns_new_snapshot_and_leaves_original() -> None:
    s = snap()
    b = s.bump(EquitySpot("SX5E"), 0.01)
    assert b.spots["SX5E"] == pytest.approx(5000.0 * np.exp(0.01))
    assert s.spots["SX5E"] == 5000.0
    assert s.bump(Vol("SX5E"), 0.01).vols["SX5E"] == pytest.approx(0.19)


def test_rate_shocks() -> None:
    s = snap()
    eur = s.curve("EUR")
    zr = s.bump(ZeroRate("EUR", "5Y"), 1e-4).curve("EUR")
    assert zr.zero(5.0) - eur.zero(5.0) == pytest.approx(1e-4)
    assert zr.zero(3.0) == eur.zero(3.0) and zr.zero(7.0) == eur.zero(7.0)
    assert zr.zero(4.0) - eur.zero(4.0) == pytest.approx(0.5e-4)
    par = s.bump(Parallel("EUR"), 1e-4).curve("EUR")
    summed = s.apply({KeyRate("EUR", k): 1e-4 for k in KEYS}).curve("EUR")
    grid = np.linspace(0, 25, 251)
    np.testing.assert_allclose(summed.zero(grid), par.zero(grid), atol=1e-16)
    assert s.bump(Parallel("EUR"), 1e-4).curve("USD") is s.curve("USD")


def test_fx_triangular_consistency() -> None:
    s = snap()
    assert s.fx_rate("USD", "JPY") == pytest.approx(177.0 / 1.12)
    assert s.fx_rate("EUR", "USD") * s.fx_rate("USD", "JPY") == pytest.approx(
        s.fx_rate("EUR", "JPY")
    )
    assert s.fx_rate("USD", "EUR") == pytest.approx(1 / 1.12)
    assert s.fx_rate("EUR", "EUR") == 1.0
    b = s.bump(FxSpot("USD"), 0.01)  # EUR/USD up 1% (log): USD/JPY down 1% (log)
    assert np.log(b.fx_rate("USD", "JPY") / s.fx_rate("USD", "JPY")) == pytest.approx(-0.01)
    with pytest.raises(KeyError, match="EUR/GBP"):
        s.fx_rate("GBP", "EUR")


def test_risk_factors_and_values() -> None:
    s = snap()
    ids = [f.id for f in s.risk_factors()]
    assert ids[:2] == ["ZR:EUR:3M", "ZR:EUR:6M"]
    assert ids[9:11] == ["ZR:JPY:3M", "ZR:JPY:6M"]  # currencies sorted: EUR, JPY, USD
    assert ids[-4:] == ["FX:JPY", "FX:USD", "EQ:SX5E", "VOL:SX5E"]
    assert len(ids) == 3 * 9 + 2 + 1 + 1
    assert s.value(ZeroRate("USD", "20Y")) == pytest.approx(0.04 + 0.02)
    assert s.value(FxSpot("JPY")) == 177.0
    assert s.value(EquitySpot("SX5E")) == 5000.0 and s.value(Vol("SX5E")) == 0.18
    with pytest.raises(TypeError, match="bump shape"):
        s.value(Parallel("EUR"))


def test_validation() -> None:
    bad = ZeroCurve("EUR", (1.0,), (0.02,), ("1Y",))
    with pytest.raises(ValueError, match="key pillars"):
        dataclasses.replace(snap(), curves={"EUR": bad})
    with pytest.raises(ValueError, match="positive"):
        snap().bump(Vol("SX5E"), -0.5)
    with pytest.raises(KeyError, match="no GBP curve"):
        snap().curve("GBP")
