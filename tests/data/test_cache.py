from __future__ import annotations

import gzip
import logging
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from minibook.data.cache import RawStore
from minibook.data.http import FetchResult

T1 = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
T2 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def obs(rows: list[tuple[date, str, float]]) -> pd.DataFrame:
    """Synthetic observations."""
    return pd.DataFrame(rows, columns=["obs_date", "series", "value"])


def result(body: bytes, at: datetime = T1) -> FetchResult:
    return FetchResult("https://example.test/x", 200, body, at, "text/csv")


def test_payload_roundtrip_and_metadata(store: RawStore) -> None:
    rel = store.save_payload("src", "ds", result(b"a,b\n1,2\n"), ".csv")
    assert store.read_payload(rel) == b"a,b\n1,2\n"
    meta = (store.root / rel).with_name(rel.name.removesuffix(".csv.gz") + ".meta.json")
    assert '"sha256"' in meta.read_text()
    assert '"fetched_at_utc": "2026-11-03T12:00:00+00:00"' in meta.read_text()


def test_payload_gzip_is_deterministic(tmp_path: Path) -> None:
    a = RawStore(tmp_path / "a").save_payload("s", "d", result(b"xyz"), ".csv")
    b = RawStore(tmp_path / "b").save_payload("s", "d", result(b"xyz"), ".csv")
    assert (tmp_path / "a" / a).read_bytes() == (tmp_path / "b" / b).read_bytes()
    assert gzip.decompress((tmp_path / "a" / a).read_bytes()) == b"xyz"


def test_upsert_add_unchanged_revise(store: RawStore, caplog: pytest.LogCaptureFixture) -> None:
    d1, d2 = date(2026, 11, 2), date(2026, 11, 3)
    p = Path("p1")
    rep = store.upsert("s", "d", obs([(d1, "A", 1.0), (d1, "B", 2.0)]), T1, p)
    assert (rep.added, rep.unchanged, rep.revised) == (2, 0, 0)

    with caplog.at_level(logging.WARNING):
        rep = store.upsert(
            "s", "d", obs([(d1, "A", 1.0), (d1, "B", 2.5), (d2, "A", 3.0)]), T2, Path("p2")
        )
    assert (rep.added, rep.unchanged, rep.revised) == (1, 1, 1)
    assert "revision" in caplog.text

    df = store.load("s", "d").set_index(["obs_date", "series"])
    assert df.loc[(d1, "A"), "first_fetched_utc"] == pd.Timestamp(T1)
    assert df.loc[(d1, "A"), "last_fetched_utc"] == pd.Timestamp(T2)
    assert df.loc[(d1, "A"), "payload"] == "p1"
    assert df.loc[(d1, "B"), "value"] == 2.5
    assert df.loc[(d1, "B"), "first_fetched_utc"] == pd.Timestamp(T2)
    revs = pd.read_parquet(store.root / "s" / "d.revisions.parquet")
    assert list(revs["value"]) == [2.0]


def test_upsert_keeps_other_series(store: RawStore) -> None:
    d1 = date(2026, 11, 2)
    store.upsert("s", "d", obs([(d1, "A", 1.0)]), T1, Path("p"))
    store.upsert("s", "d", obs([(d1, "B", 2.0)]), T2, Path("q"))
    assert set(store.load("s", "d")["series"]) == {"A", "B"}


@pytest.mark.parametrize(
    ("frame", "msg"),
    [
        (pd.DataFrame({"obs_date": [date(2026, 1, 2)], "value": [1.0]}), "missing columns"),
        (obs([(date(2026, 1, 2), "A", float("nan"))]), "NaN"),
        (obs([(date(2026, 1, 2), "A", 1.0), (date(2026, 1, 2), "A", 1.0)]), "duplicate"),
    ],
)
def test_upsert_rejects_bad_input(store: RawStore, frame: pd.DataFrame, msg: str) -> None:
    with pytest.raises(ValueError, match=msg):
        store.upsert("s", "d", frame, T1, Path("p"))


def test_load_wide_as_of_drops_future(store: RawStore) -> None:
    rows = [(date(2026, 11, d), "A", float(d)) for d in (2, 3, 4)]
    store.upsert("s", "d", obs(rows), T1, Path("p"))
    wide = store.load_wide("s", "d", as_of=date(2026, 11, 3))
    assert list(wide.index.date) == [date(2026, 11, 2), date(2026, 11, 3)]
    assert list(wide.columns) == ["A"]
    assert store.load_wide("missing", "x").empty
