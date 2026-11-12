"""``minibook init-book``: freeze trade terms at the trade date.

From the trade-date :class:`MarketSnapshot` it computes:

* swap: effective/maturity dates and fixed rate = par rate (PV_float / annuity);
* FX forwards: spot date, delivery date, strike = outright forward;
* options: expiry (trade date + tenor, modified following on the exchange calendar) and
  strike = strike_pct x index close on the trade date.

It also records the EURIBOR proxy fixings dated on the trade date in the fixing store.

Idempotency: if the book is already frozen, the terms are recomputed and compared
(relative tolerance ``VERIFY_RTOL``). Equal: nothing is written. Different: an error, because
frozen terms are never silently changed (a data revision since freezing would show up here).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from ruamel.yaml.comments import CommentedMap

from minibook.config.book import (
    DIGEST_KEY,
    Book,
    FxFrozen,
    OptionFrozen,
    SwapFrozen,
    load_book,
    private_path,
    private_terms_digest,
    yaml_round_trip,
)
from minibook.config.settings import Settings
from minibook.data.fixings import FixingRecord, FixingStore
from minibook.data.http import utc_now
from minibook.dates.calendars import CALENDARS, BusinessDayConvention
from minibook.dates.tenor import Tenor, add_tenor
from minibook.fixing_service import due_fixing_records
from minibook.instruments.factory import fx_convention, make_swap
from minibook.instruments.fx_forward import FxForward
from minibook.market.snapshot import MarketSnapshot

LOG = logging.getLogger(__name__)
VERIFY_RTOL = 1e-12


class FrozenTermsMismatchError(RuntimeError):
    """Recomputed terms differ from the terms already frozen in book.yaml."""


@dataclass(frozen=True)
class FrozenTerms:
    """Everything init-book freezes."""

    swaps: dict[str, SwapFrozen]
    fx_forwards: dict[str, FxFrozen]
    options: dict[str, OptionFrozen]
    fixings: list[FixingRecord] = field(default_factory=list)


def compute_frozen_terms(
    book: Book, settings: Settings, snap: MarketSnapshot, recorded_at: datetime
) -> FrozenTerms:
    """Compute frozen terms from the trade-date snapshot (pure, no I/O)."""
    if snap.as_of != book.trade_date:
        raise ValueError(f"snapshot {snap.as_of} is not the trade date {book.trade_date}")
    swaps: dict[str, SwapFrozen] = {}
    fixings: list[FixingRecord] = []
    for spec in book.swaps:
        swap = make_swap(spec, book, fixed_rate=0.0)
        swaps[spec.id] = SwapFrozen(
            fixed_rate=swap.par_rate(snap), effective=swap.effective, maturity=swap.maturity
        )
        fixings += due_fixing_records([swap], snap, recorded_at)
    fx: dict[str, FxFrozen] = {}
    for f in book.fx_forwards:
        conv = fx_convention(settings, f.pair)
        spot = conv.spot_date(book.trade_date)
        delivery = conv.delivery_date(spot, Tenor.parse(f.tenor))
        fwd = FxForward(f.id, f.base, f.quote, f.base_notional, 1.0, delivery, conv)
        fx[f.id] = FxFrozen(
            spot_at_trade=snap.fx_rate(f.base, f.quote),
            spot_date=spot,
            delivery=delivery,
            strike=fwd.forward_rate(snap),
        )
    options: dict[str, OptionFrozen] = {}
    for o in book.options:
        cal = CALENDARS[settings.equities.calendars[o.underlying]]
        expiry = add_tenor(
            book.trade_date, Tenor.parse(o.tenor), cal, BusinessDayConvention.MODIFIED_FOLLOWING
        )
        level = float(snap.spots[o.underlying])
        options[o.id] = OptionFrozen(
            spot_at_trade=level, strike=o.strike_pct * level, expiry=expiry
        )
    return FrozenTerms(swaps, fx, options, fixings)


def _differences(book: Book, terms: FrozenTerms) -> list[str]:
    diffs = []
    stored = {x.id: x.frozen for x in book.instruments()}
    computed: dict[str, SwapFrozen | FxFrozen | OptionFrozen] = {
        **terms.swaps,
        **terms.fx_forwards,
        **terms.options,
    }
    for iid, new in computed.items():
        old = stored[iid]
        if old is None:
            diffs.append(f"{iid}: not frozen")
            continue
        for name, value in new.model_dump().items():
            prev = getattr(old, name)
            same = (
                math.isclose(prev, value, rel_tol=VERIFY_RTOL, abs_tol=0.0)
                if isinstance(value, float)
                else prev == value
            )
            if not same:
                diffs.append(f"{iid}.{name}: stored {prev!r}, recomputed {value!r}")
    return diffs


def _write(path: Path, terms: FrozenTerms, snap: MarketSnapshot, recorded_at: datetime) -> None:
    y = yaml_round_trip()
    with path.open(encoding="utf-8") as fh:
        doc = y.load(fh)
    computed: dict[str, SwapFrozen | FxFrozen | OptionFrozen] = {
        **terms.swaps,
        **terms.fx_forwards,
        **terms.options,
    }
    for section in ("swaps", "fx_forwards"):
        for item in doc[section]:
            item["frozen"] = CommentedMap(computed[item["id"]].model_dump())
    # Option terms are derived from Yahoo closes: git-ignored private file (ADR-018).
    private = CommentedMap(
        {
            "note": "Generated by minibook init-book from Yahoo index closes: never commit.",
            "options": CommentedMap(
                {k: CommentedMap(v.model_dump()) for k, v in terms.options.items()}
            ),
        }
    )
    with private_path(path).open("w", encoding="utf-8") as fh:
        y.dump(private, fh)
    doc["frozen_metadata"] = CommentedMap(
        {
            "by": "minibook init-book",
            "trade_date": snap.as_of,
            "computed_at_utc": recorded_at.isoformat(),
            "market_data_first_fetched_utc": dict(snap.data_timestamps),
            "forward_fills": [
                f"{f.dataset} {f.series}: {f.obs_date} ({f.age_days}d) {f.reason}"
                for f in snap.fills
            ],
            "quality_flags": [f"{q.code}: {q.message}" for q in snap.quality_flags],
            DIGEST_KEY: private_terms_digest({k: v.model_dump() for k, v in terms.options.items()}),
        }
    )
    with path.open("w", encoding="utf-8") as fh:
        y.dump(doc, fh)


def init_book(
    book_path: Path,
    settings: Settings,
    snapshot_for: Callable[[date], MarketSnapshot],
    fixing_store: FixingStore,
    trade_date: date,
    clock: Callable[[], datetime] = utc_now,
) -> str:
    """Freeze (or verify) the book at ``trade_date``. Return ``"frozen"`` or ``"verified"``.

    Parameters
    ----------
    book_path
        Path of book.yaml (rewritten in place, comments preserved, on first freeze).
    snapshot_for
        Callable returning the market snapshot of a date (no dividends needed).
    fixing_store
        Store receiving the trade-date EURIBOR proxy fixing(s).
    trade_date
        Must equal ``trade_date`` in book.yaml.
    """
    book = load_book(book_path)
    if trade_date != book.trade_date:
        raise ValueError(f"--trade-date {trade_date} differs from book.yaml {book.trade_date}")
    snap = snapshot_for(trade_date)
    now = clock()
    terms = compute_frozen_terms(book, settings, snap, now)
    any_frozen = any(x.frozen is not None for x in book.instruments())
    if any_frozen:
        diffs = _differences(book, terms)
        if diffs:
            raise FrozenTermsMismatchError("frozen terms differ:\n  " + "\n  ".join(diffs))
        for rec in terms.fixings:
            fixing_store.record(rec)  # no-op if identical; raises if conflicting
        LOG.info("book already frozen at %s: terms verified", trade_date)
        return "verified"
    for rec in terms.fixings:
        fixing_store.record(rec)
    _write(book_path, terms, snap, now)
    reloaded = load_book(book_path)
    if _differences(reloaded, terms):
        raise RuntimeError("book.yaml round-trip changed frozen values")
    LOG.info("book frozen at %s: %s", trade_date, book_path)
    return "frozen"
