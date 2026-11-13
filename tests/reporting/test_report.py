"""PDF report on SYNTHETIC data: validity, page budget, sections, determinism, and the
index-level rule (ADR-019). Synthetic index levels are chosen so that their integer forms
do not collide with any EUR amount in the report."""

from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pypdf import PdfReader

from minibook.config.book import load_book
from minibook.config.settings import Settings
from minibook.instruments.bsm import OptionType
from minibook.instruments.equity_option import EquityOption
from minibook.instruments.factory import fx_convention
from minibook.instruments.fx_forward import FxForward
from minibook.instruments.swap import InterestRateSwap
from minibook.pnl.explain import DEFAULT_STEP_ORDER, explain
from minibook.reporting import charts
from minibook.reporting import model as rmodel
from minibook.reporting.guard import IndexLevelLeakError, find_levels
from minibook.reporting.pdf import render
from minibook.risk.backtest import backtest
from minibook.risk.greeks import book_greeks, with_todays_fixings
from minibook.risk.scenarios import historical_scenarios, scenario_dates
from minibook.risk.var import historical_var
from tests.conftest import ROOT
from tests.risk.test_greeks import TRADE, flat_snapshot
from tests.risk.test_var import history

D, P = date(2026, 11, 11), date(2026, 11, 10)
SPOT_PREV, SPOT = 4987.65, 5037.53  # SYNTHETIC index levels (must never be printed)


def report_data(settings: Settings, n_backtest: int = 7) -> tuple[rmodel.ReportData, list[float]]:
    base = flat_snapshot().with_fixings({("EURIBOR6M", TRADE): 0.025})
    prev = dataclasses.replace(base, as_of=P, spots={"SX5E": SPOT_PREV})
    curr = dataclasses.replace(base, as_of=D, spots={"SX5E": SPOT}, vols={"SX5E": 0.19})
    book = load_book(ROOT / "tests" / "fixtures" / "book_template.yaml")
    conv = fx_convention(settings, "EURUSD")
    strike = 4950.12  # SYNTHETIC trade-date level (strike 100% of it)
    insts = [
        InterestRateSwap.create("IRS_EUR_5Y", TRADE, 10_000_000, 0.0311, True),
        FxForward("FXF_EURUSD_6M", "EUR", "USD", 5e6, 1.13, date(2027, 5, 4), conv),
        EquityOption(
            "OPT_SX5E_C_3M_100", "SX5E", OptionType.CALL, 50, 10.0, strike, date(2027, 2, 2)
        ),
    ]
    e = explain(insts, prev, curr, settings.risk, settings.pnl)
    days = scenario_dates(D, 500)
    path = np.random.default_rng(5).normal(scale=0.4, size=len(days)).cumsum()
    snaps = history(dict(zip(days, path, strict=True)))
    snaps[D] = dataclasses.replace(snaps[D], spots={"SX5E": SPOT}).with_fixings(curr.fixings)
    var = historical_var(
        insts,
        snaps[D],
        historical_scenarios(lambda d: snaps[d], D, 500),
        settings.var,
        settings.risk,
    )
    hist = pd.DataFrame(
        {"date": [P, D], "var": [var.var * 0.97, var.var], "es": [var.es * 0.97, var.es]}
    )
    obs = pd.DataFrame(
        {
            "date": pd.bdate_range("2026-11-03", periods=n_backtest).date,
            "var_prev": var.var,
            "pnl": 1000.0,
        }
    )
    bt = backtest(obs, settings.var.var_confidence, settings.backtest)
    per = e.per_instrument.set_index("instrument_id")
    positions = tuple(
        rmodel.PositionRow(
            i.id,
            *rmodel.describe(i, book, curr),
            float(per.loc[i.id, "pv_prev"]),
            float(per.loc[i.id, "pv_curr"]),
        )
        for i in insts
    )
    data = rmodel.ReportData(
        as_of=D,
        prev=P,
        positions=positions,
        greeks=book_greeks(insts, with_todays_fixings(insts, curr), settings.risk),
        explain=e,
        step_order=tuple(s.value for s in DEFAULT_STEP_ORDER),
        var=var,
        var_history=hist,
        backtest=bt,
        eur_curve=rmodel.eur_curve_table(prev, curr),
        moves=rmodel.market_moves(prev, curr),
        vols=rmodel.vol_table(prev, curr),
        key_pillars=curr.key_pillars,
        quality=rmodel.quality_lines(curr, book),
        notes=rmodel.standard_notes(retrospective=True),
        sources=rmodel.SOURCES,
        data_timestamps={"ecb/fx": "2026-11-12T13:00:00+00:00"},
        git_sha="0123456789abcdef",
        config_hash="cafebabe1234",
    )
    return data, [SPOT_PREV, SPOT, strike]


def pdf_text(path: Path) -> tuple[int, str]:
    reader = PdfReader(str(path))
    return len(reader.pages), "\n".join(p.extract_text() for p in reader.pages)


def test_report_is_valid_and_within_budget(tmp_path: Path, settings: Settings) -> None:
    data, levels = report_data(settings)
    out = tmp_path / "report.pdf"
    texts = render(data, out, levels)
    n_pages, text = pdf_text(out)
    assert out.read_bytes().startswith(b"%PDF") and 1 <= n_pages <= 5  # brief: <= 5 pages
    for heading in (
        "1. Executive summary",
        "2. Positions and valuations",
        "3. Greeks",
        "4. P&L attribution",
        "5. Risk",
        "6. Market",
        "Notes, sources",
    ):
        assert heading in text, heading
    assert "insufficient observations (N = 7)" in text  # owner rule, never a zone
    assert "zone" not in text.lower().replace("time zone", "")
    assert "Vol proxy (a)" in text and "Vol proxy (b)" in text
    assert "Backfilled report" in text and "git 0123456789abcdef" in text
    assert "strike 100% of" in text
    # Index-level rule: no form of a synthetic level, including integers, in rendered text
    # or in the PDF's extracted text.
    assert find_levels([*texts, text], levels, integers=True) == []


def test_report_is_deterministic(tmp_path: Path, settings: Settings) -> None:
    data, levels = report_data(settings)
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    render(data, a, levels)
    render(data, b, levels)
    assert a.read_bytes() == b.read_bytes()


def test_leaked_level_aborts_before_writing(tmp_path: Path, settings: Settings) -> None:
    data, levels = report_data(settings)
    leaky = dataclasses.replace(data, quality=(*data.quality, f"SX5E closed at {SPOT:,.2f}"))
    out = tmp_path / "leak.pdf"
    with pytest.raises(IndexLevelLeakError, match=r"5,037\.53"):
        render(leaky, out, levels)
    assert not out.exists()


def test_full_sample_backtest_shows_zone(tmp_path: Path, settings: Settings) -> None:
    data, levels = report_data(settings, n_backtest=250)
    out = tmp_path / "r.pdf"
    render(data, out, levels)
    assert "green zone (0 exceptions in the last 250 days)" in pdf_text(out)[1]


def test_charts_are_png_and_deterministic() -> None:
    moves = pd.DataFrame(
        {"name": ["EUR/USD", "SX5E"], "kind": ["FX", "Index"], "ret": [-0.004, 0.012]}
    )  # SYNTHETIC
    a, b = charts.moves_chart(moves), charts.moves_chart(moves)
    assert a.startswith(b"\x89PNG") and a == b
    hist = pd.DataFrame({"date": [D], "var": [1000.0], "es": [1100.0]})
    assert charts.var_history_chart(hist, "VaR", "ES").startswith(b"\x89PNG")
    assert charts.histogram_chart(np.linspace(-5e4, 5e4, 101), 4e4, 4.5e4, "VaR", "ES").startswith(
        b"\x89PNG"
    )


def test_quality_lines_and_moves(settings: Settings) -> None:
    snap = flat_snapshot()
    book = load_book(ROOT / "tests" / "fixtures" / "book_template.yaml")
    assert rmodel.quality_lines(snap, book) == ("No forward-fills or data-quality flags today.",)
    moves = rmodel.market_moves(snap, snap)
    assert set(moves["kind"]) == {"FX", "Index"} and (moves["ret"] == 0.0).all()
