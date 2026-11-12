"""U.S. Treasury "Daily Treasury Par Yield Curve Rates": the primary USD source (ADR-012).

The par yields are derived from indicative bid quotes collected by the Federal Reserve Bank
of New York at about 3:30 PM ET each business day. Treasury fits a monotone convex curve
through them. Bills enter "as bond equivalent yields" (Treasury Yield Curve Methodology
page, read 2026-11-12). They are published the same evening, a business day before FRED.

One CSV per calendar year: ``Date`` (MM/DD/YYYY) and one column per tenor (percent). New
tenors appear over time (e.g. "1.5 Month" in 2025), so columns are mapped by name from
settings and a configured column that is missing is an error.

Dataset ``treasury/par_curve``: ``series`` is the tenor label (``1M`` .. ``10Y``) and
``value`` the yield in percent.

Terms: U.S. federal government work, public domain (17 U.S.C. §105). robots.txt places no
restriction on this path (checked 2026-11-12). Citation: "Source: U.S. Department of the
Treasury".
"""

from __future__ import annotations

import io
import logging
from datetime import date

import pandas as pd

from minibook.config.settings import TreasurySettings
from minibook.data.cache import RawStore
from minibook.data.http import HttpClient

LOG = logging.getLogger(__name__)

SOURCE = "treasury"
DATASET = "par_curve"
DATE_FORMAT = "%m/%d/%Y"


def parse_par_curve(content: bytes, columns: dict[str, str]) -> pd.DataFrame:
    """Parse one yearly Treasury par-curve CSV into long observations.

    Parameters
    ----------
    content
        CSV body.
    columns
        Tenor label -> CSV column name, e.g. ``{"3M": "3 Mo"}``.
    """
    df = pd.read_csv(io.StringIO(content.decode("utf-8")), dtype=str)
    missing = [c for c in columns.values() if c not in df.columns]
    if "Date" not in df.columns or missing:
        raise ValueError(f"Treasury CSV lacks columns {missing or ['Date']}: {list(df.columns)}")
    dates = pd.to_datetime(df["Date"], format=DATE_FORMAT).dt.date
    frames = [
        pd.DataFrame(
            {"obs_date": dates, "series": label, "value": pd.to_numeric(df[col], errors="coerce")}
        )
        for label, col in columns.items()
    ]
    out = pd.concat(frames, ignore_index=True).dropna(subset=["value"])
    return out.sort_values(["series", "obs_date"], kind="stable").reset_index(drop=True)


def fetch_par_curve(
    client: HttpClient, store: RawStore, settings: TreasurySettings, start: date, end: date
) -> pd.DataFrame:
    """Fetch the yearly files covering [start, end], archive them and store observations."""
    frames = []
    for year in range(start.year, end.year + 1):
        params = {**settings.params, "field_tdr_date_value": str(year)}
        result = client.get(settings.url_template.format(year=year), params)
        obs = parse_par_curve(result.content, dict(settings.columns))
        obs = obs.loc[(obs["obs_date"] >= start) & (obs["obs_date"] <= end)]
        payload = store.save_payload(SOURCE, DATASET, result, f".{year}.csv")
        if not obs.empty:
            store.upsert(SOURCE, DATASET, obs, result.fetched_at, payload)
        frames.append(obs)
    return pd.concat(frames, ignore_index=True)
