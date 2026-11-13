"""Daily pipeline: one TARGET business day D, end to end (brief, M8).

Steps for valuation date D (previous TARGET day P):
1. load the frozen book (option terms from the private file, ADR-018) and require every
   option's dividend-yield assumption;
2. build the snapshots of P and D (no look-ahead), and record the EURIBOR proxy fixings due
   on P and on D in the immutable fixing store (each from its own date's curve, ADR-016);
3. P&L explain P -> D, Greeks of D, historical VaR/ES of D (500 scenarios, full revaluation,
   delta-gamma VaR, bootstrap intervals);
4. VaR history and backtest observations from earlier committed outputs (P&L of t against
   the VaR of t-1);
5. write ``output/D/``: valuations.csv, greeks.csv, pnl_explain.csv, var_es.json,
   report.pdf, run_metadata.json; copy the PDF to ``reports/D.pdf``.

Every text output passes the index-level guard (ADR-019) before it is written. Re-running
a date rewrites the same files. The data outputs are byte-identical for the same inputs;
only run_metadata.json carries the wall-clock run time.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from minibook import __version__
from minibook.config.book import Book, load_book, private_path
from minibook.config.settings import DEFAULT_SETTINGS_PATH, Settings
from minibook.data.cache import RawStore
from minibook.data.fixings import FixingStore
from minibook.data.http import utc_now
from minibook.dates.calendars import TARGET
from minibook.fixing_service import record_due_fixings
from minibook.instruments.factory import build_instruments
from minibook.market.builder import SnapshotBuilder
from minibook.market.snapshot import MarketSnapshot
from minibook.pnl.explain import DEFAULT_STEP_ORDER, PnlExplain, explain
from minibook.reporting import model as rmodel
from minibook.reporting.guard import check_no_levels
from minibook.reporting.pdf import render
from minibook.risk.backtest import backtest
from minibook.risk.greeks import book_greeks
from minibook.risk.scenario_check import ScenarioFlag, detect, gap_series
from minibook.risk.scenarios import historical_scenarios, scenario_dates
from minibook.risk.var import VarResult, historical_var, with_flags

LOG = logging.getLogger(__name__)
FIXING_INDEX = "EURIBOR6M"
OUTPUT_FILES = (
    "valuations.csv",
    "greeks.csv",
    "pnl_explain.csv",
    "var_es.json",
    "report.pdf",
    "run_metadata.json",
)


class PipelineError(RuntimeError):
    """The run cannot proceed (book not ready, assumption missing, bad date)."""


@dataclass(frozen=True)
class RunResult:
    """Where the outputs went and how long the run took."""

    as_of: date
    out_dir: Path
    report: Path
    seconds: float


def git_sha(repo: Path) -> str:
    """Return the current commit (``-dirty`` if uncommitted changes), or "unknown"."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return sha + ("-dirty" if dirty.strip() else "")


def config_hash(settings_path: Path, book_path: Path) -> str:
    """SHA-256 over settings.yaml, book.yaml and the private option terms (if present)."""
    h = hashlib.sha256()
    for p in (settings_path, book_path, private_path(book_path)):
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()


def _require_assumptions(book: Book) -> dict[str, float]:
    divs = book.available_dividend_yields()
    missing = sorted({o.underlying for o in book.options} - set(divs))
    if missing:
        raise PipelineError(f"dividend-yield assumptions missing for {missing} (book.yaml)")
    if not book.is_frozen:
        raise PipelineError(
            "book is not frozen: run `minibook init-book` (and restore config/book.private.yaml)"
        )
    return divs


def _read_history(out_root: Path, before: date) -> tuple[pd.DataFrame, dict[date, float]]:
    """VaR/ES by date and actual book P&L by date, from earlier outputs (dates < before)."""
    var_rows, pnl = [], {}
    for d in sorted(p for p in out_root.glob("????-??-??") if p.is_dir()):
        day = date.fromisoformat(d.name)
        if day >= before:
            continue
        vj = d / "var_es.json"
        if vj.exists():
            v = json.loads(vj.read_text())
            var_rows.append((day, float(v["var"]), float(v["es"])))
        pe = d / "pnl_explain.csv"
        if pe.exists():
            pnl[day] = float(pd.read_csv(pe)["actual"].sum())
    return pd.DataFrame(var_rows, columns=["date", "var", "es"]), pnl


REPORTS_INDEX = "README.md"


def reports_index(out_root: Path, reports_dir: Path) -> str:
    """Markdown index of the daily reports, newest first (rendered by GitHub in reports/).

    One row per valuation date with a report: actual and unexplained book P&L, VaR99 and
    ES97.5 (EUR), read from the committed outputs. Deterministic: depends only on them.
    """
    rows = []
    for pdf in sorted(reports_dir.glob("????-??-??.pdf"), reverse=True):
        d = out_root / pdf.stem
        v = json.loads((d / "var_es.json").read_text())
        pe = pd.read_csv(d / "pnl_explain.csv")
        rows.append(
            f"| [{pdf.stem}]({pdf.name}) | {pe['actual'].sum():,.0f} | "
            f"{pe['unexplained'].sum():,.0f} | {v['var']:,.0f} | {v['es']:,.0f} |"
        )
    head = [
        "# Daily risk reports",
        "",
        "Generated by `minibook run`; newest first. EUR; P&L positive = gain, VaR/ES positive ="
        " loss",
        "(1 day, historical simulation). Data outputs per date: [../output/](../output/).",
        "",
        "| Valuation date | Actual P&L | Unexplained | VaR 99% | ES 97.5% |",
        "|---|---:|---:|---:|---:|",
    ]
    return "\n".join([*head, *rows]) + "\n"


def _publish_report(
    data: rmodel.ReportData, out_dir: Path, reports_dir: Path, levels: Sequence[float]
) -> Path:
    """Render output/D/report.pdf, copy it to reports/D.pdf and refresh the reports index."""
    report = out_dir / "report.pdf"
    render(data, report, levels)
    reports_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(report, reports_dir / f"{data.as_of.isoformat()}.pdf")
    index = reports_index(out_dir.parent, reports_dir)
    check_no_levels([index], levels)
    (reports_dir / REPORTS_INDEX).write_text(index, encoding="utf-8")
    return report


def _backtest_obs(history: pd.DataFrame, pnl: dict[date, float]) -> pd.DataFrame:
    var_by_day = dict(zip(history["date"], history["var"], strict=True))
    rows = []
    for day, value in sorted(pnl.items()):
        prev = TARGET.advance(day, -1)
        if prev in var_by_day:
            rows.append((day, var_by_day[prev], value))
    return pd.DataFrame(rows, columns=["date", "var_prev", "pnl"])


def _scenario_flags(store: RawStore, s: Settings, as_of: date) -> list[ScenarioFlag] | None:
    """Artefact flags over the scenario window (ADR-028); None if no rating-curve data."""
    curves = store.load_wide("ecb", "rating_curves", as_of=as_of)
    if curves.empty:
        LOG.warning("no ECB rating-curve data: scenario artefact check skipped")
        return None
    days = scenario_dates(as_of, s.var.n_scenarios)[1:]
    return detect(gap_series(curves, s.ecb.rating_curves.tenors), days, s.var)


def _flag_scenarios(var: VarResult, store: RawStore, s: Settings, as_of: date) -> VarResult:
    """Attach the artefact flags when the check can run (ADR-028); VaR/ES never change."""
    flags = _scenario_flags(store, s, as_of)
    return var if flags is None else with_flags(var, flags, s.var)


def _var_json(v: VarResult) -> dict[str, object]:
    return {
        "as_of": str(v.as_of),
        "n_scenarios": v.n_scenarios,
        "var_confidence": v.var_confidence,
        "es_confidence": v.es_confidence,
        "var": v.var,
        "es": v.es,
        "var_ci": v.var_ci,
        "es_ci": v.es_ci,
        "ci_level": v.ci_level,
        "delta_gamma_var": v.delta_gamma_var,
        "delta_gamma_es": v.delta_gamma_es,
        "diversification_var": v.diversification_var,
        "artefact_checked": v.artefact_checked,
        "scenario_flags": [
            {
                "scenario_date": str(f.scenario_date),
                "pillar": f.pillar,
                "gap_move_bp": f.gap_move_bp,
                "z": f.z,
                "reversal_bp": f.reversal_bp,
                "pending": f.pending,
            }
            for f in v.flags
        ],
        "var_ex_flagged": v.var_ex_flagged,
        "es_ex_flagged": v.es_ex_flagged,
        "standalone": {
            str(k): {"var": float(r["var"]), "es": float(r["es"])}
            for k, r in v.standalone.iterrows()
        },
        "worst": [
            {"scenario_date": str(k), **{str(c): float(x) for c, x in r.items()}}
            for k, r in v.worst.iterrows()
        ],
    }


def _forbidden_levels(book: Book, *snaps: MarketSnapshot) -> list[float]:
    levels = [float(x) for s in snaps for x in s.spots.values()]
    for o in book.options:
        if o.frozen is not None:
            levels += [o.frozen.spot_at_trade, o.frozen.strike]
    return levels


def _retrospective(curr: MarketSnapshot, as_of: date) -> bool:
    """Return True if D's data was first fetched after D's next TARGET business day."""
    limit = TARGET.advance(as_of, 1)
    return any(datetime.fromisoformat(ts).date() > limit for ts in curr.data_timestamps.values())


def _tabular_outputs(
    positions: tuple[rmodel.PositionRow, ...], greeks: pd.DataFrame, e: PnlExplain, var: VarResult
) -> dict[str, str]:
    """CSV and JSON outputs (EUR amounts, dates and descriptions only)."""
    comps = e.components.pivot_table(
        index="instrument_id", columns="component", values="value", aggfunc="sum", fill_value=0.0
    )
    pnl_csv = e.per_instrument.drop(columns=["pv_prev", "pv_curr"]).join(comps, on="instrument_id")
    valuations = pd.DataFrame(
        [
            (p.instrument_id, p.kind, p.description, p.maturity, p.pv_prev, p.pv_curr)
            for p in positions
        ],
        columns=["instrument_id", "kind", "description", "maturity", "pv_prev", "pv"],
    )
    return {
        "valuations.csv": valuations.to_csv(index=False, float_format="%.2f"),
        "greeks.csv": greeks.to_csv(index=False, float_format="%.4f"),
        "pnl_explain.csv": pnl_csv.to_csv(index=False, float_format="%.2f"),
        "var_es.json": json.dumps(_var_json(var), indent=2, sort_keys=True) + "\n",
    }


def _fill_log(*snaps: MarketSnapshot) -> list[dict[str, object]]:
    return [
        {
            "dataset": f.dataset,
            "series": f.series,
            "target_date": str(f.target_date),
            "obs_date": str(f.obs_date),
            "age_days": f.age_days,
            "reason": f.reason,
        }
        for snap in snaps
        for f in snap.fills
    ]


def run(
    as_of: date,
    settings: Settings,
    book_path: Path,
    settings_path: Path = DEFAULT_SETTINGS_PATH,
    repo: Path = Path(),
    clock: Callable[[], datetime] = utc_now,
) -> RunResult:
    """Produce every output for valuation date ``as_of``."""
    t0 = time.perf_counter()
    s = settings
    if not TARGET.is_business_day(as_of):
        raise PipelineError(f"{as_of} is not a TARGET business day")
    book = load_book(book_path)
    divs = _require_assumptions(book)
    if as_of <= book.trade_date:
        raise PipelineError(f"{as_of} is not after the trade date {book.trade_date}")
    prev_date = TARGET.advance(as_of, -1)
    insts = build_instruments(book, s)
    builder = SnapshotBuilder(RawStore(s.data.raw_dir), s)
    fixings = FixingStore(s.data.fixings_dir)
    now = clock()

    def snapshot_for(d: date) -> MarketSnapshot:
        return builder.build(d, divs).with_fixings(fixings.as_of([FIXING_INDEX], d))

    prev = record_due_fixings(insts, snapshot_for(prev_date), fixings, now)
    curr = record_due_fixings(insts, snapshot_for(as_of), fixings, now)

    e = explain(insts, prev, curr, s.risk, s.pnl)
    greeks = book_greeks(insts, curr, s.risk)
    var_raw = historical_var(
        insts, curr, historical_scenarios(snapshot_for, as_of, s.var.n_scenarios), s.var, s.risk
    )
    var = _flag_scenarios(var_raw, builder.store, s, as_of)
    out_root = s.pipeline.output_dir
    history, pnl_hist = _read_history(out_root, as_of)
    history = pd.concat(
        [history, pd.DataFrame([(as_of, var.var, var.es)], columns=["date", "var", "es"])],
        ignore_index=True,
    )
    pnl_hist[as_of] = e.book["actual"]
    bt = backtest(_backtest_obs(history, pnl_hist), s.var.var_confidence, s.backtest)

    pv_prev = dict(zip(e.per_instrument["instrument_id"], e.per_instrument["pv_prev"], strict=True))
    pv_curr = dict(zip(e.per_instrument["instrument_id"], e.per_instrument["pv_curr"], strict=True))
    positions = tuple(
        rmodel.PositionRow(
            i.id, *rmodel.describe(i, book, curr), float(pv_prev[i.id]), float(pv_curr[i.id])
        )
        for i in insts
    )
    retro = _retrospective(curr, as_of)
    sha = git_sha(repo)
    chash = config_hash(settings_path, book_path)
    data = rmodel.ReportData(
        as_of=as_of,
        prev=prev_date,
        positions=positions,
        greeks=greeks,
        explain=e,
        step_order=tuple(x.value for x in DEFAULT_STEP_ORDER),
        var=var,
        var_history=history,
        backtest=bt,
        eur_curve=rmodel.eur_curve_table(prev, curr),
        moves=rmodel.market_moves(prev, curr),
        vols=rmodel.vol_table(prev, curr),
        key_pillars=curr.key_pillars,
        quality=rmodel.quality_lines(curr, book),
        notes=rmodel.standard_notes(retro),
        sources=rmodel.SOURCES,
        data_timestamps=dict(curr.data_timestamps),
        git_sha=sha,
        config_hash=chash,
    )

    out_dir = out_root / as_of.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    levels = _forbidden_levels(book, prev, curr)
    texts = _tabular_outputs(positions, greeks, e, var)
    check_no_levels(texts.values(), levels)
    for name, text in texts.items():
        (out_dir / name).write_text(text, encoding="utf-8")
    report = _publish_report(data, out_dir, s.pipeline.reports_dir, levels)

    seconds = time.perf_counter() - t0
    meta = {
        "as_of": str(as_of),
        "previous": str(prev_date),
        "minibook_version": __version__,
        "git_sha": sha,
        "config_hash": chash,
        "run_at_utc": now.isoformat(),
        "run_seconds": round(seconds, 2),
        "data_first_fetched_utc": dict(curr.data_timestamps),
        "retrospective_fetch": retro,
        "forward_fills": _fill_log(prev, curr),
        "quality_flags": [f"{q.code}: {q.message}" for q in curr.quality_flags],
        "breaches": e.per_instrument.loc[e.per_instrument["flagged"], "instrument_id"].tolist(),
        "backtest_status": bt.status,
    }
    meta_text = json.dumps(meta, indent=2, sort_keys=True) + "\n"
    check_no_levels([meta_text], levels)
    (out_dir / "run_metadata.json").write_text(meta_text, encoding="utf-8")
    LOG.info("run %s done in %.1fs -> %s", as_of, seconds, out_dir)
    return RunResult(as_of, out_dir, report, seconds)
