from __future__ import annotations

import numpy as np
import pytest

from minibook.config.settings import Settings
from minibook.data.cache import RawStore
from minibook.dates.tenor import Tenor
from minibook.market.bootstrap import (
    bootstrap_par_curve,
    coupon_times,
    money_market_yield,
    par_yield,
)
from minibook.market.svensson import SvenssonParams, svensson_curve, validation_errors_bp


def test_svensson_rebuild_matches_ecb_on_every_fixture_day(
    market_store: RawStore, settings: Settings
) -> None:
    """Brief: rebuilt SR_1Y/5Y/10Y match the ECB published spot rates to <= 0.1 bp."""
    yc = market_store.load_wide("ecb", "yield_curve")
    assert len(yc) == 10
    for _, row in yc.iterrows():
        params = SvenssonParams.from_ecb(row.to_dict())
        errs = validation_errors_bp(params, {k: row[k] for k in ("SR_1Y", "SR_5Y", "SR_10Y")})
        assert max(abs(e) for e in errs.values()) <= settings.market.svensson_tolerance_bp


def test_percent_to_decimal() -> None:
    # SYNTHETIC: b1 = b2 = b3 = 0 gives a flat curve at b0 percent.
    p = SvenssonParams(2.5, 0.0, 0.0, 0.0, 1.0, 10.0)
    assert float(p.zero(7.0)) == pytest.approx(0.025)
    assert float(p.zero_pct(7.0)) == pytest.approx(2.5)


def test_pillar_curve_close_to_svensson(market_store: RawStore, settings: Settings) -> None:
    row = market_store.load_wide("ecb", "yield_curve").loc["2026-11-02"]
    params = SvenssonParams.from_ecb(row.to_dict())
    curve = svensson_curve(params, list(settings.market.eur_pillars))
    for lab, t, z in zip(curve.labels, curve.times, curve.zeros, strict=True):
        assert z == float(params.zero(t)), lab
    grid = np.linspace(1 / 12, 10.5, 2000)
    err_bp = np.max(np.abs(np.asarray(curve.zero(grid)) - params.zero(grid))) * 1e4
    assert err_bp < 0.6  # ADR-009: 0.54 bp worst case over 2023-06..2026-11


@pytest.mark.parametrize("z", [-0.005, 0.0, 0.025, 0.07])
def test_bootstrap_recovers_flat_curve(z: float) -> None:
    # SYNTHETIC: quotes generated from a flat continuously compounded curve.
    mm = {"1M": 1 / 12, "3M": 0.25, "6M": 0.5}
    quotes = {k: (np.exp(z * t) - 1.0) / t for k, t in mm.items()}
    for k in ("1Y", "2Y", "3Y", "5Y", "7Y", "10Y"):
        quotes[k] = 2.0 * (np.exp(z / 2.0) - 1.0)  # semi-annual par yield on a flat curve
    curve = bootstrap_par_curve("USD", quotes, list(mm), 2)
    np.testing.assert_allclose(curve.zeros, z, atol=1e-13)


@pytest.mark.parametrize(
    ("src", "ds", "ccy", "mm"),
    [
        ("fred", "ust_cmt", "USD", ["1M", "3M", "6M"]),
        ("mof", "jgb_cm", "JPY", []),
    ],
)
def test_bootstrap_reprices_real_quotes(
    market_store: RawStore, src: str, ds: str, ccy: str, mm: list[str]
) -> None:
    """Every recorded input quote on 2026-11-02 reprices exactly (<= 1e-8 bp)."""
    row = market_store.load_wide(src, ds).loc["2026-11-02"].dropna()
    quotes = {k: v / 100 for k, v in row.items() if Tenor.parse(str(k)).years <= 10}
    curve = bootstrap_par_curve(ccy, quotes, mm, 2)
    assert curve.df(0.0) == 1.0
    for lab, t in zip(curve.labels, curve.times, strict=True):
        model = money_market_yield(curve, t) if lab in mm else par_yield(curve, t, 2)
        assert abs(model - quotes[lab]) * 1e4 < 1e-8, lab


def test_coupon_times_requires_regular_maturity() -> None:
    np.testing.assert_allclose(coupon_times(1.5, 2), [0.5, 1.0, 1.5])
    with pytest.raises(ValueError, match="not a multiple"):
        coupon_times(1.25, 2)
