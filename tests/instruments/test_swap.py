"""EUR IRS: schedules, par/zero-PV, payer/receiver symmetry, fixings, QuantLib cross-check."""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta

import numpy as np
import pytest
import QuantLib as ql

from minibook.instruments.base import PricingError
from minibook.instruments.swap import InterestRateSwap
from minibook.market.curves import ZeroCurve
from minibook.market.snapshot import MarketSnapshot
from minibook.market.svensson import SvenssonParams

TRADE = date(2026, 11, 2)


def swap(rate: float, pay_fixed: bool = True) -> InterestRateSwap:
    return InterestRateSwap.create("IRS", TRADE, 10_000_000, rate, pay_fixed)


def test_schedule_and_fixing_dates() -> None:
    s = swap(0.03)
    assert s.effective == date(2026, 11, 4)  # T+2 TARGET
    assert s.maturity == date(2031, 11, 4)
    assert len(s.fixed_periods) == 5 and len(s.float_coupons) == 10
    assert s.float_coupons[0].fixing_date == TRADE  # first fixing on the trade date
    assert s.float_coupons[3].period.end == date(2028, 11, 6)  # MF: 4 Nov 2028 is Saturday
    assert s.float_coupons[3].fixing_date == date(2028, 5, 2)


def test_par_swap_has_zero_pv(trade_snap: MarketSnapshot) -> None:
    par = swap(0.0).par_rate(trade_snap)
    assert 0.0 < par < 0.10
    assert abs(swap(par).pv(trade_snap)) < 1.0  # brief: |PV| < EUR 1


def test_payer_plus_receiver_is_zero(trade_snap: MarketSnapshot) -> None:
    for k in (0.01, 0.03, 0.05):
        assert swap(k, True).pv(trade_snap) + swap(k, False).pv(trade_snap) == pytest.approx(
            0.0, abs=1e-8
        )


def test_pv_decomposition_and_sign(trade_snap: MarketSnapshot) -> None:
    s = swap(0.03)
    assert s.pv(trade_snap) == pytest.approx(
        s.float_leg_pv(trade_snap) - s.fixed_leg_pv(trade_snap)
    )
    par = s.par_rate(trade_snap)
    assert swap(par - 0.001).pv(trade_snap) > 0  # payer gains when fixed rate is below par


def test_fixings_rules(trade_snap: MarketSnapshot) -> None:
    s = swap(0.03)
    first = s.float_coupons[0]
    projected = s.projected_rate(first, trade_snap)
    assert s.coupon_rate(first, trade_snap) == projected  # fixing today, none stored: proxy
    with_fix = trade_snap.with_fixings({("EURIBOR6M", TRADE): 0.0123})
    assert s.coupon_rate(first, with_fix) == 0.0123
    # A later valuation date without the stored past fixing must fail, never recompute.
    later = dataclasses.replace(trade_snap, as_of=date(2026, 11, 3))
    with pytest.raises(PricingError, match="never recomputed"):
        s.pv(later)
    later_fixed = later.with_fixings({("EURIBOR6M", TRADE): 0.0123})
    assert np.isfinite(s.pv(later_fixed))
    with pytest.raises(ValueError, match="after"):
        dataclasses.replace(trade_snap, fixings={("EURIBOR6M", date(2026, 11, 3)): 0.01})


def test_cashflows_and_paid_coupons(trade_snap: MarketSnapshot) -> None:
    s = swap(0.03)
    fixed_rate_fix = {("EURIBOR6M", TRADE): 0.02}
    first_pay = s.float_coupons[0].period.end  # 2027-05-04
    snap = dataclasses.replace(trade_snap, as_of=first_pay).with_fixings(fixed_rate_fix)
    flows = s.cashflows(first_pay - timedelta(days=1), first_pay, snap)
    assert [f.description for f in flows] == ["float coupon"]
    tau = (first_pay - s.effective).days / 360
    assert flows[0].amount == pytest.approx(10_000_000 * 0.02 * tau)
    assert s.cashflows(TRADE, first_pay - timedelta(days=1), snap) == []
    fixed_pay = s.fixed_periods[0].end  # 2027-11-04, also the 2nd float coupon's pay date
    second_fix = s.float_coupons[1].fixing_date
    snap2 = dataclasses.replace(trade_snap, as_of=fixed_pay).with_fixings(
        {**fixed_rate_fix, ("EURIBOR6M", second_fix): 0.025}
    )
    f2 = s.cashflows(fixed_pay - timedelta(days=1), fixed_pay, snap2)
    assert sorted(f.description for f in f2) == ["fixed coupon", "float coupon"]
    fixed_flow = next(f for f in f2 if f.description == "fixed coupon")
    assert fixed_flow.amount == pytest.approx(-300_000)  # payer pays 3% x 1y (30/360) x 10m
    with pytest.raises(PricingError, match="missing fixing"):
        s.cashflows(
            fixed_pay - timedelta(days=1),
            fixed_pay,
            dataclasses.replace(trade_snap, as_of=fixed_pay),
        )


def _node_curve(snap_curve_params: SvenssonParams, ref: date) -> tuple[ZeroCurve, list[date]]:
    """Real 2026-11-02 Svensson zeros at monthly dates (integer-day times, exact in QuantLib)."""
    dates = [ref + timedelta(days=round(30.4375 * m)) for m in range(1, 361)]
    times = [(d - ref).days / 365 for d in dates]
    zeros = [float(snap_curve_params.zero(t)) for t in times]
    return ZeroCurve("EUR", tuple(times), tuple(zeros)), dates


def test_quantlib_cross_check_like_for_like(
    market_store: object, trade_snap: MarketSnapshot
) -> None:
    """Same curve nodes, schedules, conventions and par-coupon forwarding in QuantLib."""
    from minibook.data.cache import RawStore  # noqa: PLC0415

    assert isinstance(market_store, RawStore)
    row = market_store.load_wide("ecb", "yield_curve").loc["2026-11-02"]
    curve, dates = _node_curve(SvenssonParams.from_ecb(row.to_dict()), TRADE)
    snap = dataclasses.replace(
        trade_snap, curves={**trade_snap.curves, "EUR": curve}, key_pillars=()
    )

    ql.IborCoupon.createAtParCoupons()
    today = ql.Date(TRADE.day, TRADE.month, TRADE.year)
    ql.Settings.instance().evaluationDate = today
    qd = [today] + [ql.Date(d.day, d.month, d.year) for d in dates]
    qz = [curve.zeros[0], *curve.zeros]
    ts = ql.ZeroCurve(qd, qz, ql.Actual365Fixed(), ql.TARGET(), ql.Linear(), ql.Continuous)
    h = ql.YieldTermStructureHandle(ts)
    index = ql.Euribor6M(h)
    m = swap(0.03)
    eff, mat = (ql.Date(d.day, d.month, d.year) for d in (m.effective, date(2031, 11, 4)))
    fixed_s = ql.Schedule(
        eff,
        mat,
        ql.Period("1Y"),
        ql.TARGET(),
        ql.ModifiedFollowing,
        ql.ModifiedFollowing,
        ql.DateGeneration.Backward,
        False,
    )
    float_s = ql.Schedule(
        eff,
        mat,
        ql.Period("6M"),
        ql.TARGET(),
        ql.ModifiedFollowing,
        ql.ModifiedFollowing,
        ql.DateGeneration.Backward,
        False,
    )
    for k in (0.025, 0.03):
        qswap = ql.VanillaSwap(
            ql.Swap.Payer,
            10_000_000,
            fixed_s,
            k,
            ql.Thirty360(ql.Thirty360.BondBasis),
            float_s,
            index,
            0.0,
            ql.Actual360(),
        )
        qswap.setPricingEngine(ql.DiscountingSwapEngine(h))
        mine = swap(k)
        assert mine.pv(snap) == pytest.approx(qswap.NPV(), abs=1e-4)
        assert mine.fixed_leg_pv(snap) == pytest.approx(abs(qswap.fixedLegNPV()), abs=1e-4)
        assert mine.float_leg_pv(snap) == pytest.approx(abs(qswap.floatingLegNPV()), abs=1e-4)
        assert mine.par_rate(snap) == pytest.approx(qswap.fairRate(), abs=1e-12)
