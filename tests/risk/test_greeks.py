"""M4 sensitivities: analytical Greeks vs central finite differences (rel 1e-4), DV01 on a
SYNTHETIC flat 2.5% curve vs the analytic annuity, key rates, theta, engine output."""

from __future__ import annotations

import dataclasses
import math
from datetime import date

import pytest

from minibook.config.settings import Settings
from minibook.dates.daycount import DayCount, year_fraction
from minibook.dates.tenor import Tenor
from minibook.instruments.base import Measure
from minibook.instruments.bsm import OptionType, bsm
from minibook.instruments.equity_option import EquityOption
from minibook.instruments.factory import fx_convention
from minibook.instruments.fx_forward import FxForward
from minibook.instruments.swap import InterestRateSwap
from minibook.market.curves import ZeroCurve
from minibook.market.snapshot import MarketSnapshot, Parallel
from minibook.risk.greeks import book_greeks, by_risk_factor, rate_sensitivities, theta

TRADE = date(2026, 11, 2)
KEYS = ("3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y")
Z_FLAT = 0.025  # brief: synthetic flat 2.5% curve


def flat_snapshot() -> MarketSnapshot:
    """SYNTHETIC market: flat 2.5% continuously compounded curves, round FX/spot/vol/q."""
    times = (*(Tenor.parse(k).years for k in KEYS), 30.0)
    curves = {
        c: ZeroCurve(c, times, (Z_FLAT,) * len(times), (*KEYS, "30Y"))
        for c in ("EUR", "USD", "JPY")
    }
    return MarketSnapshot(
        TRADE,
        curves,
        {"USD": 1.12, "JPY": 177.0},
        {"SX5E": 5000.0},
        {"SX5E": 0.18},
        {"SX5E": 0.03},
        KEYS,
    )


def row(rows: list, measure: Measure, factor: str) -> float:  # type: ignore[type-arg]
    return next(r.value for r in rows if r.measure == measure and r.risk_factor == factor)


# ------------------------------------------------------------------------------ options
@pytest.mark.parametrize(
    ("kind", "qty", "strike_pct"),
    [
        (OptionType.CALL, 50, 1.00),
        (OptionType.PUT, 20, 0.95),
        (OptionType.CALL, -30, 1.05),
        (OptionType.PUT, 40, 0.90),
    ],
)
def test_option_greeks_vs_central_differences(
    trade_snap: MarketSnapshot, settings: Settings, kind: OptionType, qty: float, strike_pct: float
) -> None:
    s0 = trade_snap.spots["SX5E"]
    o = EquityOption("O", "SX5E", kind, qty, 10.0, strike_pct * s0, date(2027, 2, 2))
    rows = o.analytic_greeks(trade_snap, settings.risk)

    def pv(spot: float = s0, vol: float | None = None, q: float | None = None) -> float:
        m = dataclasses.replace(
            trade_snap,
            spots={**trade_snap.spots, "SX5E": spot},
            vols={**trade_snap.vols, "SX5E": vol if vol is not None else trade_snap.vols["SX5E"]},
            div_yields={
                **trade_snap.div_yields,
                "SX5E": q if q is not None else trade_snap.div_yields["SX5E"],
            },
        )
        return o.pv(m)

    h, hv, hq = 1e-4 * s0, 1e-4, 1e-4
    v0, sig, q0 = pv(), trade_snap.vols["SX5E"], trade_snap.div_yields["SX5E"]
    fd_delta = 0.01 * s0 * (pv(s0 + h) - pv(s0 - h)) / (2 * h)
    fd_gamma = (0.01 * s0) ** 2 * (pv(s0 + h) - 2 * v0 + pv(s0 - h)) / h**2
    fd_vega = 0.01 * (pv(vol=sig + hv) - pv(vol=sig - hv)) / (2 * hv)
    fd_div = settings.risk.div_yield_bump * (pv(q=q0 + hq) - pv(q=q0 - hq)) / (2 * hq)
    assert row(rows, Measure.DELTA_1PCT, "EQ:SX5E") == pytest.approx(fd_delta, rel=1e-4)
    assert row(rows, Measure.GAMMA_1PCT, "EQ:SX5E") == pytest.approx(fd_gamma, rel=1e-4)
    assert row(rows, Measure.VEGA_1PT, "VOL:SX5E") == pytest.approx(fd_vega, rel=1e-4)
    assert row(rows, Measure.DIV_10BP, "DIV:SX5E") == pytest.approx(fd_div, rel=1e-4)
    # Signs: long call delta > 0, long put delta < 0; long options have positive gamma/vega.
    assert math.copysign(1, row(rows, Measure.DELTA_1PCT, "EQ:SX5E")) == kind.phi * (
        1 if qty > 0 else -1
    )
    assert (row(rows, Measure.VEGA_1PT, "VOL:SX5E") > 0) == (qty > 0)


def test_option_theta_revaluation_vs_analytic(settings: Settings) -> None:
    """Flat curve: 1-day revaluation theta equals the analytic theta at the half-day midpoint
    to second order (the instantaneous theta differs by ~0.3% for a 3M ATM option)."""
    snap = flat_snapshot()
    o = EquityOption("O", "SX5E", OptionType.CALL, 50, 10.0, 5000.0, date(2027, 2, 2))
    t = year_fraction(TRADE, o.expiry, DayCount.ACT_365F)
    mid = bsm(5000.0, 5000.0, t - 0.5 / 365, Z_FLAT, 0.03, 0.18, OptionType.CALL).theta
    assert theta(o, snap, 1) == pytest.approx(o.scale * mid / 365, rel=1e-4)
    after = dataclasses.replace(snap, as_of=o.expiry)
    assert o.analytic_greeks(after, settings.risk) == []


# ---------------------------------------------------------------------------- FX forwards
@pytest.mark.parametrize(("base", "quote", "n"), [("EUR", "USD", 5e6), ("USD", "JPY", -3e6)])
def test_fx_greeks_vs_central_differences(
    trade_snap: MarketSnapshot, settings: Settings, base: str, quote: str, n: float
) -> None:
    conv = fx_convention(settings, base + quote)
    delivery = conv.delivery_date(conv.spot_date(TRADE), Tenor.parse("6M"))
    # Strike away from the outright so that the strike term is not ~0.
    f = FxForward("F", base, quote, n, trade_snap.fx_rate(base, quote) * 0.97, delivery, conv)
    rows = f.analytic_greeks(trade_snap, settings.risk)
    for ccy in {base, quote} - {"EUR"}:
        x = trade_snap.fx[ccy]
        h = 1e-4 * x

        def pv(v: float, ccy: str = ccy) -> float:
            return f.pv(dataclasses.replace(trade_snap, fx={**trade_snap.fx, ccy: v}))

        fd_d = 0.01 * x * (pv(x + h) - pv(x - h)) / (2 * h)
        fd_g = (0.01 * x) ** 2 * (pv(x + h) - 2 * f.pv(trade_snap) + pv(x - h)) / h**2
        assert row(rows, Measure.DELTA_1PCT, f"FX:{ccy}") == pytest.approx(fd_d, rel=1e-4)
        assert row(rows, Measure.GAMMA_1PCT, f"FX:{ccy}") == pytest.approx(fd_g, rel=1e-4)
    # Long EUR vs USD gains when EUR/USD rises.
    if base == "EUR":
        assert row(rows, Measure.DELTA_1PCT, "FX:USD") > 0


# ----------------------------------------------------------------------------------- DV01
def test_dv01_flat_curve_vs_analytic_annuity(settings: Settings) -> None:
    snap = flat_snapshot()
    probe = InterestRateSwap.create("S", TRADE, 10_000_000, 0.0, True)
    swap = dataclasses.replace(probe, fixed_rate=probe.par_rate(snap))
    rows = rate_sensitivities(swap, snap, settings.risk.rate_bump)
    dv01 = row(rows, Measure.DV01, "PAR:EUR")

    # (1) Exact closed form. Single curve: the projected float leg telescopes to
    #     N (DF(t_start) - DF(t_end)), so PV(z) = N (e^{-z ts} - e^{-z te}) - N K sum tau e^{-z t}.
    def pv(z: float) -> float:
        ts = year_fraction(TRADE, swap.effective, DayCount.ACT_365F)
        te = year_fraction(TRADE, swap.maturity, DayCount.ACT_365F)
        fixed = sum(
            year_fraction(p.start, p.end, DayCount.THIRTY_360_BOND)
            * math.exp(-z * year_fraction(TRADE, p.end, DayCount.ACT_365F))
            for p in swap.fixed_periods
        )
        return swap.notional * (math.exp(-z * ts) - math.exp(-z * te) - swap.fixed_rate * fixed)

    assert dv01 == pytest.approx(pv(Z_FLAT + 1e-4) - pv(Z_FLAT), abs=1e-6)
    # (2) Annuity: for a par payer swap PV = A (par - K), so DV01 ~ A * d(par)/dz * 1bp; with
    #     annual coupons on a flat continuous curve par ~ e^z - 1, d(par)/dz = e^z. Residual
    #     (30/360 accruals, bump convexity) is below 1e-3 relative.
    annuity = swap.annuity(snap)
    assert dv01 == pytest.approx(annuity * math.exp(Z_FLAT) * 1e-4, rel=1e-3)
    assert dv01 > 0  # payer gains when rates rise


def test_key_rates_add_up_to_parallel(trade_snap: MarketSnapshot, settings: Settings) -> None:
    swap = InterestRateSwap.create("S", TRADE, 10_000_000, 0.03, True)
    snap = trade_snap.with_fixings({("EURIBOR6M", TRADE): 0.027})
    rows = rate_sensitivities(swap, snap, settings.risk.rate_bump)
    krs = [r for r in rows if r.measure == Measure.KR_DV01]
    assert {r.risk_factor for r in krs} <= {f"KR:EUR:{k}" for k in KEYS}
    # Key-rate tents sum to a parallel shift; residual = second-order cross terms (~1e-4).
    assert sum(r.value for r in krs) == pytest.approx(row(rows, Measure.DV01, "PAR:EUR"), rel=1e-3)
    assert all(not r.risk_factor.startswith(("PAR:USD", "PAR:JPY")) for r in rows)


def test_fx_forward_has_rate_risk_in_both_currencies(
    trade_snap: MarketSnapshot, settings: Settings
) -> None:
    conv = fx_convention(settings, "USDJPY")
    f = FxForward(
        "F",
        "USD",
        "JPY",
        -3e6,
        150.0,
        conv.delivery_date(conv.spot_date(TRADE), Tenor.parse("3M")),
        conv,
    )
    rows = rate_sensitivities(f, trade_snap, settings.risk.rate_bump)
    ccys = {r.risk_factor for r in rows if r.measure == Measure.DV01}
    assert ccys == {"PAR:USD", "PAR:JPY"}
    # CIP: F = S exp((r_JPY - r_USD) T). Higher USD rates lower F, so the short-USD forward
    # gains (DV01 > 0); higher JPY rates raise F and it loses.
    assert row(rows, Measure.DV01, "PAR:JPY") < 0 < row(rows, Measure.DV01, "PAR:USD")


# ---------------------------------------------------------------------------------- theta
def test_swap_theta_includes_paid_coupon(trade_snap: MarketSnapshot) -> None:
    swap = InterestRateSwap.create("S", TRADE, 10_000_000, 0.03, True)
    pay = swap.float_coupons[0].period.end
    day_before = dataclasses.replace(trade_snap, as_of=date.fromordinal(pay.toordinal() - 1))
    second_fix = swap.float_coupons[1].fixing_date  # 2027-04-30, before the day before
    m = day_before.with_fixings({("EURIBOR6M", TRADE): 0.027, ("EURIBOR6M", second_fix): 0.028})
    coupon = 10_000_000 * 0.027 * (pay - swap.effective).days / 360
    # Without the cashflow, PV would drop by the coupon; theta stays a small carry number.
    assert abs(theta(swap, m, 1)) < 0.05 * coupon
    assert swap.pv(m.roll(1)) - swap.pv(m) == pytest.approx(theta(swap, m, 1) - coupon)


# -------------------------------------------------------------------------------- engine
def test_book_greeks_table(trade_snap: MarketSnapshot, settings: Settings) -> None:
    s0 = trade_snap.spots["SX5E"]
    conv = fx_convention(settings, "EURUSD")
    instruments = [
        InterestRateSwap.create("IRS", TRADE, 10_000_000, 0.03, True),
        FxForward(
            "FXF",
            "EUR",
            "USD",
            5e6,
            1.13,
            conv.delivery_date(conv.spot_date(TRADE), Tenor.parse("6M")),
            conv,
        ),
        EquityOption("OPT", "SX5E", OptionType.CALL, 50, 10.0, s0, date(2027, 2, 2)),
    ]
    df = book_greeks(instruments, trade_snap, settings.risk)
    assert list(df.columns) == ["instrument_id", "measure", "risk_factor", "value"]
    assert set(df["measure"]) == {m.value for m in Measure}
    assert (df.groupby("instrument_id")["measure"].apply(lambda s: "theta_1d" in set(s))).all()
    totals = by_risk_factor(df)
    assert totals["value"].sum() == pytest.approx(df["value"].sum())
    dv01_eur = totals.loc[(totals.measure == "dv01") & (totals.risk_factor == "PAR:EUR"), "value"]
    assert float(dv01_eur.iloc[0]) == pytest.approx(
        df.loc[(df.measure == "dv01") & (df.risk_factor == "PAR:EUR"), "value"].sum()
    )
    # ADR-019: sensitivities are EUR amounts; no index level is part of the output.
    assert not any(str(round(s0, 2)) in str(v) for v in df.to_numpy().ravel())


def test_snapshot_roll() -> None:
    snap = flat_snapshot()
    rolled = snap.roll(3)
    assert rolled.as_of == date(2026, 11, 5) and rolled.curves["EUR"] is snap.curves["EUR"]
    assert snap.bump(Parallel("EUR"), 1e-4).roll(1).as_of == date(2026, 11, 3)


def test_theta_on_a_fixing_date_sets_todays_fixing(trade_snap: MarketSnapshot) -> None:
    swap = InterestRateSwap.create("S", TRADE, 10_000_000, 0.03, True)
    assert trade_snap.fixing("EURIBOR6M", TRADE) is None
    due = swap.fixings_due(trade_snap)
    assert list(due) == [("EURIBOR6M", TRADE)]
    # Theta works on the fixing date and equals the explicit computation with the fixing set.
    fixed = trade_snap.with_fixings(due)
    expected = swap.pv(fixed.roll(1)) - swap.pv(fixed)
    assert theta(swap, trade_snap, 1) == pytest.approx(expected)
    assert swap.fixings_due(fixed) == {}
