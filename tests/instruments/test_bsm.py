"""BSM: textbook references, parity, analytical Greeks vs finite differences, limits."""

from __future__ import annotations

import math

import pytest
import QuantLib as ql
from hypothesis import given, settings
from hypothesis import strategies as st

from minibook.instruments.bsm import OptionType, bsm

CALL, PUT = OptionType.CALL, OptionType.PUT


def test_hull_example() -> None:
    # Hull, "Options, Futures, and Other Derivatives", BSM worked example:
    # S0 = 42, K = 40, r = 10%, sigma = 20%, T = 0.5 -> c = 4.76, p = 0.81 (2 decimals).
    assert bsm(42, 40, 0.5, 0.10, 0.0, 0.20, CALL).price == pytest.approx(4.76, abs=0.005)
    assert bsm(42, 40, 0.5, 0.10, 0.0, 0.20, PUT).price == pytest.approx(0.81, abs=0.005)


def test_haug_merton_1973_example() -> None:
    # Haug, "The Complete Guide to Option Pricing Formulas", 2nd ed. (2007), Merton (1973)
    # European put on an index: S = 100, K = 95, T = 0.5, r = 10%, q = 5%, sigma = 20%
    # -> p = 2.4648.
    assert bsm(100, 95, 0.5, 0.10, 0.05, 0.20, PUT).price == pytest.approx(2.4648, abs=5e-5)


inputs = st.tuples(
    st.floats(50, 150),
    st.floats(50, 150),
    st.floats(0.02, 3.0),
    st.floats(-0.01, 0.08),
    st.floats(0.0, 0.06),
    st.floats(0.05, 0.8),
)


@given(inputs)
def test_put_call_parity(x: tuple[float, ...]) -> None:
    s, k, t, r, q, v = x
    c, p = bsm(s, k, t, r, q, v, CALL).price, bsm(s, k, t, r, q, v, PUT).price
    assert c - p == pytest.approx(s * math.exp(-q * t) - k * math.exp(-r * t), abs=1e-9)


@settings(max_examples=200)
@given(inputs, st.sampled_from([CALL, PUT]))
def test_greeks_match_central_differences(x: tuple[float, ...], kind: OptionType) -> None:
    s, k, t, r, q, v = x
    res = bsm(s, k, t, r, q, v, kind)

    def price(**kw: float) -> float:
        a = {"spot": s, "strike": k, "t": t, "r": r, "q": q, "sigma": v} | kw
        return bsm(a["spot"], a["strike"], a["t"], a["r"], a["q"], a["sigma"], kind).price

    # Spot step proportional to the price-curve width S sigma sqrt(T): a fixed relative step
    # is too coarse for short-dated, low-vol options (truncation error ~ (h / S sigma sqrt T)^2).
    # Likewise the vol step scales with sigma (deep OTM options have large volga).
    hs, hv, ht = 1e-3 * s * v * math.sqrt(t), 1e-4 * v, 1e-5
    fd_delta = (price(spot=s + hs) - price(spot=s - hs)) / (2 * hs)
    fd_gamma = (price(spot=s + hs) - 2 * res.price + price(spot=s - hs)) / hs**2
    fd_vega = (price(sigma=v + hv) - price(sigma=v - hv)) / (2 * hv)
    fd_theta = -(price(t=t + ht) - price(t=t - ht)) / (2 * ht)
    # Brief: rel tol 1e-4; absolute floors for Greeks that are numerically ~0.
    assert res.delta == pytest.approx(fd_delta, rel=1e-4, abs=1e-7)
    assert res.gamma == pytest.approx(fd_gamma, rel=1e-4, abs=1e-6)
    assert res.vega == pytest.approx(fd_vega, rel=1e-4, abs=1e-6)
    assert res.theta == pytest.approx(fd_theta, rel=1e-4, abs=1e-5)


def test_matches_quantlib_analytic_engine() -> None:
    # Independent implementation: QuantLib AnalyticEuropeanEngine with flat curves.
    today = ql.Date(2, 11, 2026)
    ql.Settings.instance().evaluationDate = today
    days = 182
    s, k, r, q, v = 5000.0, 5100.0, 0.025, 0.03, 0.18
    dc = ql.Actual365Fixed()
    proc = ql.BlackScholesMertonProcess(
        ql.QuoteHandle(ql.SimpleQuote(s)),
        ql.YieldTermStructureHandle(ql.FlatForward(today, q, dc)),
        ql.YieldTermStructureHandle(ql.FlatForward(today, r, dc)),
        ql.BlackVolTermStructureHandle(ql.BlackConstantVol(today, ql.TARGET(), v, dc)),
    )
    for kind, qtype in ((CALL, ql.Option.Call), (PUT, ql.Option.Put)):
        opt = ql.EuropeanOption(ql.PlainVanillaPayoff(qtype, k), ql.EuropeanExercise(today + days))
        opt.setPricingEngine(ql.AnalyticEuropeanEngine(proc))
        mine = bsm(s, k, days / 365, r, q, v, kind)
        assert mine.price == pytest.approx(opt.NPV(), rel=1e-12)
        assert mine.delta == pytest.approx(opt.delta(), rel=1e-12)
        assert mine.gamma == pytest.approx(opt.gamma(), rel=1e-12)
        assert mine.vega == pytest.approx(opt.vega(), rel=1e-12)
        assert mine.theta == pytest.approx(opt.theta(), rel=1e-10)


def test_limits() -> None:
    # T -> 0: intrinsic value.
    assert bsm(110, 100, 0.0, 0.03, 0.0, 0.2, CALL).price == 10.0
    assert bsm(110, 100, -1.0, 0.03, 0.0, 0.2, PUT).price == 0.0
    near = bsm(110, 100, 1e-10, 0.03, 0.0, 0.2, CALL)
    assert near.price == pytest.approx(10.0, abs=1e-6) and near.delta == pytest.approx(1.0)
    # sigma -> 0: discounted deterministic payoff, continuous with small sigma.
    s, k, t, r, q = 100.0, 95.0, 1.0, 0.03, 0.01
    det = s * math.exp(-q * t) - k * math.exp(-r * t)
    zero = bsm(s, k, t, r, q, 0.0, CALL)
    assert zero.price == pytest.approx(det) and zero.gamma == 0.0 and zero.vega == 0.0
    assert bsm(s, k, t, r, q, 1e-6, CALL).price == pytest.approx(det, abs=1e-9)
    assert zero.theta == pytest.approx(
        -(bsm(s, k, t + 1e-6, r, q, 0.0, CALL).price - bsm(s, k, t - 1e-6, r, q, 0.0, CALL).price)
        / 2e-6,
        rel=1e-6,
    )
    assert bsm(s, k, t, r, q, 0.0, PUT).price == 0.0
    with pytest.raises(ValueError, match="positive"):
        bsm(-1, 100, 1, 0, 0, 0.2, CALL)
