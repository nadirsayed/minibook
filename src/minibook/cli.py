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
from datetime import date, datetime
from typing import Annotated

import typer

from minibook import __version__

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
def init_book(
    trade_date: Annotated[
        date, typer.Option("--trade-date", parser=_parse_date, metavar="YYYY-MM-DD")
    ],
) -> None:
    """Freeze par rate, outright forwards and strikes at TRADE_DATE into book.yaml."""
    _not_implemented("init-book", "M8")


@app.command()
def fetch(
    start: Annotated[date | None, typer.Option(parser=_parse_date, metavar="YYYY-MM-DD")] = None,
    end: Annotated[date | None, typer.Option(parser=_parse_date, metavar="YYYY-MM-DD")] = None,
) -> None:
    """Download and cache raw market data for [START, END]."""
    _not_implemented("fetch", "M1/M8")


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
