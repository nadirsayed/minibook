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

import numpy as np
import pandas as pd

from minibook.config.settings import Settings
from minibook.data.cache import RawStore
from minibook.dates.calendars import CALENDARS, JP, TARGET, US, Calendar
from minibook.dates.tenor import Tenor
from minibook.market.bootstrap import bootstrap_par_curve
from minibook.market.curves import ZeroCurve
from minibook.market.snapshot import FillRecord, MarketSnapshot, QualityFlag
from minibook.market.svensson import SvenssonParams, svensson_curve, validation_errors_bp
from minibook.market.vol import ewma_vol_series

LOG = logging.getLogger(__name__)
PERCENT = 100.0
BP_PER_PERCENT = 100.0

# Market calendar of each rates/FX source: used to explain fills, and for the closure
# exemption. Equity indices use their own exchange calendar (settings.equities.calendars).
SOURCE_CALENDARS: dict[tuple[str, str], Calendar] = {
    ("ecb", "yield_curve"): TARGET,
    ("ecb", "fx"): TARGET,
    ("treasury", "par_curve"): US,
    ("fred", "ust_cmt"): US,
    ("mof", "jgb_cm"): JP,
}


class MarketDataError(RuntimeError):
    """Required market data is missing or failed validation."""


class StaleDataError(MarketDataError):
    """The latest observation is older than the forward-fill limit."""


@dataclass(frozen=True)
class _Series:
    """One series, sorted by date, for O(log n) as-of lookups."""

    dates: np.ndarray  # datetime64[D], increasing
    vals: np.ndarray
    fetched: list[str]


@dataclass(frozen=True)
class _Picked:
    by_series: dict[str, float]
    obs_dates: dict[str, date]
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
        self._series_cache: dict[tuple[str, str], dict[str, _Series]] = {}
        self._vol_cache: dict[str, np.ndarray] = {}
        self._fred_index: dict[tuple[date, str], float] | None = None

    # ------------------------------------------------------------------ helpers
    def _frame(self, source: str, dataset: str) -> pd.DataFrame:
        key = (source, dataset)
        if key not in self._cache:
            self._cache[key] = self.store.load(source, dataset)
        return self._cache[key]

    def _series(self, source: str, dataset: str) -> dict[str, _Series]:
        key = (source, dataset)
        if key not in self._series_cache:
            df = self._frame(source, dataset).sort_values(["series", "obs_date"], kind="stable")
            out = {}
            for name, g in df.groupby("series", sort=True):
                out[str(name)] = _Series(
                    dates=np.asarray(
                        pd.to_datetime(g["obs_date"]).to_numpy(), dtype="datetime64[D]"
                    ),
                    vals=g["value"].to_numpy(dtype=float),
                    fetched=[pd.Timestamp(x).isoformat() for x in g["first_fetched_utc"]],
                )
            self._series_cache[key] = out
        return self._series_cache[key]

    def _closure_ok(self, cal: Calendar, obs_date: date, target: date) -> bool:
        if not self.s.market.market_closure_exempt:
            return False
        d = obs_date + timedelta(days=1)
        while d <= target:
            if d.weekday() < 5 and cal.is_business_day(d):
                return False
            d += timedelta(days=1)
        return True

    def _calendar(self, source: str, dataset: str, series: str) -> Calendar:
        if (source, dataset) == ("equities", "index_close"):
            return CALENDARS[self.s.equities.calendars[series]]
        return SOURCE_CALENDARS[(source, dataset)]

    def _pick(self, source: str, dataset: str, series: Sequence[str], as_of: date) -> _Picked:
        table = self._series(source, dataset)
        target = np.datetime64(as_of, "D")
        values: dict[str, float] = {}
        obs_dates: dict[str, date] = {}
        fills: list[FillRecord] = []
        fetched: list[str] = []
        for name in series:
            ser = table.get(name)
            k = -1 if ser is None else int(np.searchsorted(ser.dates, target, side="right")) - 1
            if ser is None or k < 0:
                raise MarketDataError(
                    f"{source}/{dataset} {name}: no observation on or before {as_of}"
                )
            obs_date: date = ser.dates[k].astype(date)
            age = (as_of - obs_date).days
            if age > 0:
                cal = self._calendar(source, dataset, name)
                reason = f"no {dataset} observation for {as_of}" + (
                    f"; {as_of} is a {cal.name} holiday"
                    if cal.is_holiday(as_of)
                    else f" although {as_of} is a {cal.name} business day (source gap)"
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
            values[name] = float(ser.vals[k])
            obs_dates[name] = obs_date
            fetched.append(ser.fetched[k])
        return _Picked(values, obs_dates, fills, max(fetched))

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

    def _usd_curve(self, as_of: date) -> tuple[ZeroCurve, _Picked, list[QualityFlag]]:
        labels = list(self.s.treasury.columns)
        picked = self._pick("treasury", "par_curve", labels, as_of)
        quotes = {k: v / PERCENT for k, v in picked.by_series.items()}
        m = self.s.market.usd
        curve = bootstrap_par_curve("USD", quotes, m.money_market, m.coupon_frequency)
        return curve, picked, self._fred_crosscheck(as_of, picked)

    def _fred_crosscheck(self, as_of: date, picked: _Picked) -> list[QualityFlag]:
        """Compare Treasury with FRED for the same observation date (ADR-012).

        FRED lags Treasury by about one business day, so a missing FRED value is normal and
        not flagged. Only differences above ``treasury.fred_crosscheck_bp`` are flagged.
        """
        if self._fred_index is None:
            f = self._frame("fred", "ust_cmt")
            self._fred_index = {
                (d, str(n)): float(v)
                for d, n, v in zip(f["obs_date"], f["series"], f["value"], strict=True)
            }
        flags = []
        for label, value in picked.by_series.items():
            obs_date = picked.obs_dates[label]
            ref_value = self._fred_index.get((obs_date, label))
            if ref_value is None:
                continue
            ref = ref_value
            diff_bp = (value - ref) * BP_PER_PERCENT
            if abs(diff_bp) > self.s.treasury.fred_crosscheck_bp:
                msg = (
                    f"USD {label} {obs_date}: Treasury {value:.3f}% vs FRED "
                    f"{ref:.3f}% ({diff_bp:+.2f} bp)"
                )
                LOG.warning("FRED cross-check: %s", msg)
                flags.append(QualityFlag("FRED_CROSSCHECK", msg))
        return flags

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
        table = self._series("equities", "index_close")
        v = self.s.market.vol
        vols = {}
        for u in underlyings:
            ser = table[u]
            if u not in self._vol_cache:
                self._vol_cache[u] = ewma_vol_series(
                    ser.vals, v.ewma_lambda, v.warmup_days, v.annualization_days
                )
            k = int(np.searchsorted(ser.dates, np.datetime64(as_of, "D"), side="right")) - 1
            vol = float(self._vol_cache[u][k])
            if not np.isfinite(vol):
                raise MarketDataError(
                    f"{u}: EWMA vol needs {v.warmup_days + 1} returns on or before {as_of}"
                )
            vols[u] = vol
        return picked.by_series, vols, picked

    # --------------------------------------------------------------------- build
    def build(
        self,
        as_of: date,
        div_yields: Mapping[str, float] | None = None,
        underlyings: Sequence[str] | None = None,
    ) -> MarketSnapshot:
        """Build the snapshot for ``as_of`` (must be a TARGET business day).

        ``div_yields`` may be omitted (e.g. for ``init-book``, which needs no dividends).
        Option pricing then fails explicitly for lack of a dividend yield.
        """
        if not TARGET.is_business_day(as_of):
            raise ValueError(f"{as_of} is not a TARGET business day")
        names = list(underlyings if underlyings is not None else self.s.equities.tickers)
        keys = list(self.s.market.key_pillars)
        key_t = [Tenor.parse(k).years for k in keys]

        eur, p_eur = self._eur_curve(as_of)
        usd, p_usd, usd_flags = self._usd_curve(as_of)
        jpy, p_jpy = self._jpy_curve(as_of)
        p_fx = self._pick("ecb", "fx", list(self.s.ecb.fx.keys), as_of)
        spots, vols, p_eq = self._equities(as_of, names)
        curves = {c.currency: c.with_pillars(key_t, keys) for c in (eur, usd, jpy)}
        picks = {
            "ecb/yield_curve": p_eur,
            "treasury/par_curve": p_usd,
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
            div_yields={u: float(v) for u, v in (div_yields or {}).items() if u in names},
            key_pillars=tuple(keys),
            fills=tuple(f for p in picks.values() for f in p.fills),
            quality_flags=tuple(usd_flags),
            data_timestamps={k: p.first_fetched for k, p in picks.items()},
        )
