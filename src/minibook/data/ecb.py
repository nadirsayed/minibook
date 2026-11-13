"""ECB Data Portal fetcher (SDMX REST, ``format=csvdata``).

Datasets
--------
``ecb/yield_curve``
    Svensson parameters BETA0..BETA3 (percent) and TAU1, TAU2 (years) for the AAA euro area
    government curve (``SV_C_YM``: continuous compounding), plus the published spot rates
    SR_1Y/SR_5Y/SR_10Y (percent), used only to validate the curve rebuild.
``ecb/fx``
    ECB euro foreign exchange reference rates: units of quote currency per 1 EUR.
``ecb/estr``
    Euro short-term rate (percent).

Values are stored as published (percent, not decimal). Unit conversion happens in the
market layer, in one place.

Source: https://data.ecb.europa.eu/help/api/data. Reuse: ESCB statistics reuse policy
(free of charge, source to be quoted).
"""

from __future__ import annotations

import io
import logging
from collections.abc import Mapping
from datetime import date

import pandas as pd

from minibook.config.settings import EcbSettings
from minibook.data.cache import RawStore
from minibook.data.http import FetchError, FetchResult, HttpClient

LOG = logging.getLogger(__name__)

SOURCE = "ecb"
HTTP_NOT_FOUND = 404
NORMAL_OBS_STATUS = "A"


def series_url(base_url: str, flow: str, keys: list[str]) -> str:
    """Build an SDMX data URL that ORs several keys sharing all but the last dimension.

    ``keys`` must be complete series keys. They are combined with ``+`` in the last
    dimension, e.g. ``YC/B.U2.EUR.4F.G_N_A.SV_C_YM.BETA0+BETA1``. Values are sorted, so the
    URL does not depend on the order of ``keys`` (deterministic caching and replay).
    """
    prefixes = {k.rsplit(".", 1)[0] for k in keys}
    if len(prefixes) == 1:
        prefix = prefixes.pop()
        last = "+".join(sorted({k.rsplit(".", 1)[1] for k in keys}))
        return f"{base_url}/{flow}/{prefix}.{last}"
    # Keys differing elsewhere (e.g. EXR D.USD.EUR... vs D.JPY.EUR...): OR each dimension.
    parts = [k.split(".") for k in keys]
    if len({len(p) for p in parts}) != 1:
        raise ValueError(f"keys have different dimensionality: {keys}")
    dims = ["+".join(sorted({p[i] for p in parts})) for i in range(len(parts[0]))]
    return f"{base_url}/{flow}/{'.'.join(dims)}"


def parse_csvdata(content: bytes, flow: str, labels: Mapping[str, str]) -> pd.DataFrame:
    """Parse an ECB ``csvdata`` body into long observations.

    Parameters
    ----------
    content
        Response body. An empty body means "no observations in the period".
    flow
        Dataflow id, e.g. ``"YC"``. The ``KEY`` column is ``"<flow>.<series key>"``.
    labels
        Map from series key (without the flow prefix) to the label stored in ``series``.
        Rows for keys not in ``labels`` are an error: the OR-query matched more than asked.

    Returns
    -------
    pandas.DataFrame
        Columns ``obs_date`` (date), ``series`` (str), ``value`` (float), sorted.
    """
    text = content.decode("utf-8")
    if not text.strip():
        return pd.DataFrame({"obs_date": [], "series": [], "value": []})
    df = pd.read_csv(io.StringIO(text), dtype={"KEY": str, "TIME_PERIOD": str})
    keys = df["KEY"].str.removeprefix(f"{flow}.")
    unknown = sorted(set(keys) - set(labels))
    if unknown:
        raise ValueError(f"unexpected ECB series in response: {unknown}")
    if "OBS_STATUS" in df.columns:
        odd = df["OBS_STATUS"].fillna(NORMAL_OBS_STATUS) != NORMAL_OBS_STATUS
        for row in df.loc[odd].itertuples():
            LOG.warning("ECB %s %s has OBS_STATUS=%s", row.KEY, row.TIME_PERIOD, row.OBS_STATUS)
    out = pd.DataFrame(
        {
            "obs_date": pd.to_datetime(df["TIME_PERIOD"], format="%Y-%m-%d").dt.date,
            "series": keys.map(labels),
            "value": pd.to_numeric(df["OBS_VALUE"], errors="coerce"),
        }
    )
    n_nan = int(out["value"].isna().sum())
    if n_nan:
        LOG.warning("ECB %s: dropping %d empty observations", flow, n_nan)
    out = out.dropna(subset=["value"])
    return out.sort_values(["series", "obs_date"], kind="stable").reset_index(drop=True)


def _fetch(
    client: HttpClient,
    store: RawStore,
    settings: EcbSettings,
    dataset: str,
    flow: str,
    labels: Mapping[str, str],
    start: date,
    end: date,
) -> pd.DataFrame:
    url = series_url(settings.base_url, flow, list(labels))
    params = {"format": "csvdata", "startPeriod": start.isoformat(), "endPeriod": end.isoformat()}
    try:
        result = client.get(url, params)
    except FetchError as exc:
        if exc.status != HTTP_NOT_FOUND:
            raise
        # The ECB API signals "no data for this period" with 404 on some flows.
        LOG.info("ECB %s: no data for %s..%s (HTTP 404)", dataset, start, end)
        return pd.DataFrame({"obs_date": [], "series": [], "value": []})
    obs = parse_csvdata(result.content, flow, labels)
    _archive(store, dataset, result, obs)
    return obs


def _archive(store: RawStore, dataset: str, result: FetchResult, obs: pd.DataFrame) -> None:
    payload = store.save_payload(SOURCE, dataset, result, ".csv")
    if not obs.empty:
        store.upsert(SOURCE, dataset, obs, result.fetched_at, payload)


def fetch_yield_curve(
    client: HttpClient, store: RawStore, settings: EcbSettings, start: date, end: date
) -> pd.DataFrame:
    """Fetch Svensson parameters and validation spot rates for [start, end]."""
    yc = settings.yield_curve
    labels = {f"{yc.key_prefix}.{name}": name for name in (*yc.params, *yc.validation)}
    return _fetch(client, store, settings, "yield_curve", yc.flow, labels, start, end)


def fetch_fx(
    client: HttpClient, store: RawStore, settings: EcbSettings, start: date, end: date
) -> pd.DataFrame:
    """Fetch ECB reference rates (quote currency per EUR) for [start, end]."""
    labels = {key: ccy for ccy, key in settings.fx.keys.items()}
    return _fetch(client, store, settings, "fx", settings.fx.flow, labels, start, end)


def fetch_rating_curves(
    client: HttpClient, store: RawStore, settings: EcbSettings, start: date, end: date
) -> pd.DataFrame:
    """Fetch AAA and all-ratings published spot rates (series ``AAA:SR_5Y``, ``ALL:SR_5Y``)."""
    rc = settings.rating_curves
    labels = {
        f"{prefix}.{t}": f"{name}:{t}" for name, prefix in rc.prefixes.items() for t in rc.tenors
    }
    return _fetch(client, store, settings, "rating_curves", rc.flow, labels, start, end)


def fetch_estr(
    client: HttpClient, store: RawStore, settings: EcbSettings, start: date, end: date
) -> pd.DataFrame:
    """Fetch the euro short-term rate (percent) for [start, end]."""
    labels = {settings.estr.key: "ESTR"}
    return _fetch(client, store, settings, "estr", settings.estr.flow, labels, start, end)
