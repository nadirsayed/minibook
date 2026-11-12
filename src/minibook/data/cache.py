"""On-disk raw cache: original payloads plus a normalized long-format parquet per dataset.

Layout under ``raw_dir``::

    <source>/<dataset>/payloads/<YYYYmmddTHHMMSSffffffZ>_<sha12><suffix>.gz   original body
    <source>/<dataset>/payloads/<same stem>.meta.json                        url, status, sha256
    <source>/<dataset>.parquet                                               normalized observations
    <source>/<dataset>.revisions.parquet                                     superseded values

Normalized schema (one row per observation date and series):

    obs_date (date) | series (str) | value (float64)
    first_fetched_utc | last_fetched_utc (UTC timestamps) | payload (str, relative path)

``first_fetched_utc`` is the first time the current value was seen. It is what lets a
backfilled report disclose that its data was fetched after the report date. A changed value
is a *revision*: the old row moves to the revisions file, the new value gets a fresh
``first_fetched_utc``, and a warning is logged. Nothing is ever dropped silently.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from minibook.data.http import FetchResult

LOG = logging.getLogger(__name__)

OBS_COLUMNS = ("obs_date", "series", "value")
STORE_COLUMNS = (*OBS_COLUMNS, "first_fetched_utc", "last_fetched_utc", "payload")
SHA_PREFIX_LEN = 12


@dataclass(frozen=True)
class UpsertReport:
    """Counts from one :meth:`RawStore.upsert` call."""

    added: int
    unchanged: int
    revised: int


def _empty_store() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "obs_date": pd.Series(dtype="object"),
            "series": pd.Series(dtype="object"),
            "value": pd.Series(dtype="float64"),
            "first_fetched_utc": pd.Series(dtype="datetime64[us, UTC]"),
            "last_fetched_utc": pd.Series(dtype="datetime64[us, UTC]"),
            "payload": pd.Series(dtype="object"),
        }
    )


class RawStore:
    """Raw payload archive and normalized observation store.

    Parameters
    ----------
    root
        Root directory (``settings.data.raw_dir``).
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    # ------------------------------------------------------------------ payloads
    def save_payload(self, source: str, dataset: str, result: FetchResult, suffix: str) -> Path:
        """Archive one response body (gzip) with a JSON metadata sidecar.

        Returns the payload path relative to ``root``.
        """
        sha = hashlib.sha256(result.content).hexdigest()
        stamp = result.fetched_at.strftime("%Y%m%dT%H%M%S%fZ")
        directory = self.root / source / dataset / "payloads"
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{stamp}_{sha[:SHA_PREFIX_LEN]}"
        path = directory / f"{stem}{suffix}.gz"
        # mtime=0 keeps the gzip bytes deterministic for identical content.
        with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            gz.write(result.content)
        meta = {
            "url": result.url,
            "status": result.status,
            "content_type": result.content_type,
            "fetched_at_utc": result.fetched_at.isoformat(),
            "sha256": sha,
            "bytes": len(result.content),
        }
        (directory / f"{stem}.meta.json").write_text(json.dumps(meta, indent=2) + "\n")
        return path.relative_to(self.root)

    def read_payload(self, relative: Path) -> bytes:
        """Return the decompressed body of an archived payload."""
        with gzip.open(self.root / relative, "rb") as gz:
            return gz.read()

    # ------------------------------------------------------------------ observations
    def _store_path(self, source: str, dataset: str) -> Path:
        return self.root / source / f"{dataset}.parquet"

    def _revisions_path(self, source: str, dataset: str) -> Path:
        return self.root / source / f"{dataset}.revisions.parquet"

    def load(self, source: str, dataset: str) -> pd.DataFrame:
        """Load the normalized store (empty frame with the store schema if absent)."""
        path = self._store_path(source, dataset)
        if not path.exists():
            return _empty_store()
        df = pd.read_parquet(path)
        df["obs_date"] = pd.to_datetime(df["obs_date"]).dt.date
        return df

    def load_wide(self, source: str, dataset: str, as_of: date | None = None) -> pd.DataFrame:
        """Return values as a wide frame: index = obs_date (Timestamp), columns = series.

        If ``as_of`` is given, observations dated after it are removed (no look-ahead).
        """
        df = self.load(source, dataset)
        if as_of is not None:
            df = df.loc[df["obs_date"] <= as_of]
        # pivot (not pivot_table): keys are unique by construction, and pivot raises on
        # duplicates instead of silently aggregating them.
        wide = df.pivot(index="obs_date", columns="series", values="value")  # noqa: PD010
        wide.index = pd.to_datetime(wide.index)
        wide.columns.name = None
        return wide.sort_index()

    def upsert(
        self,
        source: str,
        dataset: str,
        obs: pd.DataFrame,
        fetched_at: datetime,
        payload: Path,
    ) -> UpsertReport:
        """Merge new observations into the store.

        Parameters
        ----------
        obs
            Columns ``obs_date`` (date), ``series`` (str), ``value`` (float). NaNs must be
            removed by the caller: a missing observation is "no data", not a value.
        fetched_at
            Fetch time of the payload the observations were parsed from (UTC).
        payload
            Relative path of that payload (from :meth:`save_payload`).

        Returns
        -------
        UpsertReport
            How many rows were added, unchanged or revised.
        """
        missing = set(OBS_COLUMNS) - set(obs.columns)
        if missing:
            raise ValueError(f"observations missing columns {sorted(missing)}")
        if obs["value"].isna().any():
            raise ValueError("observations contain NaN values; drop them before upsert")
        if obs.duplicated(["obs_date", "series"]).any():
            raise ValueError("duplicate (obs_date, series) in observations")

        ts = pd.Timestamp(fetched_at).tz_convert("UTC")
        new = obs.loc[:, list(OBS_COLUMNS)].copy()
        new["value"] = new["value"].astype("float64")
        old = self.load(source, dataset)
        merged = new.merge(
            old, on=["obs_date", "series"], how="left", suffixes=("", "_old"), indicator=True
        )

        is_new = merged["_merge"] == "left_only"
        is_same = ~is_new & (merged["value"] == merged["value_old"])
        is_rev = ~is_new & ~is_same

        if is_rev.any():
            revs = merged.loc[is_rev]
            for row in revs.itertuples():
                LOG.warning(
                    "%s/%s revision %s %s: %r -> %r",
                    source,
                    dataset,
                    row.obs_date,
                    row.series,
                    row.value_old,
                    row.value,
                )
            superseded = old.merge(revs[["obs_date", "series"]], on=["obs_date", "series"])
            superseded = superseded.assign(superseded_utc=ts)
            rev_path = self._revisions_path(source, dataset)
            if rev_path.exists():
                superseded = pd.concat([pd.read_parquet(rev_path), superseded], ignore_index=True)
            superseded.to_parquet(rev_path, index=False)

        merged["first_fetched_utc"] = merged["first_fetched_utc"].where(is_same, ts)
        merged["last_fetched_utc"] = ts
        merged["payload"] = merged["payload"].where(is_same, str(payload))
        updated = merged.loc[:, list(STORE_COLUMNS)]

        untouched = old.merge(
            new[["obs_date", "series"]], on=["obs_date", "series"], how="left", indicator=True
        )
        untouched = untouched.loc[untouched["_merge"] == "left_only", list(STORE_COLUMNS)]
        frames = [f for f in (untouched, updated) if not f.empty]
        out = pd.concat(frames, ignore_index=True) if frames else _empty_store()
        out = out.sort_values(["series", "obs_date"], kind="stable").reset_index(drop=True)

        path = self._store_path(source, dataset)
        path.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(path, index=False)
        report = UpsertReport(int(is_new.sum()), int(is_same.sum()), int(is_rev.sum()))
        LOG.info("%s/%s upsert: %s", source, dataset, report)
        return report
