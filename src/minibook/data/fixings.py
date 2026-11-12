"""Immutable store of index fixings (EURIBOR 6M curve-implied proxy).

Real EURIBOR fixings are licensed data, so minibook uses a documented proxy: the simply
compounded ACT/360 forward over the coupon's accrual period, implied by the EUR curve *of
the fixing date* (see :mod:`minibook.instruments.swap`). It is recorded once, on its fixing
date, and never recomputed from a later curve.

File: ``<directory>/<INDEX>_proxy.csv``, append-only, committed to git (derived from ECB data,
reusable with attribution). Recording the same fixing again is a no-op if the value is
identical. A different value raises :class:`FixingConflictError`.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import asdict, dataclass, fields
from datetime import date
from pathlib import Path

LOG = logging.getLogger(__name__)
RATE_TOL = 1e-15  # identical up to float round-trip through CSV (repr is exact)


class FixingConflictError(RuntimeError):
    """An attempt to overwrite a stored fixing with a different value."""


@dataclass(frozen=True)
class FixingRecord:
    """One recorded fixing and its provenance."""

    index: str
    fixing_date: date
    rate: float
    accrual_start: date
    accrual_end: date
    curve_as_of: date
    method: str
    recorded_at_utc: str


class FixingStore:
    """Append-only CSV store of fixings, one file per index."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _path(self, index: str) -> Path:
        return self.directory / f"{index}_proxy.csv"

    def load(self, index: str) -> dict[date, FixingRecord]:
        """All stored fixings of ``index`` keyed by fixing date."""
        path = self._path(index)
        if not path.exists():
            return {}
        out: dict[date, FixingRecord] = {}
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                rec = FixingRecord(
                    index=row["index"],
                    fixing_date=date.fromisoformat(row["fixing_date"]),
                    rate=float(row["rate"]),
                    accrual_start=date.fromisoformat(row["accrual_start"]),
                    accrual_end=date.fromisoformat(row["accrual_end"]),
                    curve_as_of=date.fromisoformat(row["curve_as_of"]),
                    method=row["method"],
                    recorded_at_utc=row["recorded_at_utc"],
                )
                out[rec.fixing_date] = rec
        return out

    def as_of(self, indices: list[str], as_of: date) -> dict[tuple[str, date], float]:
        """Return fixings of ``indices`` dated on or before ``as_of`` (for MarketSnapshot)."""
        return {
            (idx, d): rec.rate for idx in indices for d, rec in self.load(idx).items() if d <= as_of
        }

    def record(self, rec: FixingRecord) -> bool:
        """Append ``rec``. Return True if written, False if an identical one exists.

        Raises
        ------
        FixingConflictError
            If a fixing for that date exists with a different rate.
        """
        if rec.curve_as_of != rec.fixing_date:
            raise ValueError("a fixing proxy must come from the curve of its fixing date")
        existing = self.load(rec.index).get(rec.fixing_date)
        if existing is not None:
            if abs(existing.rate - rec.rate) <= RATE_TOL:
                return False
            raise FixingConflictError(
                f"{rec.index} {rec.fixing_date}: stored {existing.rate!r} "
                f"(recorded {existing.recorded_at_utc}), refusing to overwrite with {rec.rate!r}"
            )
        path = self._path(rec.index)
        path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=[f.name for f in fields(FixingRecord)], lineterminator="\n"
            )
            if new_file:
                writer.writeheader()
            row = asdict(rec)
            row["rate"] = repr(rec.rate)
            writer.writerow(row)
        LOG.info("recorded fixing %s %s = %r", rec.index, rec.fixing_date, rec.rate)
        return True
