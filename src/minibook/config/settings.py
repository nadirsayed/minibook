"""Pydantic models for ``config/settings.yaml``.

The settings file holds every tunable number and every source URL / series key, so that
code contains no magic numbers. Models are frozen: settings are read once per run.
"""

from __future__ import annotations

from datetime import date, time
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat

DEFAULT_SETTINGS_PATH = Path("config/settings.yaml")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DataSettings(_Frozen):
    """Location of the raw cache and start of the history window."""

    raw_dir: Path
    history_start: date


class HttpSettings(_Frozen):
    """HTTP client behaviour.

    Retries use exponential backoff: wait_k = backoff_initial_s * backoff_factor**k,
    for k = 0 .. max_retries - 1.
    """

    timeout_s: PositiveFloat
    max_retries: int = Field(ge=0)
    backoff_initial_s: float = Field(ge=0.0)
    backoff_factor: float = Field(ge=1.0)
    user_agent: str


class EcbYieldCurveSettings(_Frozen):
    """ECB YC dataflow: Svensson parameters and published spot rates for validation."""

    flow: str
    key_prefix: str
    params: tuple[str, ...]
    validation: tuple[str, ...]


class EcbFxSettings(_Frozen):
    """ECB EXR dataflow: series keys per quote currency (units per 1 EUR)."""

    flow: str
    keys: dict[str, str]


class EcbEstrSettings(_Frozen):
    """ECB EST dataflow: euro short-term rate."""

    flow: str
    key: str


class EcbSettings(_Frozen):
    """ECB Data Portal settings."""

    base_url: str
    yield_curve: EcbYieldCurveSettings
    fx: EcbFxSettings
    estr: EcbEstrSettings


class FredSettings(_Frozen):
    """FRED CSV endpoint and series ids per tenor label."""

    url: str
    series: dict[str, str]


class MofSettings(_Frozen):
    """Japan MoF JGB constant-maturity yield CSVs."""

    latest_url: str
    history_url: str
    encoding: str
    missing_marker: str


class EquitySettings(_Frozen):
    """Equity index tickers (yfinance) and the intraday-bar cutoff (ADR-003)."""

    tickers: dict[str, str]
    close_cutoff_local: time
    timezone: str


class Settings(_Frozen):
    """Root settings model."""

    data: DataSettings
    http: HttpSettings
    ecb: EcbSettings
    fred: FredSettings
    mof: MofSettings
    equities: EquitySettings


def load_settings(path: Path = DEFAULT_SETTINGS_PATH) -> Settings:
    """Load and validate settings from a YAML file.

    Parameters
    ----------
    path
        Path to the settings YAML.

    Returns
    -------
    Settings
        Validated, immutable settings.
    """
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return Settings.model_validate(raw)


__all__ = [
    "DEFAULT_SETTINGS_PATH",
    "DataSettings",
    "EcbSettings",
    "EquitySettings",
    "FredSettings",
    "HttpSettings",
    "MofSettings",
    "Settings",
    "load_settings",
]
