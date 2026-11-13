"""Smoke tests for the CLI scaffold (M0)."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner

from minibook import __version__, cli
from minibook.cli import app
from minibook.data.replay import FixtureClient
from tests.conftest import HTTP_FIXTURES, ROOT

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("init-book", "fetch", "run", "backfill"):
        assert cmd in result.stdout


def test_bad_date_rejected() -> None:
    result = runner.invoke(app, ["run", "--date", "2026-13-01"])
    assert result.exit_code != 0


def _settings_with_raw_dir(tmp_path: Path) -> Path:
    raw = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())
    raw["data"]["raw_dir"] = str(tmp_path / "raw")
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump(raw))
    return path


def test_fetch_all_sources_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def synthetic_history(ticker: str, start: date, end: date) -> pd.DataFrame:
        # SYNTHETIC equity bars (no real index data is committed).
        idx = pd.DatetimeIndex([pd.Timestamp("2026-11-02", tz="Europe/Berlin")])
        return pd.DataFrame({"Close": [100.0]}, index=idx)

    monkeypatch.setattr(cli, "make_client", lambda s: FixtureClient(HTTP_FIXTURES))
    monkeypatch.setattr(cli, "EQUITY_HISTORY", synthetic_history)
    path = _settings_with_raw_dir(tmp_path)
    result = runner.invoke(
        app, ["fetch", "--start", "2026-10-26", "--end", "2026-11-06", "--settings", str(path)]
    )
    assert result.exit_code == 0, result.output
    for parquet in (
        "ecb/yield_curve",
        "ecb/fx",
        "ecb/estr",
        "ecb/rating_curves",
        "treasury/par_curve",
        "fred/ust_cmt",
        "mof/jgb_cm",
        "equities/index_close",
    ):
        assert (tmp_path / "raw" / f"{parquet}.parquet").exists()


def test_fetch_reports_failed_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(ticker: str, start: date, end: date) -> pd.DataFrame:
        raise ConnectionError("synthetic outage")

    monkeypatch.setattr(cli, "make_client", lambda s: FixtureClient(HTTP_FIXTURES))
    monkeypatch.setattr(cli, "EQUITY_HISTORY", broken)
    path = _settings_with_raw_dir(tmp_path)
    result = runner.invoke(
        app, ["fetch", "--start", "2026-10-26", "--end", "2026-11-06", "--settings", str(path)]
    )
    assert result.exit_code == 1


def test_run_reports_stale_market_data_cleanly(tmp_path: Path) -> None:
    """An empty market-data store: a clean error and exit status 1, not a traceback."""
    path = _settings_with_raw_dir(tmp_path)
    result = runner.invoke(app, ["run", "--date", "2026-12-01", "--settings", str(path)])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
