"""Report content, assembled from the day's results (no rendering here).

Index-level rule (ADR-019, owner decision 13): nothing committed may show an index level.
The report model is the only input of the PDF and the charts, and it is built from returns,
ratios, vols and EUR amounts only. :func:`assemble` reads spots solely to compute
returns and moneyness, and never stores a level. :mod:`minibook.reporting.guard` checks the
rendered text as a second line of defence.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from minibook.config.book import Book
from minibook.instruments.base import Instrument
from minibook.instruments.equity_option import EquityOption
from minibook.instruments.fx_forward import FxForward
from minibook.instruments.swap import InterestRateSwap
from minibook.market.snapshot import MarketSnapshot
from minibook.pnl.explain import PnlExplain
from minibook.risk.backtest import BacktestResult
from minibook.risk.var import VarResult

CURVE_CHART_MAX_YEARS = 10.0
CURVE_CHART_POINTS = 121


@dataclass(frozen=True)
class PositionRow:
    """One position in the valuation table (no index levels)."""

    instrument_id: str
    kind: str
    description: str
    maturity: date
    pv_prev: float
    pv_curr: float


@dataclass(frozen=True)
class ReportData:
    """Everything the PDF shows. EUR amounts, %, bp and dates only."""

    as_of: date
    prev: date
    positions: tuple[PositionRow, ...]
    greeks: pd.DataFrame  # long: instrument_id, measure, risk_factor, value
    explain: PnlExplain
    step_order: tuple[str, ...]
    var: VarResult
    var_history: pd.DataFrame  # date, var, es
    backtest: BacktestResult
    eur_curve: pd.DataFrame  # t (years), today (%), prev (%)
    moves: pd.DataFrame  # name, kind ("FX" | "Index"), ret (decimal)
    vols: pd.DataFrame  # underlying, vol (decimal), change (decimal)
    key_pillars: tuple[str, ...]  # from the snapshot (settings.market.key_pillars)
    quality: tuple[str, ...]
    notes: tuple[str, ...]
    sources: tuple[str, ...]
    data_timestamps: dict[str, str] = field(default_factory=dict)
    git_sha: str = "unknown"
    config_hash: str = "unknown"


def describe(inst: Instrument, book: Book, market: MarketSnapshot) -> tuple[str, str, date]:
    """(kind, description, maturity) without any index level."""
    if isinstance(inst, InterestRateSwap):
        side = "Payer" if inst.pay_fixed else "Receiver"
        return (
            "IRS",
            f"{side} EUR {inst.notional / 1e6:.1f}m, fixed {100 * inst.fixed_rate:.4f}% "
            f"vs {inst.index} (proxy fixings)",
            inst.maturity,
        )
    if isinstance(inst, FxForward):
        side = "Buy" if inst.base_notional > 0 else "Sell"
        return (
            "FX fwd",
            f"{side} {inst.base} {abs(inst.base_notional) / 1e6:.1f}m vs "
            f"{inst.quote} at {inst.strike:.5f}",
            inst.delivery,
        )
    if isinstance(inst, EquityOption):
        spec = next(o for o in book.options if o.id == inst.id)
        side = "Long" if inst.quantity > 0 else "Short"
        moneyness = float(market.spots[inst.underlying]) / inst.strike - 1.0
        return (
            "Option",
            f"{side} {abs(inst.quantity):g} {inst.underlying} "
            f"{inst.option_type.value} {spec.tenor}, strike {100 * spec.strike_pct:.0f}% of "
            f"trade-date spot, EUR {inst.multiplier:g}/pt; spot vs strike "
            f"{100 * moneyness:+.1f}%",
            inst.expiry,
        )
    raise TypeError(f"unknown instrument {inst!r}")


def market_moves(prev: MarketSnapshot, curr: MarketSnapshot) -> pd.DataFrame:
    """Day returns of FX rates and indices (decimal); levels are never kept."""
    rows = [(f"EUR/{c}", "FX", curr.fx[c] / prev.fx[c] - 1.0) for c in sorted(curr.fx)]
    rows += [(u, "Index", curr.spots[u] / prev.spots[u] - 1.0) for u in sorted(curr.spots)]
    return pd.DataFrame(rows, columns=["name", "kind", "ret"])


def vol_table(prev: MarketSnapshot, curr: MarketSnapshot) -> pd.DataFrame:
    """EWMA vol proxy per index and its daily change (decimal)."""
    return pd.DataFrame(
        [(u, curr.vols[u], curr.vols[u] - prev.vols[u]) for u in sorted(curr.vols)],
        columns=["underlying", "vol", "change"],
    )


def eur_curve_table(prev: MarketSnapshot, curr: MarketSnapshot) -> pd.DataFrame:
    """EUR zero curve (%, continuous) today and on t-1, 0-10Y."""
    t = np.linspace(1.0 / 12.0, CURVE_CHART_MAX_YEARS, CURVE_CHART_POINTS)
    return pd.DataFrame(
        {
            "t": t,
            "today": 100 * np.asarray(curr.curve("EUR").zero(t)),
            "prev": 100 * np.asarray(prev.curve("EUR").zero(t)),
        }
    )


def quality_lines(curr: MarketSnapshot, book: Book, extra: Sequence[str] = ()) -> tuple[str, ...]:
    """Data-quality section: forward fills (grouped), quality flags, assumption flags."""
    lines: list[str] = []
    grouped: dict[tuple[str, date, int, str], list[str]] = {}
    for f in curr.fills:
        grouped.setdefault((f.dataset, f.obs_date, f.age_days, f.reason), []).append(f.series)
    for (ds, obs, age, reason), series in sorted(grouped.items()):
        lines.append(
            f"Forward-fill {ds} ({', '.join(series)}): value of {obs}, {age} day(s) old - {reason}"
        )
    lines += [f"{q.code}: {q.message}" for q in curr.quality_flags]
    for u, dy in sorted(book.assumptions.dividend_yields.items()):
        if dy is not None and dy.look_ahead:
            lines.append(
                f"Dividend yield {u} {100 * dy.value:.1f}%: owner assumption from "
                f"sources consulted {dy.date}, after the trade date (look-ahead flag)"
            )
    lines += list(extra)
    return tuple(lines) if lines else ("No forward-fills or data-quality flags today.",)


SOURCES: tuple[str, ...] = (
    "ECB Data Portal (euro area AAA yield curve, Svensson parameters; euro FX reference rates)",
    "U.S. Department of the Treasury (daily par yield curve); FRED / Federal Reserve H.15 "
    "(cross-check)",
    "Ministry of Finance Japan (JGB constant-maturity yields, Public Data License 1.0)",
    "Yahoo Finance via yfinance (index closes; local, personal non-commercial use, not "
    "redistributed)",
)


def standard_notes(retrospective: bool) -> tuple[str, ...]:
    """Simplifications and model notes printed on every report (CLAUDE.md 13, 14)."""
    notes = [
        "Vol proxy (a): option vols are EWMA realized vols (lambda 0.94), not implied vols. "
        "Realized vol usually sits below implied vol (variance risk premium), and skew is "
        "ignored, so option values are likely understated vs market, most for the long "
        "out-of-the-money puts.",
        "Vol proxy (b): the EWMA vol change of a day is driven by that day's squared return, so "
        "vega P&L and delta/gamma P&L are not independent. On big-move days the omitted "
        "vanna/volga terms dominate the unexplained P&L (diagnostic column), and the VaR vol "
        "shocks rise with |move| in either direction (implied vol would jump in sell-offs), so "
        "vega VaR is a lower bound.",
        "Dividends: flat continuous yields are owner assumptions (look-ahead flagged). A flat q "
        "ignores the April-May dividend season: it overstates dividends for the 3M options and "
        "understates them for the 6M options.",
        "Curves: single EUR AAA government curve (ECB) for discounting and EURIBOR projection: "
        "not a swap curve, no EURIBOR-ESTR basis, no cross-currency basis. JPY is flat below "
        "1Y (no money-market input).",
        "EURIBOR fixings are a curve-implied proxy, recorded once on each fixing date.",
        "Options are hypothetical European cash-settled contracts with bespoke expiries and "
        "exact percentage strikes (listed-contract multipliers): not listed-contract "
        "replication. Strikes are shown as % of the trade-date spot; index moves as % returns.",
        "Index levels are not published here, but they can be recovered from the published "
        "option outputs (PV, strike as % of spot, vol, dividend yield, rates) by inverting "
        "the Black-Scholes formula (ADR-019).",
        "P&L explain uses Greeks of t-1 and the period theta (revaluation from t-1 to t with "
        "the market held at t-1: constant zero rates per tenor, so roll-down is included). "
        "Theta 1d in the Greeks table is the one-day value. Step attribution is "
        "order-dependent.",
    ]
    if retrospective:
        notes.append(
            "Backfilled report: market data was fetched after the report date "
            "(retrospective fetch timestamps; values are those published for the date)."
        )
    return tuple(notes)
