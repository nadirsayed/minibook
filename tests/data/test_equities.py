"""Equity fetcher tests. All bars are SYNTHETIC: Yahoo / index-provider terms restrict
redistribution of real index levels, so no real equity data is committed."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from minibook.config.settings import Settings
from minibook.data.cache import RawStore
from minibook.data.equities import completed_bars, fetch_index_closes, index_closes


def bars(days: list[str], tz: str = "Europe/Berlin") -> pd.DataFrame:
    idx = pd.DatetimeIndex([pd.Timestamp(d, tz=tz) for d in days])
    return pd.DataFrame({"Close": [100.0 + i for i in range(len(days))]}, index=idx)


DAYS = ["2026-11-10", "2026-11-11", "2026-11-12"]


@pytest.mark.parametrize(
    ("fetched_utc", "expected_last"),
    [
        # 12 Nov 2026 is CET (UTC+1): 13:45 CET is before the 18:30 cutoff.
        (datetime(2026, 11, 12, 12, 45, tzinfo=UTC), "2026-11-11"),
        # 17:30 UTC = 18:30 CET, exactly the cutoff: accepted.
        (datetime(2026, 11, 12, 17, 30, tzinfo=UTC), "2026-11-12"),
        # Next morning: the 12 Nov bar is complete.
        (datetime(2026, 11, 13, 7, 0, tzinfo=UTC), "2026-11-12"),
    ],
)
def test_intraday_bar_dropped(
    settings: Settings, fetched_utc: datetime, expected_last: str
) -> None:
    out = completed_bars(bars(DAYS), fetched_utc, settings.equities)
    assert out.index[-1].date().isoformat() == expected_last


def test_cutoff_respects_summer_time(settings: Settings) -> None:
    # 2026-07-01 is CEST (UTC+2): 16:45 UTC = 18:45 local -> accepted; 16:15 UTC -> not.
    b = bars(["2026-06-30", "2026-07-01"])
    late = completed_bars(b, datetime(2026, 7, 1, 16, 45, tzinfo=UTC), settings.equities)
    early = completed_bars(b, datetime(2026, 7, 1, 16, 15, tzinfo=UTC), settings.equities)
    assert len(late) == 2 and len(early) == 1


def test_future_bar_dropped(settings: Settings) -> None:
    out = completed_bars(
        bars(["2026-11-12", "2026-11-13"]),
        datetime(2026, 11, 12, 20, 0, tzinfo=UTC),
        settings.equities,
    )
    assert [ts.date() for ts in out.index] == [date(2026, 11, 12)]


def test_fetch_and_read_as_of(store: RawStore, settings: Settings) -> None:
    calls: list[tuple[str, date, date]] = []

    def history(ticker: str, start: date, end: date) -> pd.DataFrame:
        calls.append((ticker, start, end))
        return bars(DAYS)

    fetch_index_closes(
        history,
        store,
        settings.equities,
        date(2026, 11, 10),
        date(2026, 11, 12),
        clock=lambda: datetime(2026, 11, 12, 12, 45, tzinfo=UTC),
    )
    # end is passed exclusive to yfinance, hence +1 day.
    assert calls[0] == ("^STOXX50E", date(2026, 11, 10), date(2026, 11, 13))
    assert len(calls) == len(settings.equities.tickers)
    wide = index_closes(store, as_of=date(2026, 11, 12))
    assert list(wide.columns) == sorted(settings.equities.tickers)
    assert wide.index[-1] == pd.Timestamp("2026-11-11")  # intraday bar was not stored
    assert len(index_closes(store, as_of=date(2026, 11, 10))) == 1  # no look-ahead


def test_empty_history_is_an_error(store: RawStore, settings: Settings) -> None:
    with pytest.raises(ValueError, match="no bars"):
        fetch_index_closes(
            lambda t, s, e: pd.DataFrame({"Close": []}),
            store,
            settings.equities,
            date(2026, 11, 10),
            date(2026, 11, 12),
        )
