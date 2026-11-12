"""Equity index closes via yfinance.

Dataset ``equities/index_close``: ``series`` is the index label from settings (``SX5E``,
``DAX``, ``CAC40``, ``FTSEMIB``) and ``value`` is the unadjusted close in index points.

No look-ahead (ADR-003, approved 2026-11-12)
--------------------------------------------
* At fetch time, a bar dated on the fetch day (in ``settings.timezone``) is kept only if the
  fetch happens at or after ``close_cutoff_local``. Before that it is an intraday bar.
  Bars dated after the fetch day are always dropped.
* At read time, :func:`index_closes` drops every bar dated after the valuation date.

yfinance does not expose the underlying HTTP payload. The archived "raw payload" is
therefore yfinance's unadjusted OHLCV frame as CSV, together with the call arguments.

Licensing caveat: Yahoo Finance terms restrict automated access and redistribution, and
the index levels are licensed by the index providers. See docs/decisions.md (open issue).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from minibook.config.settings import EquitySettings
from minibook.data.cache import RawStore
from minibook.data.http import FetchResult, utc_now

LOG = logging.getLogger(__name__)

SOURCE = "equities"
DATASET = "index_close"
CLOSE_COLUMN = "Close"


class HistoryFn(Protocol):
    """Callable returning daily bars for ``ticker`` with dates in [start, end)."""

    def __call__(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        """Return a frame indexed by bar timestamp with at least a ``Close`` column."""
        ...


def yfinance_history(ticker: str, start: date, end: date) -> pd.DataFrame:  # pragma: no cover
    """Production :class:`HistoryFn`: unadjusted daily bars from yfinance (end exclusive)."""
    import yfinance as yf  # noqa: PLC0415 - heavy import, only needed for live fetches

    df = yf.Ticker(ticker).history(
        start=start.isoformat(),
        end=end.isoformat(),
        interval="1d",
        auto_adjust=False,
        actions=False,
    )
    return pd.DataFrame(df)


def completed_bars(
    bars: pd.DataFrame, fetched_at: datetime, settings: EquitySettings
) -> pd.DataFrame:
    """Drop intraday and future bars (ADR-003).

    Parameters
    ----------
    bars
        Frame indexed by bar timestamp (tz-aware or naive; only the date is used).
    fetched_at
        Fetch time (tz-aware).
    settings
        Provides the local timezone and the close cutoff.

    Returns
    -------
    pandas.DataFrame
        Bars dated strictly before the local fetch date, plus the fetch-date bar if
        ``fetched_at`` is at or after the cutoff.
    """
    local = fetched_at.astimezone(ZoneInfo(settings.timezone))
    today_ok = local.time() >= settings.close_cutoff_local
    keep = np.array(
        [
            d < local.date() or (d == local.date() and today_ok)
            for d in (ts.date() for ts in bars.index)
        ],
        dtype=bool,
    )
    dropped = bars.index[~keep]
    if len(dropped):
        LOG.info(
            "dropping %d incomplete/future bar(s): %s (fetched %s)",
            len(dropped),
            [d.date().isoformat() for d in dropped],
            local.isoformat(),
        )
    return pd.DataFrame(bars.loc[keep])


def fetch_index_closes(
    history: HistoryFn,
    store: RawStore,
    settings: EquitySettings,
    start: date,
    end: date,
    clock: Callable[[], datetime] = utc_now,
) -> pd.DataFrame:
    """Fetch closes for every configured index for [start, end] (both inclusive)."""
    frames = []
    for label, ticker in settings.tickers.items():
        bars = history(ticker, start, end + timedelta(days=1))
        fetched_at = clock()
        if bars.empty:
            raise ValueError(f"yfinance returned no bars for {ticker} {start}..{end}")
        payload_bytes = bars.to_csv().encode("utf-8")
        result = FetchResult(
            url=f"yfinance://{ticker}?start={start}&end={end}&auto_adjust=false",
            status=200,
            content=payload_bytes,
            fetched_at=fetched_at,
            content_type="text/csv",
        )
        payload = store.save_payload(SOURCE, DATASET, result, f".{label}.csv")
        done = completed_bars(bars, fetched_at, settings)
        obs = pd.DataFrame(
            {
                "obs_date": [ts.date() for ts in done.index],
                "series": label,
                "value": done[CLOSE_COLUMN].astype("float64").to_numpy(),
            }
        ).dropna(subset=["value"])
        if not obs.empty:
            store.upsert(SOURCE, DATASET, obs, fetched_at, payload)
        frames.append(obs)
    return pd.concat(frames, ignore_index=True)


def index_closes(store: RawStore, as_of: date) -> pd.DataFrame:
    """Wide frame of closes with every bar dated after ``as_of`` removed (no look-ahead)."""
    return store.load_wide(SOURCE, DATASET, as_of=as_of)
