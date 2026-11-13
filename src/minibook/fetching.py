"""Incremental market-data fetch (shared by ``minibook fetch`` and the daily job).

For each dataset the window starts ``pipeline.fetch_lookback_days`` before its last stored
observation (or at ``data.history_start`` for an empty store) and ends at ``end``. Re-reading
a few days catches late revisions, which the raw store logs and keeps. MoF's large history
file is only re-read when the store does not yet cover the previous month (the current-month
file only holds the current month). Every source is attempted; failures are collected and
returned, never hidden.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, timedelta

from minibook.config.settings import Settings
from minibook.data import ecb, equities, fred, mof, treasury
from minibook.data.cache import RawStore
from minibook.data.http import HttpClient

LOG = logging.getLogger(__name__)


def window_start(
    store: RawStore, source: str, dataset: str, settings: Settings, floor: date | None = None
) -> date:
    """First date to fetch for a dataset (lookback before its last stored observation)."""
    df = store.load(source, dataset)
    start = settings.data.history_start
    if not df.empty:
        start = max(
            start, max(df["obs_date"]) - timedelta(days=settings.pipeline.fetch_lookback_days)
        )
    return start if floor is None else min(start, floor)


def fetch_all(
    client: HttpClient,
    store: RawStore,
    settings: Settings,
    end: date,
    history: equities.HistoryFn,
    start: date | None = None,
) -> list[str]:
    """Fetch every source up to ``end``; return the names of the sources that failed.

    ``start`` forces the beginning of every window (full re-fetch); otherwise windows are
    incremental.
    """
    s = settings

    def ws(source: str, dataset: str) -> date:
        return start if start is not None else window_start(store, source, dataset, s)

    mof_df = store.load("mof", "jgb_cm")
    month_start = end.replace(day=1)
    need_history = (
        start is not None
        or mof_df.empty
        or max(mof_df["obs_date"]) < (month_start - timedelta(days=1))
    )
    jobs: dict[str, Callable[[], object]] = {
        "ecb.yield_curve": lambda: ecb.fetch_yield_curve(
            client, store, s.ecb, ws("ecb", "yield_curve"), end
        ),
        "ecb.fx": lambda: ecb.fetch_fx(client, store, s.ecb, ws("ecb", "fx"), end),
        "ecb.estr": lambda: ecb.fetch_estr(client, store, s.ecb, ws("ecb", "estr"), end),
        "ecb.rating_curves": lambda: ecb.fetch_rating_curves(
            client, store, s.ecb, ws("ecb", "rating_curves"), end
        ),
        "treasury.par_curve": lambda: treasury.fetch_par_curve(
            client, store, s.treasury, ws("treasury", "par_curve"), end
        ),
        "fred.ust_cmt": lambda: fred.fetch_ust_cmt(
            client, store, s.fred, ws("fred", "ust_cmt"), end
        ),
        "mof.jgb_cm": lambda: mof.fetch_jgb(client, store, s.mof, include_history=need_history),
        "equities.index_close": lambda: equities.fetch_index_closes(
            history, store, s.equities, ws("equities", "index_close"), end
        ),
    }
    failures = []
    for name, job in jobs.items():
        try:
            job()
        except Exception:
            LOG.exception("fetch %s failed", name)
            failures.append(name)
    return failures
