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
from minibook.risk.scenario_check import ScenarioFlag
from minibook.risk.scenarios import historical_scenarios, scenario_dates
from minibook.risk.var import historical_var, with_flags
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
    assert "can be recovered from the published option outputs" in " ".join(text.split())
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


def test_summary_shows_bootstrap_brackets(tmp_path: Path, settings: Settings) -> None:
    data, levels = report_data(settings)
    out = tmp_path / "r.pdf"
    render(data, out, levels)
    text = pdf_text(out)[1]
    assert data.var.var_ci is not None
    lo, hi = data.var.var_ci
    assert f"[{lo / 1e3:,.1f}k-{hi / 1e3:,.1f}k]" in text
    assert "90% bootstrap interval" in text
    assert "Scenario check (ADR-028): not run" in text
    checked = dataclasses.replace(data, var=with_flags(data.var, [], settings.var))
    render(checked, out, levels)
    assert "no scenario day flagged" in pdf_text(out)[1]


def test_flagged_scenario_is_listed_and_kept(tmp_path: Path, settings: Settings) -> None:
    data, levels = report_data(settings)
    day = data.var.worst.index[0]
    # SYNTHETIC flag on the worst scenario day, as the detector would produce it.
    flag = ScenarioFlag(day, "SR_5Y", -10.0, 1.4, 9.8, pending=False)
    var = with_flags(data.var, [flag], settings.var)
    out = tmp_path / "r.pdf"
    render(dataclasses.replace(data, var=var), out, levels)
    text = " ".join(pdf_text(out)[1].split())
    assert "suspected AAA curve-fitting artefact" in text
    assert f"{day} *" in text  # marked in the worst-scenario table
    assert var.var_ex_flagged is not None and var.var_ex_flagged != var.var
    assert "without them" in text and "(no cherry-picking)" in text


def test_summary_signs_breach_text_and_key_risks(tmp_path: Path, settings: Settings) -> None:
    data, levels = report_data(settings)
    # SYNTHETIC case like 11 Nov: positive unexplained on a negative actual reads positive.
    per = data.explain.per_instrument.copy()
    for col, total in (("actual", -49_563.0), ("explained", -49_722.0), ("unexplained", 159.0)):
        per[col] = [total] + [0.0] * (len(per) - 1)
    explain = dataclasses.replace(data.explain, per_instrument=per)
    out = tmp_path / "r.pdf"
    render(dataclasses.replace(data, explain=explain), out, levels)
    text = " ".join(pdf_text(out)[1].split())
    assert "159 (+0.3%)" in text
    assert "max(5% of abs(actual P&L), EUR 1,000)" in text and "|" not in text
    g = data.greeks
    dv01_eur = g[(g["measure"] == "dv01") & (g["risk_factor"] == "PAR:EUR")]["value"].sum()
    vega = g[g["measure"] == "vega_1pt"]["value"].sum()
    assert f"Key risks (EUR): DV01 per +1 bp EUR {dv01_eur:,.0f} / USD" in text
    assert "/ JPY 0;" in text  # no JPY instrument in the synthetic book
    assert f"vega per +1 vol pt {vega:,.0f}." in text
