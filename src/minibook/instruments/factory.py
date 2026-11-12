"""Build immutable instruments from the validated book and settings."""

from __future__ import annotations

from functools import reduce

from minibook.config.book import Book, FxForwardSpec, OptionSpec, SwapSpec
from minibook.config.settings import Settings
from minibook.dates.calendars import CALENDARS, Calendar
from minibook.instruments.base import Instrument
from minibook.instruments.bsm import OptionType
from minibook.instruments.equity_option import EquityOption
from minibook.instruments.fx_forward import FxConvention, FxForward
from minibook.instruments.swap import InterestRateSwap


class BookNotFrozenError(RuntimeError):
    """The book has instruments without frozen terms: run ``minibook init-book``."""


def _joint(names: tuple[str, ...]) -> Calendar:
    return reduce(lambda a, b: a + b, (CALENDARS[n] for n in names))


def fx_convention(settings: Settings, pair: str) -> FxConvention:
    """Spot-date convention of ``pair`` from settings."""
    try:
        c = settings.fx_conventions[pair]
    except KeyError as exc:
        raise KeyError(f"no fx_conventions entry for {pair}") from exc
    return FxConvention(c.spot_lag, _joint(c.lag_calendars), _joint(c.settlement_calendars))


def make_swap(spec: SwapSpec, book: Book, fixed_rate: float | None = None) -> InterestRateSwap:
    """Swap from its spec; ``fixed_rate`` overrides the frozen rate (used by init-book)."""
    if fixed_rate is None:
        if spec.frozen is None:
            raise _not_frozen(spec.id)
        fixed_rate = spec.frozen.fixed_rate
    rate = fixed_rate
    return InterestRateSwap.create(
        id=spec.id,
        trade_date=book.trade_date,
        notional=spec.notional,
        fixed_rate=rate,
        pay_fixed=spec.pay_fixed,
        tenor=spec.tenor,
        fixed_frequency=spec.fixed_frequency,
        float_frequency=spec.float_frequency,
        spot_lag=spec.spot_lag,
        fixing_lag=spec.fixing_lag,
        index=spec.index,
    )


def make_fx_forward(spec: FxForwardSpec, settings: Settings) -> FxForward:
    """FX forward from its (frozen) spec."""
    f = spec.frozen
    if f is None:
        raise _not_frozen(spec.id)
    return FxForward(
        spec.id,
        spec.base,
        spec.quote,
        spec.base_notional,
        f.strike,
        f.delivery,
        fx_convention(settings, spec.pair),
    )


def make_option(spec: OptionSpec) -> EquityOption:
    """Option from its (frozen) spec."""
    f = spec.frozen
    if f is None:
        raise _not_frozen(spec.id)
    return EquityOption(
        spec.id,
        spec.underlying,
        OptionType(spec.option_type),
        spec.quantity,
        spec.multiplier,
        f.strike,
        f.expiry,
    )


def _not_frozen(spec_id: str) -> BookNotFrozenError:
    return BookNotFrozenError(f"{spec_id} has no frozen terms: run `minibook init-book`")


def build_instruments(book: Book, settings: Settings) -> list[Instrument]:
    """All instruments of a frozen book, in book order."""
    out: list[Instrument] = [make_swap(s, book) for s in book.swaps]
    out += [make_fx_forward(f, settings) for f in book.fx_forwards]
    out += [make_option(o) for o in book.options]
    return out
