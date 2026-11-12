"""Pydantic models for ``config/book.yaml`` (positions, frozen trade terms, dividends)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
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
    """An owner-provided dividend-yield assumption (ADR-019)."""

    value: float = Field(ge=0, lt=0.2)
    source: str
    date: date
    look_ahead: bool = False
    note: str | None = None


class Assumptions(_Model):
    """Owner-provided model assumptions."""

    dividend_yields: dict[str, DividendYield | None]


type AnySpec = SwapSpec | FxForwardSpec | OptionSpec


class Book(_Model):
    """The whole book."""

    reporting_currency: Literal["EUR"]
    trade_date: date
    swaps: tuple[SwapSpec, ...]
    fx_forwards: tuple[FxForwardSpec, ...]
    options: tuple[OptionSpec, ...]
    assumptions: Assumptions
    frozen_metadata: dict[str, object] | None = None

    def instruments(self) -> tuple[AnySpec, ...]:
        """All instrument specs in book order (swaps, FX forwards, options)."""
        return (*self.swaps, *self.fx_forwards, *self.options)

    @model_validator(mode="after")
    def _unique_ids(self) -> Book:
        ids = [x.id for x in self.instruments()]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate instrument ids: {ids}")
        missing = {o.underlying for o in self.options} - set(self.assumptions.dividend_yields)
        if missing:
            raise ValueError(f"assumptions.dividend_yields lacks entries for {sorted(missing)}")
        return self

    @property
    def is_frozen(self) -> bool:
        """True when init-book has frozen every instrument."""
        return all(x.frozen is not None for x in self.instruments())

    def available_dividend_yields(self) -> dict[str, float]:
        """Dividend yields that have been provided (None entries are skipped)."""
        return {k: v.value for k, v in self.assumptions.dividend_yields.items() if v is not None}


def yaml_round_trip() -> YAML:
    """ruamel.yaml instance that preserves comments and key order."""
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 100
    y.indent(mapping=2, sequence=4, offset=2)  # keep the "  - id:" list style of book.yaml
    return y


PRIVATE_SUFFIX = ".private.yaml"
DIGEST_KEY = "private_terms_sha256"


def private_terms_digest(options: Mapping[str, object]) -> str:
    """SHA-256 of the option frozen terms (canonical JSON). Reveals nothing about them.

    Stored in book.yaml ``frozen_metadata`` so that a wrong or corrupted private file (e.g. a
    mistyped GitHub secret) is detected instead of silently pricing other strikes.
    """
    canonical = json.dumps(options, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


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
        meta = raw.get("frozen_metadata") or {}
        expected = meta.get(DIGEST_KEY) if isinstance(meta, dict) else None
        if expected is not None and private_terms_digest(frozen) != expected:
            raise ValueError(
                f"{priv.name} does not match {DIGEST_KEY} in {path.name}: wrong or corrupted "
                "private file (check the BOOK_PRIVATE_YAML_B64 secret)"
            )
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
