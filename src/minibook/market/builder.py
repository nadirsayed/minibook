"""Build a :class:`MarketSnapshot` for one valuation date from the raw store.

Alignment and forward-fill (brief, CLAUDE.md)
---------------------------------------------
Every input is read with ``as_of = D``, so nothing dated after D is visible. For each
series:

* an observation dated D is used as is;
* otherwise the latest earlier observation is used if it is at most ``max_ffill_days``
  calendar days old. A :class:`FillRecord` (observation date, age, reason) is attached to
  the snapshot and logged;
* anything older raises :class:`StaleDataError`. Nothing is ever filled silently.

If ``market_closure_exempt`` is true (ADR-011, default false as in the brief), an older
observation is also accepted when every weekday after it, up to D, is a holiday of that
source's market calendar. Example: Japanese Golden Week. The fill is still recorded.

Curves: EUR from the ECB Svensson parameters (validated against the published SR_* rates),
USD and JPY bootstrapped from par yields. Every curve gets the key-rate pillars inserted.
Vol: EWMA proxy over closes dated on or before D. Equity spots are the closes on D.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from minibook.config.settings import Settings
from minibook.data.cache import RawStore
from minibook.dates.calendars import JP, TARGET, US, Calendar
from minibook.dates.tenor import Tenor
from minibook.market.bootstrap import bootstrap_par_curve
from minibook.market.curves import ZeroCurve
from minibook.market.snapshot import FillRecord, MarketSnapshot
from minibook.market.svensson import SvenssonParams, svensson_curve, validation_errors_bp
from minibook.market.vol import ewma_vol

LOG = logging.getLogger(__name__)
PERCENT = 100.0

# Market calendar of each source: used to explain fills, and for the closure exemption.
SOURCE_CALENDARS: dict[tuple[str, str], Calendar | None] = {
    ("ecb", "yield_curve"): TARGET,
    ("ecb", "fx"): TARGET,
    ("fred", "ust_cmt"): US,
    ("mof", "jgb_cm"): JP,
    ("equities", "index_close"): None,
}


class MarketDataError(RuntimeError):
    """Required market data is missing or failed validation."""


class StaleDataError(MarketDataError):
    """The latest observation is older than the forward-fill limit."""


@dataclass(frozen=True)
class _Picked:
    by_series: dict[str, float]
    fills: list[FillRecord]
    first_fetched: str


class SnapshotBuilder:
    """Builds snapshots from a store, under one ``Settings``.

    Parameters
    ----------
    store
        Raw store.
    settings
        Validated settings.
    """

    def __init__(self, store: RawStore, settings: Settings) -> None:
        self.store = store
        self.s = settings
        self._cache: dict[tuple[str, str], pd.DataFrame] = {}

    # ------------------------------------------------------------------ helpers
    def _frame(self, source: str, dataset: str) -> pd.DataFrame:
        key = (source, dataset)
        if key not in self._cache:
            self._cache[key] = self.store.load(source, dataset)
        return self._cache[key]

    def _closure_ok(self, cal: Calendar | None, obs_date: date, target: date) -> bool:
        if cal is None or not self.s.market.market_closure_exempt:
            return False
        d = obs_date + timedelta(days=1)
        while d <= target:
            if d.weekday() < 5 and cal.is_business_day(d):
                return False
            d += timedelta(days=1)
        return True

    def _pick(self, source: str, dataset: str, series: Sequence[str], as_of: date) -> _Picked:
        df = self._frame(source, dataset)
        df = df.loc[(df["obs_date"] <= as_of) & df["series"].isin(list(series))]
        cal = SOURCE_CALENDARS.get((source, dataset))
        values: dict[str, float] = {}
        fills: list[FillRecord] = []
        fetched: list[pd.Timestamp] = []
        for name in series:
            rows = df.loc[df["series"] == name]
            if rows.empty:
                raise MarketDataError(
                    f"{source}/{dataset} {name}: no observation on or before {as_of}"
                )
            row = rows.sort_values("obs_date").iloc[-1]
            obs_date: date = row["obs_date"]
            age = (as_of - obs_date).days
            if age > 0:
                holiday = cal is not None and cal.is_holiday(as_of)
                reason = f"no {dataset} observation for {as_of}" + (
                    f"; {as_of} is a {cal.name} holiday" if holiday and cal else ""
                )
                if age > self.s.market.max_ffill_days:
                    if not self._closure_ok(cal, obs_date, as_of):
                        raise StaleDataError(
                            f"{source}/{dataset} {name}: latest observation {obs_date} is "
                            f"{age} days old (> {self.s.market.max_ffill_days}) for {as_of}"
                        )
                    reason += f"; market closed since {obs_date} (closure exemption, ADR-011)"
                rec = FillRecord(f"{source}/{dataset}", name, as_of, obs_date, age, reason)
                LOG.warning("forward-fill: %s", rec)
                fills.append(rec)
            values[name] = float(row["value"])
            fetched.append(pd.Timestamp(row["first_fetched_utc"]))
        return _Picked(values, fills, max(fetched).isoformat())

    # ------------------------------------------------------------------- curves
    def _eur_curve(self, as_of: date) -> tuple[ZeroCurve, _Picked]:
        yc = self.s.ecb.yield_curve
        picked = self._pick("ecb", "yield_curve", [*yc.params, *yc.validation], as_of)
        params = SvenssonParams.from_ecb(picked.by_series)
        errors = validation_errors_bp(params, {k: picked.by_series[k] for k in yc.validation})
        worst = max(abs(e) for e in errors.values())
        if worst > self.s.market.svensson_tolerance_bp:
            raise MarketDataError(
                f"Svensson rebuild off by {errors} bp on {as_of} "
                f"(tolerance {self.s.market.svensson_tolerance_bp} bp)"
            )
        return svensson_curve(params, list(self.s.market.eur_pillars)), picked

    def _usd_curve(self, as_of: date) -> tuple[ZeroCurve, _Picked]:
        labels = list(self.s.fred.series)
        picked = self._pick("fred", "ust_cmt", labels, as_of)
        quotes = {k: v / PERCENT for k, v in picked.by_series.items()}
        m = self.s.market.usd
        return bootstrap_par_curve("USD", quotes, m.money_market, m.coupon_frequency), picked

    def _jpy_curve(self, as_of: date) -> tuple[ZeroCurve, _Picked]:
        m = self.s.market.jpy
        picked = self._pick("mof", "jgb_cm", list(m.tenors), as_of)
        quotes = {k: v / PERCENT for k, v in picked.by_series.items()}
        return bootstrap_par_curve("JPY", quotes, (), m.coupon_frequency), picked

    # ---------------------------------------------------------------- equities
    def _equities(
        self, as_of: date, underlyings: Sequence[str]
    ) -> tuple[dict[str, float], dict[str, float], _Picked]:
        picked = self._pick("equities", "index_close", underlyings, as_of)
        df = self._frame("equities", "index_close")
        v = self.s.market.vol
        vols = {}
        for u in underlyings:
            closes = df.loc[(df["series"] == u) & (df["obs_date"] <= as_of)].sort_values(
                "obs_date"
            )["value"]
            vols[u] = ewma_vol(closes, v.ewma_lambda, v.warmup_days, v.annualization_days)
        return picked.by_series, vols, picked

    # --------------------------------------------------------------------- build
    def build(
        self, as_of: date, div_yields: Mapping[str, float], underlyings: Sequence[str] | None = None
    ) -> MarketSnapshot:
        """Build the snapshot for ``as_of`` (must be a TARGET business day)."""
        if not TARGET.is_business_day(as_of):
            raise ValueError(f"{as_of} is not a TARGET business day")
        names = list(underlyings if underlyings is not None else self.s.equities.tickers)
        keys = list(self.s.market.key_pillars)
        key_t = [Tenor.parse(k).years for k in keys]

        eur, p_eur = self._eur_curve(as_of)
        usd, p_usd = self._usd_curve(as_of)
        jpy, p_jpy = self._jpy_curve(as_of)
        p_fx = self._pick("ecb", "fx", list(self.s.ecb.fx.keys), as_of)
        spots, vols, p_eq = self._equities(as_of, names)
        curves = {c.currency: c.with_pillars(key_t, keys) for c in (eur, usd, jpy)}
        picks = {
            "ecb/yield_curve": p_eur,
            "fred/ust_cmt": p_usd,
            "mof/jgb_cm": p_jpy,
            "ecb/fx": p_fx,
            "equities/index_close": p_eq,
        }
        return MarketSnapshot(
            as_of=as_of,
            curves=curves,
            fx=p_fx.by_series,
            spots=spots,
            vols=vols,
            div_yields={u: float(div_yields[u]) for u in names},
            key_pillars=tuple(keys),
            fills=tuple(f for p in picks.values() for f in p.fills),
            data_timestamps={k: p.first_fetched for k, p in picks.items()},
        )
