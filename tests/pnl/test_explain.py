"""P&L explain: convergence orders, actual P&L with cashflows, steps, flags, diagnostics.

Convergence tests use SYNTHETIC flat markets (risk.test_greeks.flat_snapshot) and the
same calendar date for t-1 and t (Δt = 0), to isolate the market move under test.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pytest

from minibook.config.settings import PnlSettings, Settings
from minibook.data.fixings import FixingStore
from minibook.fixing_service import due_fixing_records, record_due_fixings
from minibook.instruments.bsm import OptionType
from minibook.instruments.equity_option import EquityOption
from minibook.instruments.swap import InterestRateSwap
from minibook.market.snapshot import EquitySpot, MarketSnapshot, Parallel, Vol
from minibook.pnl.explain import Step, explain, market_moves
from tests.risk.test_greeks import TRADE, flat_snapshot

# 10% out-of-the-money call: vanna and volga are material (both ~0 at the money, where the
# mixed-move quadratic term would vanish and the order test would be meaningless).
OPTION = EquityOption("O", "SX5E", OptionType.CALL, 50, 10.0, 5500.0, date(2027, 2, 2))
# Small moves, so that higher-order terms do not bend the log-log slope.
SIZES = [0.00125, 0.0025, 0.005, 0.01, 0.02]


def unexplained(
    prev: MarketSnapshot, curr: MarketSnapshot, settings: Settings, inst: object = OPTION
) -> tuple[float, float]:
    r = explain([inst], prev, curr, settings.risk, settings.pnl)  # type: ignore[list-item]
    row = r.per_instrument.iloc[0]
    return float(row["unexplained"]), float(row["residual_after_2nd"])


def order(residuals: list[float], sizes: list[float] = SIZES) -> float:
    """Log-log slope of |residual| against move size."""
    return float(np.polyfit(np.log(sizes), np.log(np.abs(residuals)), 1)[0])


def test_single_factor_spot_move_has_cubic_residual(settings: Settings) -> None:
    snap = flat_snapshot()
    res = [
        unexplained(snap, snap.bump(EquitySpot("SX5E"), float(np.log1p(u))), settings)[0]
        for u in SIZES
    ]
    assert order(res) == pytest.approx(3.0, abs=0.1)  # brief: cubic residual


def test_mixed_moves_have_quadratic_residual(settings: Settings) -> None:
    snap = flat_snapshot()
    res, after = [], []
    for h in SIZES:  # spot +h and vol +h together (scaled jointly)
        curr = snap.apply({EquitySpot("SX5E"): float(np.log1p(h)), Vol("SX5E"): h})
        u, a = unexplained(snap, curr, settings)
        res.append(u)
        after.append(a)
    assert order(res) == pytest.approx(2.0, abs=0.1)  # brief: omitted cross terms
    # The vanna + volga diagnostic captures the omitted second-order terms: what remains is
    # third order and below 1% of the unexplained P&L at every size. (It is not monotone in
    # the size: third-order terms of opposite sign cancel near a 1% move.)
    assert all(abs(a) < 0.01 * abs(r) for a, r in zip(after, res, strict=True))


def test_rates_move_residual_is_second_order(settings: Settings) -> None:
    snap = flat_snapshot().with_fixings({("EURIBOR6M", TRADE): 0.025})
    swap = InterestRateSwap.create("S", TRADE, 10_000_000, 0.03, True)
    # The brief's DV01 is a one-sided +1bp difference, so for a parallel move of D bp the
    # residual is ~ 1/2 PV'' D (D - 1bp): zero at exactly 1bp. Use moves well above 1bp.
    sizes_bp = [5.0, 10.0, 20.0, 40.0]
    res = [
        unexplained(snap, snap.bump(Parallel("EUR"), d * 1e-4), settings, swap)[0] for d in sizes_bp
    ]
    assert order(res, sizes_bp) == pytest.approx(2.0, abs=0.1)


def test_no_move_one_day_is_theta(settings: Settings) -> None:
    snap = flat_snapshot()
    r = explain([OPTION], snap, snap.roll(1), settings.risk, settings.pnl)
    row = r.per_instrument.iloc[0]
    assert row["explained"] == pytest.approx(row["actual"])  # theta is a 1-day revaluation
    assert set(r.components["component"]) == {"theta", "eq_delta", "eq_gamma", "vega", "rates"}


def test_actual_includes_cashflows_and_steps_add_up(
    trade_snap: MarketSnapshot, settings: Settings
) -> None:
    swap = InterestRateSwap.create("S", TRADE, 10_000_000, 0.03, True)
    pay = swap.float_coupons[0].period.end
    fix = {("EURIBOR6M", TRADE): 0.027, ("EURIBOR6M", swap.float_coupons[1].fixing_date): 0.028}
    prev = dataclasses.replace(trade_snap, as_of=date.fromordinal(pay.toordinal() - 1))
    prev = prev.with_fixings(fix)
    curr = dataclasses.replace(trade_snap, as_of=pay).with_fixings(fix)
    r = explain([swap], prev, curr, settings.risk, settings.pnl)
    row = r.per_instrument.iloc[0]
    coupon = 10_000_000 * 0.027 * (pay - swap.effective).days / 360
    assert row["cashflows"] == pytest.approx(coupon)
    assert row["actual"] == pytest.approx(row["pv_curr"] - row["pv_prev"] + coupon)
    assert abs(row["unexplained"]) < 1.0  # same market: only time passes, theta covers it
    steps = r.steps.set_index("step")["value"]
    assert steps.sum() == pytest.approx(row["actual"], abs=1e-6)
    assert list(steps.index) == [s.value for s in Step]


def test_real_rates_window_additivity(
    trade_snap: MarketSnapshot, market_store: object, settings: Settings
) -> None:
    from minibook.data.cache import RawStore  # noqa: PLC0415
    from minibook.market.builder import SnapshotBuilder  # noqa: PLC0415
    from tests.conftest import PLACEHOLDER_DIV_YIELDS_TESTS_ONLY  # noqa: PLC0415

    assert isinstance(market_store, RawStore)
    b = SnapshotBuilder(market_store, settings)
    fix = {("EURIBOR6M", TRADE): 0.027}
    prev = b.build(date(2026, 11, 4), PLACEHOLDER_DIV_YIELDS_TESTS_ONLY).with_fixings(fix)
    curr = b.build(date(2026, 11, 5), PLACEHOLDER_DIV_YIELDS_TESTS_ONLY).with_fixings(fix)
    s0 = trade_snap.spots["SX5E"]
    insts = [
        InterestRateSwap.create("IRS", TRADE, 10_000_000, 0.03, True),
        dataclasses.replace(OPTION, strike=s0),
    ]
    r = explain(insts, prev, curr, settings.risk, settings.pnl)
    per = r.per_instrument
    assert r.book["unexplained"] == pytest.approx(per["unexplained"].sum())
    assert r.book["actual"] == pytest.approx(r.book["explained"] + r.book["unexplained"])
    assert r.components.groupby("instrument_id")["value"].sum().to_dict() == pytest.approx(
        per.set_index("instrument_id")["explained"].to_dict()
    )
    # Recorded real rates move: the swap's explain is accurate to well under EUR 100.
    assert abs(float(per.loc[per.instrument_id == "IRS", "unexplained"].iloc[0])) < 100.0
    assert r.moves.dt_days == 1


def test_flag_threshold_and_note(settings: Settings) -> None:
    snap = flat_snapshot()
    curr = snap.apply({EquitySpot("SX5E"): float(np.log1p(0.04)), Vol("SX5E"): 0.04})
    strict = PnlSettings(unexplained_rel_threshold=0.0, unexplained_abs_threshold_eur=1.0)
    r = explain([OPTION], snap, curr, settings.risk, strict)
    row = r.per_instrument.iloc[0]
    assert bool(row["flagged"]) and row["threshold"] == 1.0
    assert "omitted vanna+volga" in row["note"] and "largest revaluation step" in row["note"]
    loose = PnlSettings(unexplained_rel_threshold=1.0, unexplained_abs_threshold_eur=1e9)
    row2 = explain([OPTION], snap, curr, settings.risk, loose).per_instrument.iloc[0]
    assert not bool(row2["flagged"]) and row2["note"] == ""


def test_market_moves_and_order() -> None:
    snap = flat_snapshot()
    m = market_moves(snap, snap.bump(Parallel("USD"), 2e-4).roll(3))
    assert m.dt_days == 3
    assert m.rate_changes_bp["KR:USD:5Y"] == pytest.approx(2.0)
    assert m.rate_changes_bp["KR:EUR:5Y"] == 0.0
    with pytest.raises(ValueError, match="before"):
        market_moves(snap.roll(1), snap)


def test_fixing_service(tmp_path: Path, trade_snap: MarketSnapshot) -> None:
    swap = InterestRateSwap.create("S", TRADE, 10_000_000, 0.03, True)
    at = datetime(2026, 11, 12, tzinfo=UTC)
    recs = due_fixing_records([swap, OPTION], trade_snap, at)
    assert [(r.index, r.fixing_date) for r in recs] == [("EURIBOR6M", TRADE)]
    assert recs[0].rate == swap.projected_rate(swap.float_coupons[0], trade_snap)
    store = FixingStore(tmp_path)
    m = record_due_fixings([swap], trade_snap, store, at)
    assert m.fixing("EURIBOR6M", TRADE) == recs[0].rate
    again = record_due_fixings([swap], m, store, at)  # idempotent: same value, no error
    assert again.fixings == m.fixings
    assert len(store.load("EURIBOR6M")) == 1
    later = m.roll(1)
    assert record_due_fixings([swap], later, store, at) is later  # nothing due that day
