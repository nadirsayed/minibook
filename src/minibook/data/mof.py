"""Japan Ministry of Finance JGB yield fetcher.

MoF publishes constant-maturity JGB yields (1Y..40Y, percent) in two CSVs:

* ``jgbcme.csv``: the current month,
* ``historical/jgbcme_all.csv``: from 1974 to the end of the previous month.

Both are archived and merged into dataset ``mof/jgb_cm``. Convention (MoF FAQ,
https://www.mof.go.jp/faq/jgbs/04hc.htm and 04hb.htm): each issue's yield is a
*semi-annually compounded* yield computed from JSDA over-the-counter reference prices. A
yield curve is fitted through those issue yields and read at exact constant maturities.
Publication is around 09:30 JST on the next business day (04hf.htm).

Licence: Public Data License 1.0 (https://www.mof.go.jp/about_mof/notice/index.html).
"""

from __future__ import annotations

import io
import logging

import pandas as pd

from minibook.config.settings import MofSettings
from minibook.data.cache import RawStore
from minibook.data.http import FetchResult, HttpClient

LOG = logging.getLogger(__name__)

SOURCE = "mof"
DATASET = "jgb_cm"
HEADER_PREFIX = "Date,"
DATE_FORMAT = "%Y/%m/%d"


def parse_jgbcme(content: bytes, encoding: str, missing_marker: str) -> pd.DataFrame:
    """Parse a MoF JGB CSV into long observations (series = tenor label, e.g. ``"10Y"``).

    The file has a title line, a header line starting with ``Date,``, data lines, then
    footer notes. Lines whose first field is not a ``YYYY/M/D`` date are ignored, and
    ``missing_marker`` cells (tenor not yet issued) are dropped.
    """
    lines = content.decode(encoding).splitlines()
    try:
        header = next(i for i, ln in enumerate(lines) if ln.startswith(HEADER_PREFIX))
    except StopIteration as exc:
        raise ValueError("MoF CSV: header line 'Date,...' not found") from exc
    df = pd.read_csv(io.StringIO("\n".join(lines[header:])), dtype=str)
    dates = pd.to_datetime(df["Date"], format=DATE_FORMAT, errors="coerce")
    df = df.loc[dates.notna()].assign(Date=dates[dates.notna()].dt.date)
    long = df.melt(id_vars="Date", var_name="series", value_name="raw")
    long = long.loc[long["raw"].notna() & (long["raw"].str.strip() != missing_marker)]
    out = pd.DataFrame(
        {
            "obs_date": long["Date"].to_numpy(),
            "series": long["series"].str.strip().to_numpy(),
            "value": pd.to_numeric(long["raw"], errors="raise").to_numpy(),
        }
    )
    return out.sort_values(["series", "obs_date"], kind="stable").reset_index(drop=True)


def _ingest(store: RawStore, settings: MofSettings, result: FetchResult, tag: str) -> pd.DataFrame:
    obs = parse_jgbcme(result.content, settings.encoding, settings.missing_marker)
    payload = store.save_payload(SOURCE, DATASET, result, f".{tag}.csv")
    if not obs.empty:
        store.upsert(SOURCE, DATASET, obs, result.fetched_at, payload)
    return obs


def fetch_jgb(
    client: HttpClient, store: RawStore, settings: MofSettings, include_history: bool = True
) -> pd.DataFrame:
    """Fetch the history file (optional) and then the current-month file.

    The history file is ingested first, so a value restated in the current-month file is
    recorded as a revision (logged) and not silently overwritten.
    """
    frames = []
    if include_history:
        frames.append(_ingest(store, settings, client.get(settings.history_url), "all"))
    frames.append(_ingest(store, settings, client.get(settings.latest_url), "latest"))
    return pd.concat(frames, ignore_index=True)
