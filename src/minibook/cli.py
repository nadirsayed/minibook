"""Command-line interface (Typer).

Commands
--------
init-book  Compute par rate, outright forwards and strikes at the trade date and
           freeze them in config/book.yaml.
fetch      Download and cache raw market data.
run        Value the book, compute Greeks, P&L explain, VaR/ES and the PDF for one date.
backfill   Run ``run`` over a range of TARGET business days.

All commands are idempotent.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer

from minibook import __version__, pipeline
from minibook.config.book import DEFAULT_BOOK_PATH
from minibook.config.settings import DEFAULT_SETTINGS_PATH, Settings, load_settings
from minibook.daily import daily
from minibook.data import equities
from minibook.data.cache import RawStore
from minibook.data.fixings import FixingStore
from minibook.data.http import HttpClient, RequestsClient
from minibook.dates.calendars import TARGET
from minibook.fetching import fetch_all
from minibook.init_book import init_book
from minibook.market.builder import MarketDataError, SnapshotBuilder

LOG = logging.getLogger(__name__)

app = typer.Typer(
    name="minibook",
    help="Mini derivatives book: valuation, Greeks, P&L explain, VaR/ES, PDF report.",
    no_args_is_help=True,
    add_completion=False,
)


def _parse_date(value: str) -> date:
    """Parse an ISO ``YYYY-MM-DD`` date."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise typer.BadParameter(f"expected YYYY-MM-DD, got {value!r}") from exc


DateOpt = Annotated[date, typer.Option(parser=_parse_date, metavar="YYYY-MM-DD")]


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Debug logging.")] = False,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """Configure logging for every sub-command."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@app.command("init-book")
def init_book_cmd(
    trade_date: Annotated[
        date, typer.Option("--trade-date", parser=_parse_date, metavar="YYYY-MM-DD")
    ],
    settings_path: Annotated[Path, typer.Option("--settings")] = DEFAULT_SETTINGS_PATH,
    book_path: Annotated[Path, typer.Option("--book")] = DEFAULT_BOOK_PATH,
) -> None:
    """Freeze par rate, outright forwards and strikes at TRADE_DATE into book.yaml.

    Uses the cached market data (run ``minibook fetch`` first). Re-running verifies the
    frozen terms and changes nothing.
    """
    s = load_settings(settings_path)
    builder = SnapshotBuilder(RawStore(s.data.raw_dir), s)
    status = init_book(book_path, s, builder.build, FixingStore(s.data.fixings_dir), trade_date)
    LOG.info("init-book %s: %s", trade_date, status)


def make_client(settings: Settings) -> HttpClient:
    """Return the production HTTP client (patched in tests)."""
    return RequestsClient(settings.http)


EQUITY_HISTORY: equities.HistoryFn = equities.yfinance_history


@app.command()
def fetch(
    start: Annotated[date | None, typer.Option(parser=_parse_date, metavar="YYYY-MM-DD")] = None,
    end: Annotated[date | None, typer.Option(parser=_parse_date, metavar="YYYY-MM-DD")] = None,
    full: Annotated[bool, typer.Option("--full", help="Re-fetch from data.history_start.")] = False,
    settings_path: Annotated[Path, typer.Option("--settings")] = DEFAULT_SETTINGS_PATH,
) -> None:
    """Download market data for [START, END] (END defaults to today) into the local cache.

    Without START the fetch is incremental: each source restarts a few days before its last
    stored observation (``--full``: from data.history_start). Every source is attempted;
    failures are listed and the exit status is 1.
    """
    s = load_settings(settings_path)
    store = RawStore(s.data.raw_dir)
    failures = fetch_all(
        make_client(s),
        store,
        s,
        end or date.today(),
        EQUITY_HISTORY,
        start=s.data.history_start if full else start,
    )
    if failures:
        LOG.error("failed sources: %s", ", ".join(failures))
        raise typer.Exit(code=1)
    LOG.info("all sources fetched into %s", s.data.raw_dir)


@app.command("run")
def run_cmd(
    run_date: Annotated[date, typer.Option("--date", parser=_parse_date, metavar="YYYY-MM-DD")],
    settings_path: Annotated[Path, typer.Option("--settings")] = DEFAULT_SETTINGS_PATH,
    book_path: Annotated[Path, typer.Option("--book")] = DEFAULT_BOOK_PATH,
) -> None:
    """Produce every output for one TARGET business day from the cached data."""
    s = load_settings(settings_path)
    try:
        res = pipeline.run(run_date, s, book_path, settings_path)
    except (pipeline.PipelineError, MarketDataError) as exc:
        LOG.error("%s", exc)
        raise typer.Exit(code=1) from exc
    LOG.info("outputs in %s (%.1fs)", res.out_dir, res.seconds)


@app.command()
def backfill(
    start: Annotated[date, typer.Option(parser=_parse_date, metavar="YYYY-MM-DD")],
    end: Annotated[date, typer.Option(parser=_parse_date, metavar="YYYY-MM-DD")],
    settings_path: Annotated[Path, typer.Option("--settings")] = DEFAULT_SETTINGS_PATH,
    book_path: Annotated[Path, typer.Option("--book")] = DEFAULT_BOOK_PATH,
) -> None:
    """Run every TARGET business day in [START, END], oldest first (idempotent).

    Backfilled reports disclose that their data was fetched after the report date.
    """
    s = load_settings(settings_path)
    for d in TARGET.business_days_between(start, end):
        try:
            res = pipeline.run(d, s, book_path, settings_path)
        except (pipeline.PipelineError, MarketDataError) as exc:
            LOG.error("%s: %s", d, exc)
            raise typer.Exit(code=1) from exc
        LOG.info("%s done (%.1fs)", d, res.seconds)


@app.command("daily")
def daily_cmd(
    settings_path: Annotated[Path, typer.Option("--settings")] = DEFAULT_SETTINGS_PATH,
    book_path: Annotated[Path, typer.Option("--book")] = DEFAULT_BOOK_PATH,
    ignore_window: Annotated[bool, typer.Option("--ignore-window")] = False,
) -> None:
    """Scheduled job: fetch, then produce every due report whose ECB curve is published.

    Exit status ``pipeline.not_ready_exit_code`` (75) when a due report must wait for the
    ECB; the workflow treats it as "retry at the next trigger", not as a failure.
    """
    s = load_settings(settings_path)
    done, ready = daily(
        s, book_path, make_client(s), EQUITY_HISTORY, settings_path, ignore_window=ignore_window
    )
    LOG.info("produced: %s", [str(d) for d in done] or "nothing")
    if not ready:
        raise typer.Exit(code=s.pipeline.not_ready_exit_code)
