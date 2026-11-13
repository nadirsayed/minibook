"""M8 end to end on recorded real rates/FX (2026-10-26..11-06) and SYNTHETIC equities, with a
temporary frozen book whose dividend assumptions are PLACEHOLDERS (tests only). VaR uses 5
scenarios here, because the recorded window is short; the production setting is 500."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest
import yaml
from pypdf import PdfReader
from typer.testing import CliRunner

from minibook import cli, pipeline
from minibook.config.settings import Settings
from minibook.daily import daily, due_dates, in_window, is_ready
from minibook.data.cache import RawStore
from minibook.data.fixings import FixingStore
from minibook.data.replay import FixtureClient
from minibook.fetching import window_start
from minibook.init_book import init_book
from minibook.market.builder import SnapshotBuilder
from minibook.pipeline import OUTPUT_FILES, PipelineError, run
from minibook.reporting.guard import find_levels
from tests.conftest import HTTP_FIXTURES, ROOT

TRADE = date(2026, 11, 2)
PLACEHOLDER = (  # PLACEHOLDER dividend assumptions, FOR TESTS ONLY (not market data)
    "    SX5E:\n      value: 0.03\n      source: test placeholder\n      date: 2026-11-02\n"
)


@pytest.fixture
def env(tmp_path: Path, market_store: RawStore, settings: Settings) -> tuple[Settings, Path]:
    s = settings.model_copy(
        update={
            "data": settings.data.model_copy(
                update={"raw_dir": market_store.root, "fixings_dir": tmp_path / "fixings"}
            ),
            "pipeline": settings.pipeline.model_copy(
                update={"output_dir": tmp_path / "output", "reports_dir": tmp_path / "reports"}
            ),
            "var": settings.var.model_copy(update={"n_scenarios": 5, "bootstrap_resamples": 50}),
        }
    )
    book = tmp_path / "book.yaml"
    text = (ROOT / "tests" / "fixtures" / "book_template.yaml").read_text()
    for u in ("SX5E", "CAC40", "FTSEMIB"):
        text = text.replace(f"    {u}:\n", PLACEHOLDER.replace("SX5E", u), 1)
    book.write_text(text)
    init_book(
        book,
        s,
        SnapshotBuilder(market_store, s).build,
        FixingStore(tmp_path / "fixings"),
        TRADE,
        lambda: datetime(2026, 11, 3, tzinfo=UTC),
    )
    return s, book


def test_run_produces_every_output(env: tuple[Settings, Path], market_store: RawStore) -> None:
    s, book = env
    res = run(date(2026, 11, 4), s, book, clock=lambda: datetime(2026, 11, 5, 12, tzinfo=UTC))
    assert sorted(p.name for p in res.out_dir.iterdir()) == sorted(OUTPUT_FILES)
    assert (s.pipeline.reports_dir / "2026-11-04.pdf").read_bytes() == res.report.read_bytes()
    index = (s.pipeline.reports_dir / "README.md").read_text()
    assert "| [2026-11-04](2026-11-04.pdf) |" in index and "VaR 99%" in index
    assert 1 <= len(PdfReader(str(res.report)).pages) <= 5
    pnl = pd.read_csv(res.out_dir / "pnl_explain.csv")
    assert {"actual", "explained", "unexplained", "flagged", "theta", "rates"} <= set(pnl.columns)
    var = json.loads((res.out_dir / "var_es.json").read_text())
    assert var["n_scenarios"] == 5 and var["var_ci"] is not None
    assert var["artefact_checked"] and var["scenario_flags"] == []  # recorded ECB data
    assert var["var_ex_flagged"] is None
    meta = json.loads((res.out_dir / "run_metadata.json").read_text())
    assert meta["as_of"] == "2026-11-04" and meta["git_sha"] and meta["config_hash"]
    assert meta["backtest_status"] == "insufficient observations (N = 0)"
    assert meta["retrospective_fetch"] is True  # fixtures recorded on 2026-11-12
    # Index-level rule: no level of the SYNTHETIC equity history in any text output.
    levels = market_store.load_wide("equities", "index_close").to_numpy().ravel().tolist()
    texts = [(res.out_dir / f).read_text() for f in OUTPUT_FILES if f != "report.pdf"]
    assert find_levels(texts, levels) == []


def test_run_is_idempotent_and_builds_history(env: tuple[Settings, Path]) -> None:
    s, book = env
    clock = lambda: datetime(2026, 11, 7, 12, tzinfo=UTC)  # noqa: E731
    first = run(date(2026, 11, 5), s, book, clock=clock)
    before = {f: (first.out_dir / f).read_bytes() for f in OUTPUT_FILES if f != "run_metadata.json"}
    again = run(date(2026, 11, 5), s, book, clock=clock)
    assert {f: (again.out_dir / f).read_bytes() for f in before} == before
    nxt = run(date(2026, 11, 6), s, book, clock=clock)
    meta = json.loads((nxt.out_dir / "run_metadata.json").read_text())
    assert meta["backtest_status"] == "insufficient observations (N = 1)"  # 6 Nov vs VaR 5 Nov


def test_run_refuses_bad_dates_and_missing_assumptions(
    env: tuple[Settings, Path], tmp_path: Path
) -> None:
    s, book = env
    with pytest.raises(PipelineError, match="TARGET"):
        run(date(2026, 11, 7), s, book)
    with pytest.raises(PipelineError, match="after the trade date"):
        run(TRADE, s, book)
    text = book.read_text().replace(PLACEHOLDER.replace("SX5E", "FTSEMIB"), "    FTSEMIB:\n")
    no_div = tmp_path / "nodiv" / "book.yaml"
    no_div.parent.mkdir()
    no_div.write_text(text)
    shutil.copy(book.with_name("book.private.yaml"), no_div.with_name("book.private.yaml"))
    with pytest.raises(PipelineError, match="FTSEMIB"):
        run(date(2026, 11, 4), s, no_div)


def test_daily_catches_up_then_waits_for_the_ecb(env: tuple[Settings, Path]) -> None:
    s, book = env
    client = FixtureClient(HTTP_FIXTURES)  # incremental URLs are not recorded: fetch fails,
    history = lambda t, a, b: pd.DataFrame({"Close": []})  # noqa: E731  # the store is used
    # Mon 9 Nov 2026 13:30 CET: due 3-6 Nov, ECB curves stored up to 6 Nov -> all produced.
    mon = lambda: datetime(2026, 11, 9, 12, 30, tzinfo=UTC)  # noqa: E731
    done, ready = daily(s, book, client, history, clock=mon)
    assert done == [date(2026, 11, d) for d in (3, 4, 5, 6)] and ready
    assert daily(s, book, client, history, clock=mon) == ([], True)  # nothing left
    # Tue 10 Nov: 9 Nov is due, but no ECB curve for it -> wait (exit code 75 in the CLI).
    tue = lambda: datetime(2026, 11, 10, 12, 30, tzinfo=UTC)  # noqa: E731
    assert daily(s, book, client, history, clock=tue) == ([], False)
    # Outside the window, or on a non-TARGET day: nothing to do.
    assert daily(s, book, client, history, clock=lambda: datetime(2026, 11, 10, 6, tzinfo=UTC)) == (
        [],
        True,
    )
    assert daily(
        s, book, client, history, clock=lambda: datetime(2026, 12, 25, 12, tzinfo=UTC)
    ) == ([], True)


def test_schedule_helpers(settings: Settings, market_store: RawStore, tmp_path: Path) -> None:
    # 12:30 UTC is 13:30 CET in November; 11:30 UTC is 13:30 CEST in July.
    assert in_window(datetime(2026, 11, 9, 12, 30, tzinfo=UTC), settings)
    assert not in_window(datetime(2026, 11, 9, 11, 30, tzinfo=UTC), settings)
    assert in_window(datetime(2026, 7, 6, 11, 30, tzinfo=UTC), settings)
    # The final :05 UTC trigger must be admitted in either daylight-saving season.
    assert in_window(datetime(2026, 11, 9, 17, 5, tzinfo=UTC), settings)
    assert in_window(datetime(2026, 7, 6, 16, 5, tzinfo=UTC), settings)
    assert not in_window(datetime(2026, 7, 6, 17, 5, tzinfo=UTC), settings)
    assert due_dates(TRADE, date(2026, 11, 5), tmp_path) == [date(2026, 11, 3), date(2026, 11, 4)]
    (tmp_path / "2026-11-03").mkdir()
    (tmp_path / "2026-11-03" / "report.pdf").write_bytes(b"%PDF")
    assert due_dates(TRADE, date(2026, 11, 5), tmp_path) == [date(2026, 11, 4)]
    assert due_dates(TRADE, TRADE, tmp_path) == []
    # 31 Dec skipped by the ECB: ready once a later curve exists (ADR-007).
    assert is_ready(market_store, date(2026, 11, 6))
    assert not is_ready(market_store, date(2026, 11, 9))
    empty = RawStore(tmp_path / "empty")
    assert window_start(empty, "ecb", "fx", settings) == settings.data.history_start
    assert window_start(market_store, "ecb", "fx", settings) == date(2026, 10, 23)  # 6 Nov - 14d


def test_cli_run_and_daily_exit_codes(
    env: tuple[Settings, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s, book = env
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text(yaml.safe_dump(s.model_dump(mode="json")))
    runner = CliRunner()
    ok = runner.invoke(
        cli.app,
        ["run", "--date", "2026-11-04", "--settings", str(settings_file), "--book", str(book)],
    )
    assert ok.exit_code == 0, ok.output
    bad = runner.invoke(
        cli.app,
        ["run", "--date", "2026-11-02", "--settings", str(settings_file), "--book", str(book)],
    )
    assert bad.exit_code == 1
    monkeypatch.setattr(cli, "make_client", lambda _s: FixtureClient(HTTP_FIXTURES))
    monkeypatch.setattr(cli, "EQUITY_HISTORY", lambda t, a, b: pd.DataFrame({"Close": []}))
    monkeypatch.setattr(
        "minibook.daily.utc_now", lambda: datetime(2026, 11, 10, 12, 30, tzinfo=UTC)
    )
    wait = runner.invoke(cli.app, ["daily", "--settings", str(settings_file), "--book", str(book)])
    assert wait.exit_code == s.pipeline.not_ready_exit_code, wait.output


def test_scenario_check_skipped_without_rating_curves(
    settings: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert pipeline._scenario_flags(RawStore(tmp_path), settings, date(2026, 11, 4)) is None
    assert "scenario artefact check skipped" in caplog.text
