"""Probe every external market-data source used by minibook.

For each source this script:
  * downloads a small sample (and, where cheap, the full history),
  * prints the first/last rows,
  * reports the history coverage against the window needed for 500 VaR
    scenarios + 60d realized-vol warm-up (start ~ 2023-06-01),
  * for the ECB Svensson curve, rebuilds SR_1Y/SR_5Y/SR_10Y from the published
    parameters and reports the reconstruction error in basis points.

Exit code 0 if every source passed, 1 otherwise. Results are also written as
JSON to the path given by --out (default: probe_report.json).

Usage: uv run python scripts/probe_sources.py [--out probe_report.json]
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import requests
import yfinance as yf

LOG = logging.getLogger("probe")

# Window needed: 501 aligned TARGET dates before 2026-12-31 plus a 60-business-day
# realized-vol warm-up -> roughly 2.25 calendar years. 2023-06-01 leaves margin.
HISTORY_START = date(2023, 6, 1)
TIMEOUT_S = 60
USER_AGENT = "minibook-probe/0.1 (+https://github.com/nadirsayed/minibook)"

ECB_BASE = "https://data-api.ecb.europa.eu/service/data"
SV_PARAMS = ("BETA0", "BETA1", "BETA2", "BETA3", "TAU1", "TAU2")
SV_KEY = "B.U2.EUR.4F.G_N_A.SV_C_YM.{}"
SR_TENORS = {"SR_1Y": 1.0, "SR_5Y": 5.0, "SR_10Y": 10.0}
SV_TOL_BP = 0.1

FRED_SERIES = (
    "DGS1MO",
    "DGS3MO",
    "DGS6MO",
    "DGS1",
    "DGS2",
    "DGS3",
    "DGS5",
    "DGS7",
    "DGS10",
)
MOF_LATEST = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"
MOF_ALL = (
    "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv"
)
STOXX_V2TX = "https://www.stoxx.com/document/Indices/Current/HistoricalData/h_v2tx.txt"
EQUITY_TICKERS = ("^STOXX50E", "^GDAXI", "^FCHI", "FTSEMIB.MI", "^V2TX")


@dataclass
class ProbeResult:
    name: str
    ok: bool
    detail: str
    first_obs: str | None = None
    last_obs: str | None = None
    n_obs: int | None = None
    extra: dict[str, object] = field(default_factory=dict)


def _get(url: str, **params: str) -> requests.Response:
    resp = requests.get(
        url, params=params or None, timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT}
    )
    resp.raise_for_status()
    return resp


def _coverage(name: str, s: pd.Series, extra: dict[str, object] | None = None) -> ProbeResult:
    s = s.dropna().sort_index()
    first, last = s.index.min().date(), s.index.max().date()
    ok = first <= HISTORY_START
    detail = "history covers window" if ok else f"history starts {first} > {HISTORY_START}"
    return ProbeResult(name, ok, detail, str(first), str(last), int(s.size), extra or {})


def _show(title: str, df: pd.DataFrame | pd.Series, n: int = 3) -> None:
    LOG.info("---- %s: head ----\n%s", title, df.head(n).to_string())
    LOG.info("---- %s: tail ----\n%s", title, df.tail(n).to_string())


# --------------------------------------------------------------------------- ECB
def ecb_series(flow: str, key: str, start: date | None = None) -> pd.Series:
    """Fetch one ECB SDMX series as a float Series indexed by TIME_PERIOD."""
    params = {"format": "csvdata"}
    if start is not None:
        params["startPeriod"] = start.isoformat()
    resp = _get(f"{ECB_BASE}/{flow}/{key}", **params)
    df = pd.read_csv(io.StringIO(resp.text))
    s = pd.Series(
        df["OBS_VALUE"].astype(float).to_numpy(),
        index=pd.to_datetime(df["TIME_PERIOD"]),
        name=f"{flow}.{key}",
    )
    return s.sort_index()


FloatOrArray = float | np.ndarray


def svensson_zero_pct(
    m: np.ndarray,
    b0: FloatOrArray,
    b1: FloatOrArray,
    b2: FloatOrArray,
    b3: FloatOrArray,
    t1: FloatOrArray,
    t2: FloatOrArray,
) -> np.ndarray:
    """ECB Svensson spot rate in percent (continuous compounding).

    z(m) = b0 + b1*L1 + b2*(L1 - e^{-m/t1}) + b3*(L2 - e^{-m/t2}),
    with Lk = (1 - e^{-m/tk}) / (m/tk).
    Source: ECB, "Euro area yield curves - technical notes".
    """
    x1, x2 = m / t1, m / t2
    l1 = (1.0 - np.exp(-x1)) / x1
    l2 = (1.0 - np.exp(-x2)) / x2
    return b0 + b1 * l1 + b2 * (l1 - np.exp(-x1)) + b3 * (l2 - np.exp(-x2))


def probe_ecb_curve() -> ProbeResult:
    start = HISTORY_START
    params = pd.DataFrame({p: ecb_series("YC", SV_KEY.format(p), start) for p in SV_PARAMS})
    srs = pd.DataFrame({k: ecb_series("YC", SV_KEY.format(k), start) for k in SR_TENORS})
    _show("ECB Svensson params", params)
    _show("ECB published spot rates (%)", srs)
    joined = params.join(srs, how="inner").dropna()
    errs = {}
    for k, m in SR_TENORS.items():
        rebuilt = svensson_zero_pct(
            np.full(len(joined), m), *(joined[p].to_numpy() for p in SV_PARAMS)
        )
        errs[k] = (rebuilt - joined[k].to_numpy()) * 100.0  # percent -> bp
    err = pd.DataFrame(errs, index=joined.index)
    LOG.info(
        "---- Svensson rebuild error (bp), last 5 days ----\n%s", err.tail(5).round(6).to_string()
    )
    max_abs = {k: float(np.abs(v).max()) for k, v in err.items()}
    LOG.info("Max |error| over %d days (bp): %s", len(err), max_abs)
    res = _coverage("ECB YC Svensson (AAA, SV_C_YM)", params["BETA0"])
    worst = max(max_abs.values())
    res.extra = {"max_abs_err_bp": max_abs, "days_checked": len(err)}
    if worst > SV_TOL_BP:
        res.ok = False
        res.detail += f"; Svensson rebuild error {worst:.4f}bp > {SV_TOL_BP}bp"
    else:
        res.detail += f"; Svensson rebuild max error {worst:.2e}bp <= {SV_TOL_BP}bp"
    return res


def probe_ecb_simple(name: str, flow: str, key: str) -> ProbeResult:
    s = ecb_series(flow, key, HISTORY_START)
    _show(name, s)
    return _coverage(name, s)


# --------------------------------------------------------------------------- FRED
def probe_fred() -> ProbeResult:
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
    frames = {}
    for sid in FRED_SERIES:
        resp = _get(url, id=sid, cosd=HISTORY_START.isoformat())
        df = pd.read_csv(io.StringIO(resp.text), na_values=".")
        frames[sid] = pd.Series(
            df.iloc[:, 1].to_numpy(dtype=float), index=pd.to_datetime(df.iloc[:, 0])
        )
    out = pd.DataFrame(frames)
    _show("FRED CMT par yields (%)", out)
    return _coverage("FRED DGS*", out["DGS10"])


# --------------------------------------------------------------------------- MoF
def _parse_mof(text: str) -> pd.DataFrame:
    lines = text.splitlines()
    hdr = next(i for i, ln in enumerate(lines) if ln.startswith("Date,"))
    df = pd.read_csv(io.StringIO("\n".join(lines[hdr:])), na_values="-")
    df = df[pd.to_datetime(df["Date"], format="%Y/%m/%d", errors="coerce").notna()]
    df.index = pd.to_datetime(df.pop("Date"), format="%Y/%m/%d")
    return df.astype(float)


def probe_mof() -> ProbeResult:
    latest = _parse_mof(_get(MOF_LATEST).content.decode("latin-1"))
    hist = _parse_mof(_get(MOF_ALL).content.decode("latin-1"))
    _show("MoF JGB latest month (%)", latest)
    _show("MoF JGB history (%)", hist[hist.index >= pd.Timestamp(HISTORY_START)])
    res = _coverage("MoF JGB (jgbcme + jgbcme_all)", hist["10Y"])
    res.extra = {"latest_last": str(latest.index.max().date()), "tenors": list(latest.columns)}
    res.last_obs = str(max(hist.index.max(), latest.index.max()).date())
    return res


# --------------------------------------------------------------------------- STOXX
def probe_vstoxx() -> ProbeResult:
    resp = _get(STOXX_V2TX)
    df = pd.read_csv(io.StringIO(resp.text), sep=";")
    s = pd.Series(
        df["Indexvalue"].astype(float).to_numpy(),
        index=pd.to_datetime(df["Date"], format="%d.%m.%Y"),
        name="V2TX",
    )
    _show("STOXX VSTOXX h_v2tx.txt", s)
    return _coverage("STOXX VSTOXX (official file)", s)


# --------------------------------------------------------------------------- Yahoo
def probe_yahoo(ticker: str) -> ProbeResult:
    df = yf.Ticker(ticker).history(start=HISTORY_START.isoformat(), auto_adjust=False)
    if df.empty:
        return ProbeResult(f"yfinance {ticker}", False, "no data returned")
    df.index = df.index.tz_localize(None)
    _show(f"yfinance {ticker}", df[["Close"]])
    return _coverage(f"yfinance {ticker}", df["Close"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="probe_report.json")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

    probes: list[tuple[str, Callable[[], ProbeResult]]] = [
        ("ECB YC", probe_ecb_curve),
        ("ECB EXR USD", lambda: probe_ecb_simple("ECB EXR EUR/USD", "EXR", "D.USD.EUR.SP00.A")),
        ("ECB EXR JPY", lambda: probe_ecb_simple("ECB EXR EUR/JPY", "EXR", "D.JPY.EUR.SP00.A")),
        ("ECB ESTR", lambda: probe_ecb_simple("ECB EUR STR", "EST", "B.EU000A2X2A25.WT")),
        ("FRED", probe_fred),
        ("MoF", probe_mof),
        ("STOXX", probe_vstoxx),
        *((t, (lambda t=t: probe_yahoo(t))) for t in EQUITY_TICKERS),
    ]
    results: list[ProbeResult] = []
    for name, fn in probes:
        LOG.info("\n==================== %s ====================", name)
        try:
            results.append(fn())
        except Exception as exc:
            LOG.error("%s FAILED: %r", name, exc)
            results.append(ProbeResult(name, False, f"{type(exc).__name__}: {exc}"))

    LOG.info("\n==================== SUMMARY ====================")
    for r in results:
        LOG.info(
            "[%s] %-34s %s..%s n=%s  %s",
            "PASS" if r.ok else "FAIL",
            r.name,
            r.first_obs,
            r.last_obs,
            r.n_obs,
            r.detail,
        )
    with open(args.out, "w") as fh:
        json.dump(
            {"run_at_utc": datetime.now(UTC).isoformat(), "results": [r.__dict__ for r in results]},
            fh,
            indent=2,
            default=str,
        )
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
