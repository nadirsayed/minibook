from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from minibook.config.settings import Settings
from minibook.data.cache import RawStore
from minibook.market.builder import MarketDataError, SnapshotBuilder, StaleDataError

NO_DIVS = {"SX5E": 0.0, "DAX": 0.0, "CAC40": 0.0, "FTSEMIB": 0.0}  # SYNTHETIC


def test_build_trade_date_without_fills(market_store: RawStore, settings: Settings) -> None:
    snap = SnapshotBuilder(market_store, settings).build(date(2026, 11, 2), NO_DIVS)
    assert snap.fills == ()
    # Recorded ECB reference rates for 2026-11-02 (fixture 6cbd17c2819123a3 / test_sources).
    assert snap.fx["USD"] == 1.1216 and snap.fx["JPY"] == 177.1
    for ccy in ("EUR", "USD", "JPY"):
        c = snap.curve(ccy)
        assert set(settings.market.key_pillars) <= set(c.labels)
        assert c.df(0.0) == 1.0
    # JPY has no quote below 1Y: 3M and 6M pillars are flat-extrapolated (ADR-008).
    jpy = snap.curve("JPY")
    assert jpy.zero(0.25) == jpy.zero(1.0)
    assert all(0.05 < v < 0.5 for v in snap.vols.values())
    assert set(snap.data_timestamps) == {
        "ecb/yield_curve",
        "fred/ust_cmt",
        "mof/jgb_cm",
        "ecb/fx",
        "equities/index_close",
    }


def test_japanese_holiday_is_forward_filled_and_logged(
    market_store: RawStore, settings: Settings
) -> None:
    snap = SnapshotBuilder(market_store, settings).build(date(2026, 11, 3), NO_DIVS)
    fills = [f for f in snap.fills if f.dataset == "mof/jgb_cm"]
    assert len(fills) == len(settings.market.jpy.tenors)
    f = fills[0]
    assert (f.obs_date, f.age_days) == (date(2026, 11, 2), 1)
    assert "JP holiday" in f.reason
    assert {f.dataset for f in snap.fills} == {"mof/jgb_cm"}


def test_no_look_ahead(market_store: RawStore, settings: Settings) -> None:
    b = SnapshotBuilder(market_store, settings)
    early = b.build(date(2026, 10, 30), NO_DIVS)
    assert early.fx["USD"] != b.build(date(2026, 11, 2), NO_DIVS).fx["USD"]
    # Equity vol uses only closes on or before as_of.
    closes = market_store.load_wide("equities", "index_close", as_of=date(2026, 10, 30))
    assert early.spots["SX5E"] == closes["SX5E"].iloc[-1]


def test_stale_data_fails_explicitly(market_store: RawStore, settings: Settings) -> None:
    # 2026-11-06 is the last recorded day; 2026-11-10 is 4 calendar days later.
    with pytest.raises(StaleDataError, match="4 days old"):
        SnapshotBuilder(market_store, settings).build(date(2026, 11, 10), NO_DIVS)


def test_closure_exemption_is_opt_in(tmp_path: Path, settings: Settings) -> None:
    # SYNTHETIC JGB rows around Golden Week 2026: last JP business day before is Fri 1 May,
    # 2-6 May are weekend/holidays, so on Wed 6 May the observation is 5 days old.
    store = RawStore(tmp_path / "raw")
    rows = [(date(2026, 5, 1), t, 1.0) for t in settings.market.jpy.tenors]
    store.upsert(
        "mof",
        "jgb_cm",
        pd.DataFrame(rows, columns=["obs_date", "series", "value"]),
        datetime(2026, 5, 2, tzinfo=UTC),
        Path("synthetic"),
    )
    tenors = list(settings.market.jpy.tenors)
    strict = SnapshotBuilder(store, settings)
    with pytest.raises(StaleDataError):
        strict._pick("mof", "jgb_cm", tenors, date(2026, 5, 6))
    relaxed = settings.model_copy(
        update={"market": settings.market.model_copy(update={"market_closure_exempt": True})}
    )
    picked = SnapshotBuilder(store, relaxed)._pick("mof", "jgb_cm", tenors, date(2026, 5, 6))
    assert picked.fills[0].age_days == 5 and "closure exemption" in picked.fills[0].reason
    # Not exempt when a JP business day was skipped (Thu 7 May is a business day).
    with pytest.raises(StaleDataError):
        SnapshotBuilder(store, relaxed)._pick("mof", "jgb_cm", tenors, date(2026, 5, 8))


def test_svensson_validation_failure(market_store: RawStore, settings: Settings) -> None:
    row = pd.DataFrame(
        [(date(2026, 11, 2), "SR_5Y", 9.99)], columns=["obs_date", "series", "value"]
    )  # SYNTHETIC corrupt value
    market_store.upsert(
        "ecb", "yield_curve", row, datetime(2026, 11, 8, tzinfo=UTC), Path("synthetic")
    )
    with pytest.raises(MarketDataError, match="Svensson rebuild off"):
        SnapshotBuilder(market_store, settings).build(date(2026, 11, 2), NO_DIVS)


def test_missing_series_and_non_target_day(market_store: RawStore, settings: Settings) -> None:
    b = SnapshotBuilder(market_store, settings)
    with pytest.raises(MarketDataError, match="no observation"):
        b.build(date(2026, 11, 2), NO_DIVS, underlyings=["NIKKEI"])
    with pytest.raises(ValueError, match="not a TARGET business day"):
        b.build(date(2026, 11, 1), NO_DIVS)
