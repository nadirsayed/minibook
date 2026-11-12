"""Record the index fixings due on a valuation date (ADR-016).

On each run date the coupons fixing that day get their curve-implied proxy from that day's
snapshot, and it is written once to the immutable fixing store. Later runs read it back and
never recompute it. ``init-book`` uses the same function for the trade-date fixing.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from minibook.data.fixings import FixingRecord, FixingStore
from minibook.instruments.base import Instrument
from minibook.instruments.swap import InterestRateSwap
from minibook.market.snapshot import MarketSnapshot

FIXING_METHOD = "EUR AAA curve ACT/360 forward over the accrual period (proxy, ADR-016)"


def due_fixing_records(
    instruments: Iterable[Instrument], market: MarketSnapshot, recorded_at: datetime
) -> list[FixingRecord]:
    """Return fixing records for every coupon fixing on ``market.as_of`` (curve proxy)."""
    out: dict[tuple[str, object], FixingRecord] = {}
    for inst in instruments:
        if not isinstance(inst, InterestRateSwap):
            continue
        for c in inst.float_coupons:
            if c.fixing_date != market.as_of:
                continue
            out[(inst.index, c.fixing_date)] = FixingRecord(
                index=inst.index,
                fixing_date=c.fixing_date,
                rate=inst.projected_rate(c, market),
                accrual_start=c.period.start,
                accrual_end=c.period.end,
                curve_as_of=market.as_of,
                method=FIXING_METHOD,
                recorded_at_utc=recorded_at.isoformat(),
            )
    return list(out.values())


def record_due_fixings(
    instruments: Iterable[Instrument],
    market: MarketSnapshot,
    store: FixingStore,
    recorded_at: datetime,
) -> MarketSnapshot:
    """Record today's fixings in ``store`` and return ``market`` with them set.

    Recording is idempotent (identical value: no-op) and immutable (different value: error).
    """
    records = due_fixing_records(instruments, market, recorded_at)
    for rec in records:
        store.record(rec)
    if not records:
        return market
    return market.with_fixings(
        {**market.fixings, **{(r.index, r.fixing_date): r.rate for r in records}}
    )
