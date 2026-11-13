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
    fixings_dir: Path
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


class TreasurySettings(_Frozen):
    """U.S. Treasury daily par yield curve CSV (one file per year)."""

    url_template: str
    params: dict[str, str]
    columns: dict[str, str]
    fred_crosscheck_bp: float = Field(gt=0.0)


class MofSettings(_Frozen):
    """Japan MoF JGB constant-maturity yield CSVs."""

    latest_url: str
    history_url: str
    encoding: str
    missing_marker: str


class EquitySettings(_Frozen):
    """Equity index tickers (yfinance) and the intraday-bar cutoff (ADR-003)."""

    tickers: dict[str, str]
    calendars: dict[str, str]
    close_cutoff_local: time
    timezone: str


class UsdCurveSettings(_Frozen):
    """USD Treasury CMT bootstrap inputs."""

    money_market: tuple[str, ...]
    coupon_frequency: int = Field(gt=0)


class JpyCurveSettings(_Frozen):
    """JPY MoF constant-maturity bootstrap inputs."""

    tenors: tuple[str, ...]
    coupon_frequency: int = Field(gt=0)


class VolSettings(_Frozen):
    """EWMA realized-vol proxy parameters."""

    ewma_lambda: float = Field(gt=0.0, lt=1.0)
    warmup_days: int = Field(gt=0)
    annualization_days: float = Field(gt=0.0)


class MarketSettings(_Frozen):
    """Snapshot construction: forward-fill policy, curve grids, vol proxy."""

    max_ffill_days: int = Field(ge=0)
    market_closure_exempt: bool
    svensson_tolerance_bp: float = Field(gt=0.0)
    key_pillars: tuple[str, ...]
    eur_pillars: tuple[str, ...]
    usd: UsdCurveSettings
    jpy: JpyCurveSettings
    vol: VolSettings


class FxConventionSettings(_Frozen):
    """Spot-date rule of one currency pair (calendar names from ``CALENDARS``)."""

    spot_lag: int = Field(ge=0)
    lag_calendars: tuple[str, ...]
    settlement_calendars: tuple[str, ...]


class RiskSettings(_Frozen):
    """Sensitivity conventions (brief units)."""

    rate_bump: float = Field(gt=0.0)
    theta_days: int = Field(gt=0)
    days_per_year: float = Field(gt=0.0)
    div_yield_bump: float = Field(gt=0.0)


class PnlSettings(_Frozen):
    """P&L explain breach threshold: |unexplained| > max(rel * |actual|, abs)."""

    unexplained_rel_threshold: float = Field(ge=0.0)
    unexplained_abs_threshold_eur: float = Field(ge=0.0)


class VarSettings(_Frozen):
    """Historical-simulation VaR/ES parameters."""

    n_scenarios: int = Field(gt=0)
    var_confidence: float = Field(gt=0.0, lt=1.0)
    es_confidence: float = Field(gt=0.0, lt=1.0)
    n_worst: int = Field(gt=0)
    bootstrap_resamples: int = Field(gt=0)
    bootstrap_seed: int
    bootstrap_ci: float = Field(gt=0.0, lt=1.0)


class BacktestSettings(_Frozen):
    """VaR backtesting: Basel traffic light and Kupiec POF test."""

    min_observations: int = Field(gt=0)
    yellow_from: int = Field(gt=0)
    red_from: int = Field(gt=0)
    kupiec_significance: float = Field(gt=0.0, lt=1.0)


class PipelineSettings(_Frozen):
    """Daily pipeline: output locations, incremental fetch, schedule window."""

    output_dir: Path
    reports_dir: Path
    fetch_lookback_days: int = Field(ge=0)
    timezone: str
    window_start_local: time
    window_end_local: time
    not_ready_exit_code: int


class Settings(_Frozen):
    """Root settings model."""

    data: DataSettings
    http: HttpSettings
    ecb: EcbSettings
    treasury: TreasurySettings
    fred: FredSettings
    mof: MofSettings
    equities: EquitySettings
    market: MarketSettings
    fx_conventions: dict[str, FxConventionSettings]
    risk: RiskSettings
    pnl: PnlSettings
    var: VarSettings
    backtest: BacktestSettings
    pipeline: PipelineSettings


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
    "MarketSettings",
    "MofSettings",
    "Settings",
    "TreasurySettings",
    "load_settings",
]
