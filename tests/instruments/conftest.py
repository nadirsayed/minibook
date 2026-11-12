from __future__ import annotations

from datetime import date

import pytest

from minibook.config.settings import Settings
from minibook.data.cache import RawStore
from minibook.market.builder import SnapshotBuilder
from minibook.market.snapshot import MarketSnapshot
from tests.conftest import PLACEHOLDER_DIV_YIELDS_TESTS_ONLY

TRADE = date(2026, 11, 2)


@pytest.fixture
def trade_snap(market_store: RawStore, settings: Settings) -> MarketSnapshot:
    """Trade-date snapshot: real rates/FX (recorded), SYNTHETIC equities, PLACEHOLDER q."""
    return SnapshotBuilder(market_store, settings).build(TRADE, PLACEHOLDER_DIV_YIELDS_TESTS_ONLY)
