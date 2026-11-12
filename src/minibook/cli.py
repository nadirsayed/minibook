"""Command-line interface (Typer).

Commands
--------
init-book  Compute par rate, outright forwards and strikes at the trade date and
           freeze them in config/book.yaml.
fetch      Download and cache raw market data.
run        Value the book, compute Greeks, P&L explain, VaR/ES and the PDF for one date.
backfill   Run ``run`` over a range of TARGET business days.

All commands are idempotent. Commands not yet implemented exit with status 2.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer

from minibook import __version__
from minibook.config.book import DEFAULT_BOOK_PATH
from minibook.config.settings import DEFAULT_SETTINGS_PATH, Settings, load_settings
from minibook.data import ecb, equities, fred, mof, treasury
from minibook.data.cache import RawStore
from minibook.data.fixings import FixingStore
from minibook.data.http import HttpClient, RequestsClient
from minibook.init_book import init_book
from minibook.market.builder import SnapshotBuilder

LOG = logging.getLogger(__name__)
NOT_IMPLEMENTED_EXIT = 2

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


def _not_implemented(command: str, milestone: str) -> None:
    LOG.error("'%s' is not implemented yet (planned in %s).", command, milestone)
    raise typer.Exit(code=NOT_IMPLEMENTED_EXIT)


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
    settings_path: Annotated[Path, typer.Option("--settings")] = DEFAULT_SETTINGS_PATH,
) -> None:
    """Download and cache raw market data for [START, END].

    START defaults to ``data.history_start`` and END to today. Every source is attempted.
    If any source fails, the failures are listed and the command exits with status 1.
    """
    s = load_settings(settings_path)
    start = start or s.data.history_start
    end = end or date.today()
    client = make_client(s)
    store = RawStore(s.data.raw_dir)
    jobs: dict[str, Callable[[], object]] = {
        "ecb.yield_curve": lambda: ecb.fetch_yield_curve(client, store, s.ecb, start, end),
        "ecb.fx": lambda: ecb.fetch_fx(client, store, s.ecb, start, end),
        "ecb.estr": lambda: ecb.fetch_estr(client, store, s.ecb, start, end),
        "treasury.par_curve": lambda: treasury.fetch_par_curve(
            client, store, s.treasury, start, end
        ),
        "fred.ust_cmt": lambda: fred.fetch_ust_cmt(client, store, s.fred, start, end),
        "mof.jgb_cm": lambda: mof.fetch_jgb(client, store, s.mof),
        "equities.index_close": lambda: equities.fetch_index_closes(
            EQUITY_HISTORY, store, s.equities, start, end
        ),
    }
    failures = []
    for name, job in jobs.items():
        LOG.info("fetching %s for %s..%s", name, start, end)
        try:
            job()
        except Exception:
            LOG.exception("fetch %s failed", name)
            failures.append(name)
    if failures:
        LOG.error("failed sources: %s", ", ".join(failures))
        raise typer.Exit(code=1)
    LOG.info("all sources fetched into %s", s.data.raw_dir)


@app.command()
def run(
    run_date: Annotated[date, typer.Option("--date", parser=_parse_date, metavar="YYYY-MM-DD")],
) -> None:
    """Produce every output for one TARGET business day."""
    _not_implemented("run", "M8")


@app.command()
def backfill(
    start: Annotated[date, typer.Option(parser=_parse_date, metavar="YYYY-MM-DD")],
    end: Annotated[date, typer.Option(parser=_parse_date, metavar="YYYY-MM-DD")],
) -> None:
    """Run every TARGET business day in [START, END]."""
    _not_implemented("backfill", "M8")
