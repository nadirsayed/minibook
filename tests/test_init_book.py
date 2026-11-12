"""init-book on recorded real rates/FX and SYNTHETIC equities, with a temporary book.yaml."""

from __future__ import annotations

import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from minibook.config.book import load_book
from minibook.config.settings import Settings
from minibook.data.cache import RawStore
from minibook.data.fixings import FixingStore
from minibook.init_book import FrozenTermsMismatchError, init_book
from minibook.instruments.factory import BookNotFrozenError, build_instruments
from minibook.market.builder import SnapshotBuilder
from tests.conftest import PLACEHOLDER_DIV_YIELDS_TESTS_ONLY, ROOT

TRADE = date(2026, 11, 2)
CLOCK = lambda: datetime(2026, 11, 12, 15, 0, tzinfo=UTC)  # noqa: E731


@pytest.fixture
def book_path(tmp_path: Path) -> Path:
    path = tmp_path / "book.yaml"
    shutil.copy(ROOT / "tests" / "fixtures" / "book_template.yaml", path)  # unfrozen copy
    return path


def run(book_path: Path, market_store: RawStore, settings: Settings, tmp_path: Path) -> str:
    builder = SnapshotBuilder(market_store, settings)
    return init_book(
        book_path, settings, builder.build, FixingStore(tmp_path / "fixings"), TRADE, CLOCK
    )


def test_freeze_then_verify(
    book_path: Path, market_store: RawStore, settings: Settings, tmp_path: Path
) -> None:
    with pytest.raises(BookNotFrozenError):
        build_instruments(load_book(book_path), settings)
    assert run(book_path, market_store, settings, tmp_path) == "frozen"
    text = book_path.read_text()
    assert "NOT listed-contract" in text and "frozen_metadata" in text  # comments kept
    # ADR-018: option terms (from equity closes) only in the git-ignored private file.
    private = book_path.with_name("book.private.yaml")
    assert private.exists() and "strike" in private.read_text()
    options_part = text[text.index("options:") : text.index("dividend_yields:")]
    assert "strike:" not in options_part and "spot_at_trade" not in options_part
    book = load_book(book_path)
    assert book.is_frozen
    snap = SnapshotBuilder(market_store, settings).build(TRADE, PLACEHOLDER_DIV_YIELDS_TESTS_ONLY)
    snap = snap.with_fixings(FixingStore(tmp_path / "fixings").as_of(["EURIBOR6M"], TRADE))
    instruments = {i.id: i for i in build_instruments(book, settings)}
    assert abs(instruments["IRS_EUR_5Y"].pv(snap)) < 1.0
    assert abs(instruments["FXF_EURUSD_6M"].pv(snap)) < 1e-6
    assert abs(instruments["FXF_USDJPY_3M"].pv(snap)) < 1e-6
    fx = {f.id: f.frozen for f in book.fx_forwards}
    assert fx["FXF_EURUSD_6M"].delivery == date(2027, 5, 4)  # type: ignore[union-attr]
    assert fx["FXF_USDJPY_3M"].spot_date == date(2026, 11, 5)  # type: ignore[union-attr]
    for o in book.options:
        assert o.frozen is not None
        assert o.frozen.strike == pytest.approx(o.strike_pct * snap.spots[o.underlying])
    expiries = {o.id: o.frozen.expiry for o in book.options if o.frozen}
    assert expiries["OPT_SX5E_C_3M_100"] == date(2027, 2, 2)
    assert expiries["OPT_DAX_P_6M_95"] == date(2027, 5, 3)
    fixings = FixingStore(tmp_path / "fixings").load("EURIBOR6M")
    assert list(fixings) == [TRADE]

    before = book_path.read_bytes()
    assert run(book_path, market_store, settings, tmp_path) == "verified"
    assert book_path.read_bytes() == before  # idempotent: nothing rewritten


def test_mismatch_and_wrong_date(
    book_path: Path, market_store: RawStore, settings: Settings, tmp_path: Path
) -> None:
    run(book_path, market_store, settings, tmp_path)
    private = book_path.with_name("book.private.yaml")  # option terms live here (ADR-018)
    text = private.read_text()
    book = load_book(book_path)
    strike = book.options[1].frozen.strike  # type: ignore[union-attr]  # DAX 95%: unique value
    private.write_text(text.replace(repr(strike), repr(strike + 1.0), 1))
    with pytest.raises(FrozenTermsMismatchError, match="strike"):
        run(book_path, market_store, settings, tmp_path)
    with pytest.raises(ValueError, match=r"differs from book\.yaml"):
        init_book(
            book_path,
            settings,
            SnapshotBuilder(market_store, settings).build,
            FixingStore(tmp_path / "f2"),
            date(2026, 11, 3),
            CLOCK,
        )


def test_option_terms_refused_in_public_book(
    book_path: Path, market_store: RawStore, settings: Settings, tmp_path: Path
) -> None:
    run(book_path, market_store, settings, tmp_path)
    text = book_path.read_text()
    leaked = text.replace(
        "    multiplier: 10             # EUR per index point (Eurex OESX)\n    frozen:\n",
        "    multiplier: 10             # EUR per index point (Eurex OESX)\n    frozen:\n"
        "      spot_at_trade: 1.0\n      strike: 1.0\n      expiry: 2027-02-02\n",
        1,
    )
    assert leaked != text
    book_path.write_text(leaked)
    with pytest.raises(ValueError, match=r"must not be in book\.yaml"):
        load_book(book_path)
