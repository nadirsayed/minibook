"""Store filled from recorded real fixtures (ECB, Treasury, FRED, MoF; 2026-10-26..11-06)
plus SYNTHETIC equity closes (no real index data is committed)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from minibook.config.settings import Settings
from minibook.data import ecb, fred, mof, treasury
from minibook.data.cache import RawStore
from minibook.data.replay import FixtureClient

START, END = date(2026, 10, 26), date(2026, 11, 6)
SYNTH_FETCH = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def synthetic_equities(store: RawStore, names: list[str], seed: int = 7) -> None:
    """SYNTHETIC: geometric random walk, 1% daily vol, weekdays 2026-05-01..2026-11-06."""
    days = pd.bdate_range("2026-05-01", "2026-11-06")
    rng = np.random.default_rng(seed)
    rows = []
    for name in names:
        px = 1000.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, len(days))))
        rows += [(d.date(), name, float(p)) for d, p in zip(days, px, strict=True)]
    store.upsert(
        "equities",
        "index_close",
        pd.DataFrame(rows, columns=["obs_date", "series", "value"]),
        SYNTH_FETCH,
        Path("synthetic"),
    )


@pytest.fixture
def market_store(tmp_path: Path, settings: Settings, client: FixtureClient) -> RawStore:
    store = RawStore(tmp_path / "raw")
    ecb.fetch_yield_curve(client, store, settings.ecb, START, END)
    ecb.fetch_fx(client, store, settings.ecb, START, END)
    treasury.fetch_par_curve(client, store, settings.treasury, START, END)
    fred.fetch_ust_cmt(client, store, settings.fred, START, END)
    mof.fetch_jgb(client, store, settings.mof)
    synthetic_equities(store, list(settings.equities.tickers))
    return store
