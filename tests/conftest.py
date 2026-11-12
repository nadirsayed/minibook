"""Shared fixtures. All tests are offline: HTTP is replayed from tests/fixtures/http."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from minibook.config.settings import Settings, load_settings
from minibook.data import ecb, fred, mof, treasury
from minibook.data.cache import RawStore
from minibook.data.replay import FixtureClient

ROOT = Path(__file__).resolve().parents[1]
HTTP_FIXTURES = ROOT / "tests" / "fixtures" / "http"

# Window of the recorded real fixtures (scripts/record_fixtures.py).
START, END = date(2026, 10, 26), date(2026, 11, 6)
SYNTH_FETCH = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)

# ---------------------------------------------------------------------------------------
# PLACEHOLDER dividend yields, FOR TESTS ONLY. NOT market data: the real values are
# provided by the owner in config/book.yaml. Never used by a report (CLAUDE.md, item 11).
PLACEHOLDER_DIV_YIELDS_TESTS_ONLY: dict[str, float] = {
    "SX5E": 0.03,
    "DAX": 0.0,
    "CAC40": 0.03,
    "FTSEMIB": 0.04,
}


@pytest.fixture(scope="session")
def settings() -> Settings:
    return load_settings(ROOT / "config" / "settings.yaml")


@pytest.fixture
def client() -> FixtureClient:
    return FixtureClient(HTTP_FIXTURES)


@pytest.fixture
def store(tmp_path: Path) -> RawStore:
    return RawStore(tmp_path / "raw")


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
    """Recorded real ECB/Treasury/FRED/MoF data plus SYNTHETIC equity closes."""
    store = RawStore(tmp_path / "raw")
    ecb.fetch_yield_curve(client, store, settings.ecb, START, END)
    ecb.fetch_fx(client, store, settings.ecb, START, END)
    treasury.fetch_par_curve(client, store, settings.treasury, START, END)
    fred.fetch_ust_cmt(client, store, settings.fred, START, END)
    mof.fetch_jgb(client, store, settings.mof)
    synthetic_equities(store, list(settings.equities.tickers))
    return store
