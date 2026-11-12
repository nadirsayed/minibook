from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from minibook.data.fixings import FixingConflictError, FixingRecord, FixingStore


def rec(rate: float, d: date = date(2026, 11, 2), curve: date | None = None) -> FixingRecord:
    """SYNTHETIC fixing record."""
    return FixingRecord(
        "EURIBOR6M",
        d,
        rate,
        date(2026, 11, 4),
        date(2027, 5, 4),
        curve or d,
        "test",
        "2026-11-12T00:00:00+00:00",
    )


def test_record_is_append_only_and_exact(tmp_path: Path) -> None:
    store = FixingStore(tmp_path)
    rate = 0.1 + 0.2  # not exactly representable in short decimal: tests repr round-trip
    assert store.record(rec(rate)) is True
    assert store.record(rec(rate)) is False  # identical: no-op
    assert store.load("EURIBOR6M")[date(2026, 11, 2)].rate == rate
    with pytest.raises(FixingConflictError, match="refusing to overwrite"):
        store.record(rec(rate + 1e-9))
    assert len((tmp_path / "EURIBOR6M_proxy.csv").read_text().splitlines()) == 2


def test_proxy_must_use_fixing_date_curve(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="curve of its fixing date"):
        FixingStore(tmp_path).record(rec(0.02, curve=date(2026, 11, 3)))


def test_as_of_filters_future(tmp_path: Path) -> None:
    store = FixingStore(tmp_path)
    store.record(rec(0.02))
    store.record(rec(0.021, d=date(2027, 4, 30)))
    assert store.as_of(["EURIBOR6M"], date(2026, 12, 31)) == {
        ("EURIBOR6M", date(2026, 11, 2)): 0.02
    }
    assert store.load("OTHER") == {}
