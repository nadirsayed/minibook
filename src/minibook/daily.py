"""Scheduled daily job: decide which reports are due, fetch, run, catch up (ADR-001/007).

Triggered hourly on weekdays by GitHub Actions. Logic:

1. Outside the local window (``pipeline.window_start_local``..``window_end_local``,
   Europe/Berlin, which absorbs CET/CEST) or on a non-TARGET day: do nothing.
2. Fetch market data incrementally.
3. The due dates are every TARGET business day after the trade date and before today that
   has no output yet, oldest first.
4. A date D is ready if the ECB yield curve for D is in the store, or if the ECB has
   already published a *later* date. In the second case the ECB skipped D (e.g. 24 or
   31 Dec), and the snapshot forward-fills it under the 3-day rule (ADR-007). Otherwise D
   is not ready: stop and let the next hourly trigger retry.
5. Run each ready date in order. Earlier outputs feed the VaR history and the backtest.

Returns ``(dates produced, ready)``. ``ready`` is False if some due date had to wait.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from minibook.config.book import load_book
from minibook.config.settings import DEFAULT_SETTINGS_PATH, Settings
from minibook.data.cache import RawStore
from minibook.data.equities import HistoryFn
from minibook.data.http import HttpClient, utc_now
from minibook.dates.calendars import TARGET
from minibook.fetching import fetch_all
from minibook.pipeline import run

LOG = logging.getLogger(__name__)


def in_window(now: datetime, settings: Settings) -> bool:
    """Return True if ``now`` falls inside the local publishing window."""
    local = now.astimezone(ZoneInfo(settings.pipeline.timezone))
    p = settings.pipeline
    return p.window_start_local <= local.time() <= p.window_end_local


def due_dates(trade_date: date, today: date, out_root: Path) -> list[date]:
    """TARGET days in (trade_date, today) without an output directory, oldest first."""
    if today <= trade_date:
        return []
    last = TARGET.advance(today, -1)  # last TARGET business day before today
    days = TARGET.business_days_between(TARGET.advance(trade_date, 1), last)
    return [d for d in days if not (out_root / d.isoformat() / "report.pdf").exists()]


def is_ready(store: RawStore, d: date) -> bool:
    """ECB curve for ``d`` stored, or a later ECB curve published (``d`` was skipped)."""
    df = store.load("ecb", "yield_curve")
    return bool(len(df)) and max(df["obs_date"]) >= d


def daily(
    settings: Settings,
    book_path: Path,
    client: HttpClient,
    history: HistoryFn,
    settings_path: Path = DEFAULT_SETTINGS_PATH,
    repo: Path = Path(),
    clock: Callable[[], datetime] | None = None,
    ignore_window: bool = False,
) -> tuple[list[date], bool]:
    """Run every due report that is ready. See module docstring.

    ``clock`` defaults to the module's ``utc_now``, looked up at call time.
    """
    now = clock() if clock is not None else utc_now()
    local_today = now.astimezone(ZoneInfo(settings.pipeline.timezone)).date()
    if not ignore_window and not in_window(now, settings):
        LOG.info("outside the publishing window (%s local): nothing to do", now)
        return [], True
    if not TARGET.is_business_day(local_today):
        LOG.info("%s is not a TARGET business day: nothing to do", local_today)
        return [], True
    book = load_book(book_path)
    due = due_dates(book.trade_date, local_today, settings.pipeline.output_dir)
    if not due:
        LOG.info("all reports up to date")
        return [], True
    store = RawStore(settings.data.raw_dir)
    failures = fetch_all(client, store, settings, local_today, history)
    if failures:
        LOG.warning("fetch failures: %s (runs use what is stored; staleness is enforced)", failures)
    done: list[date] = []
    for d in due:
        if not is_ready(store, d):
            LOG.info("ECB curve for %s not published yet: retry at the next trigger", d)
            return done, False
        run(d, settings, book_path, settings_path, repo, clock or utc_now)
        done.append(d)
    return done, True
