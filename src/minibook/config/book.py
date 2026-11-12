"""Pydantic models for ``config/book.yaml`` (positions, frozen trade terms, dividends)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from ruamel.yaml import YAML

DEFAULT_BOOK_PATH = Path("config/book.yaml")


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SwapFrozen(_Model):
    """Swap terms fixed at the trade date by init-book."""

    fixed_rate: float
    effective: date
    maturity: date


class SwapSpec(_Model):
    """EUR fixed-vs-EURIBOR swap (conventions in :mod:`minibook.instruments.swap`)."""

    id: str
    currency: Literal["EUR"]
    notional: float = Field(gt=0)
    pay_fixed: bool
    tenor: str
    spot_lag: int = Field(ge=0)
    fixed_frequency: str
    float_frequency: str
    index: str
    fixing_lag: int = Field(ge=0)
    frozen: SwapFrozen | None = None


class FxFrozen(_Model):
    """FX forward terms fixed at the trade date by init-book."""

    spot_at_trade: float = Field(gt=0)
    spot_date: date
    delivery: date
    strike: float = Field(gt=0)


class FxForwardSpec(_Model):
    """Outright FX forward; ``base_notional`` is signed (+ buy base)."""

    id: str
    base: str
    quote: str
    base_notional: float
    tenor: str
    frozen: FxFrozen | None = None

    @property
    def pair(self) -> str:
        """Pair code, e.g. ``"EURUSD"``."""
        return f"{self.base}{self.quote}"


class OptionFrozen(_Model):
    """Option terms fixed at the trade date by init-book."""

    spot_at_trade: float = Field(gt=0)
    strike: float = Field(gt=0)
    expiry: date


class OptionSpec(_Model):
    """Hypothetical European cash-settled index option; ``quantity`` signed contracts."""

    id: str
    underlying: str
    option_type: Literal["call", "put"]
    quantity: float
    tenor: str
    strike_pct: float = Field(gt=0)
    multiplier: float = Field(gt=0)
    frozen: OptionFrozen | None = None


class DividendYield(_Model):
    """A trailing dividend yield with its provenance (owner input)."""

    value: float = Field(ge=0, lt=0.2)
    definition: str | None = None
    source: str | None = None
    url: str | None = None
    data_as_of: date | None = None
    published: date | None = None
    look_ahead: bool = False
    note: str | None = None


type AnySpec = SwapSpec | FxForwardSpec | OptionSpec


class Book(_Model):
    """The whole book."""

    reporting_currency: Literal["EUR"]
    trade_date: date
    swaps: tuple[SwapSpec, ...]
    fx_forwards: tuple[FxForwardSpec, ...]
    options: tuple[OptionSpec, ...]
    dividend_yields: dict[str, DividendYield | None]
    frozen_metadata: dict[str, object] | None = None

    def instruments(self) -> tuple[AnySpec, ...]:
        """All instrument specs in book order (swaps, FX forwards, options)."""
        return (*self.swaps, *self.fx_forwards, *self.options)

    @model_validator(mode="after")
    def _unique_ids(self) -> Book:
        ids = [x.id for x in self.instruments()]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate instrument ids: {ids}")
        missing = {o.underlying for o in self.options} - set(self.dividend_yields)
        if missing:
            raise ValueError(f"dividend_yields lacks entries for {sorted(missing)}")
        return self

    @property
    def is_frozen(self) -> bool:
        """True when init-book has frozen every instrument."""
        return all(x.frozen is not None for x in self.instruments())

    def available_dividend_yields(self) -> dict[str, float]:
        """Dividend yields that have been provided (None entries are skipped)."""
        return {k: v.value for k, v in self.dividend_yields.items() if v is not None}


def yaml_round_trip() -> YAML:
    """ruamel.yaml instance that preserves comments and key order."""
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 100
    y.indent(mapping=2, sequence=4, offset=2)  # keep the "  - id:" list style of book.yaml
    return y


PRIVATE_SUFFIX = ".private.yaml"


def private_path(book_path: Path) -> Path:
    """Git-ignored sibling holding option terms derived from Yahoo closes (ADR-018).

    ``config/book.yaml`` -> ``config/book.private.yaml``.
    """
    return book_path.with_name(book_path.stem + PRIVATE_SUFFIX)


def load_book(path: Path = DEFAULT_BOOK_PATH) -> Book:
    """Load and validate the book, merging option frozen terms from the private file.

    Option strikes and spots come from Yahoo index closes, which are never committed to the
    public repository (ADR-014, ADR-018). init-book writes them to the git-ignored
    ``book.private.yaml`` next to ``book.yaml``. Without that file, options are not frozen.
    """
    y = yaml_round_trip()
    with path.open(encoding="utf-8") as fh:
        raw = _plain(y.load(fh))
    priv = private_path(path)
    if priv.exists() and isinstance(raw, dict):
        with priv.open(encoding="utf-8") as fh:
            private = _plain(y.load(fh))
        frozen = private.get("options", {}) if isinstance(private, dict) else {}
        for item in raw.get("options", []):
            if item.get("frozen") is not None:
                raise ValueError(f"{item['id']}: option terms must not be in {path.name}")
            item["frozen"] = frozen.get(item["id"])
    return Book.model_validate(raw)


def _plain(obj: object) -> object:
    """Convert ruamel containers and scalar subclasses into plain Python for pydantic.

    bool is checked before int (bool subclasses int), and dates are kept as they are.
    """
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    if isinstance(obj, bool | date):
        return obj
    if isinstance(obj, float):
        return float(obj)
    if isinstance(obj, int):
        return int(obj)
    return str(obj) if isinstance(obj, str) else obj
