"""Shared fixtures. All tests are offline: HTTP is replayed from tests/fixtures/http."""

from __future__ import annotations

from pathlib import Path

import pytest

from minibook.config.settings import Settings, load_settings
from minibook.data.cache import RawStore
from minibook.data.replay import FixtureClient

ROOT = Path(__file__).resolve().parents[1]
HTTP_FIXTURES = ROOT / "tests" / "fixtures" / "http"


@pytest.fixture(scope="session")
def settings() -> Settings:
    return load_settings(ROOT / "config" / "settings.yaml")


@pytest.fixture
def client() -> FixtureClient:
    return FixtureClient(HTTP_FIXTURES)


@pytest.fixture
def store(tmp_path: Path) -> RawStore:
    return RawStore(tmp_path / "raw")
