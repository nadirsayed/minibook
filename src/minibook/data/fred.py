"""FRED fetcher for US Treasury constant-maturity par yields (H.15, percent).

One request per series: with several ``id`` values, ``fredgraph.csv`` applies the
``cosd``/``coed`` window only to the first series (observed 2026-11-12).

Dataset ``fred/ust_cmt``: ``series`` is the tenor label from settings (``1M`` .. ``10Y``),
``value`` the yield in percent. These are *par* yields, not zero rates. The bootstrap to
zero rates is in :mod:`minibook.market.bootstrap` (M2).

Source: FRED, Federal Reserve Bank of St. Louis (https://fred.stlouisfed.org/), series
DGS*, "Public Domain: Citation requested".
"""

from __future__ import annotations

import io
import logging
from datetime import date

import pandas as pd

from minibook.config.settings import FredSettings
from minibook.data.cache import RawStore
from minibook.data.http import HttpClient

LOG = logging.getLogger(__name__)

SOURCE = "fred"
DATASET = "ust_cmt"
DATE_COLUMNS = ("observation_date", "DATE")


def parse_fredgraph(content: bytes, series_id: str, label: str) -> pd.DataFrame:
    """Parse a single-series ``fredgraph.csv`` body into long observations.

    Missing values (holidays) appear as empty cells or ``"."`` and are dropped.
    """
    df = pd.read_csv(io.StringIO(content.decode("utf-8")), na_values=["."], dtype=str)
    date_col = next((c for c in DATE_COLUMNS if c in df.columns), None)
    if date_col is None or series_id not in df.columns:
        raise ValueError(f"unexpected FRED CSV header for {series_id}: {list(df.columns)}")
    out = pd.DataFrame(
        {
            "obs_date": pd.to_datetime(df[date_col], format="%Y-%m-%d").dt.date,
            "series": label,
            "value": pd.to_numeric(df[series_id], errors="raise"),
        }
    )
    return out.dropna(subset=["value"]).reset_index(drop=True)


def fetch_ust_cmt(
    client: HttpClient, store: RawStore, settings: FredSettings, start: date, end: date
) -> pd.DataFrame:
    """Fetch every configured DGS series for [start, end] and archive each payload."""
    frames = []
    for label, series_id in settings.series.items():
        params = {"id": series_id, "cosd": start.isoformat(), "coed": end.isoformat()}
        result = client.get(settings.url, params)
        obs = parse_fredgraph(result.content, series_id, label)
        payload = store.save_payload(SOURCE, DATASET, result, f".{series_id}.csv")
        if not obs.empty:
            store.upsert(SOURCE, DATASET, obs, result.fetched_at, payload)
        frames.append(obs)
    return pd.concat(frames, ignore_index=True)
