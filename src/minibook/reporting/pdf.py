"""Daily PDF risk report (reportlab + matplotlib), at most 5 pages.

Sections (brief): 1 executive summary with data quality, 2 positions and valuations,
3 Greeks by instrument and risk factor with key-rate DV01 charts, 4 P&L attribution
(waterfall, per-instrument table, breach notes, step attribution), 5 risk (scenario histogram,
VaR/ES history, worst scenarios, backtest), 6 market (EUR curve, FX and index moves as %
returns, vol proxy), then notes: sources, data timestamps, git SHA, simplifications.

Determinism: reportlab's invariant mode (fixed creation date and document id) and charts
without timestamps, so the same inputs give the same bytes. Every string drawn is collected
and checked by :func:`minibook.reporting.guard.check_no_levels` before the file is written.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from pathlib import Path

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from minibook.reporting import charts
from minibook.reporting.guard import check_no_levels
from minibook.reporting.model import ReportData

rl_config.invariant = 1  # deterministic PDF bytes

MARGIN = 13 * mm
CONTENT_W = A4[0] - 2 * MARGIN
HEADER_BG = colors.HexColor("#f0efec")
GRID = colors.HexColor("#e1e0d9")
INK = colors.HexColor("#0b0b0b")
INK_2 = colors.HexColor("#52514e")
FLAG = colors.HexColor("#d03b3b")
COMPONENT_LABELS = {
    "theta": "Theta",
    "rates": "Rates",
    "fx_delta": "FX delta",
    "fx_gamma": "FX gamma",
    "eq_delta": "Eq delta",
    "eq_gamma": "Eq gamma",
    "vega": "Vega",
}


class _Writer:
    """Collects flowables and every string drawn (for the index-level guard)."""

    def __init__(self) -> None:
        base = getSampleStyleSheet()
        self.h1 = ParagraphStyle(
            "h1", parent=base["Heading1"], fontSize=13, spaceAfter=2, textColor=INK
        )
        self.h2 = ParagraphStyle(
            "h2", parent=base["Heading2"], fontSize=10, spaceBefore=5, spaceAfter=3, textColor=INK
        )
        self.body = ParagraphStyle(
            "body", parent=base["BodyText"], fontSize=7.5, leading=9.5, textColor=INK
        )
        self.small = ParagraphStyle(
            "small", parent=self.body, fontSize=6.5, leading=8, textColor=INK_2
        )
        self.cell = ParagraphStyle("cell", parent=self.body, fontSize=6.8, leading=8.2)
        self.num = ParagraphStyle("num", parent=self.cell, alignment=TA_RIGHT)
        self.story: list[object] = []
        self.texts: list[str] = []

    def p(self, text: str, style: ParagraphStyle | None = None) -> Paragraph:
        self.texts.append(text)
        return Paragraph(text, style or self.body)

    def add(self, *flows: object) -> None:
        self.story.extend(flows)

    def table(
        self,
        header: Sequence[str],
        rows: Sequence[Sequence[object]],
        widths: Sequence[float],
        numeric_from: int = 1,
        bold_last: bool = False,
    ) -> Table:
        def cell(text: str, col: int) -> Paragraph:
            return self.p(text, self.num if col >= numeric_from else self.cell)

        data = [[cell(f"<b>{h}</b>", k) for k, h in enumerate(header)]]
        data += [[cell(str(v), k) for k, v in enumerate(r)] for r in rows]
        t = Table(data, colWidths=list(widths), repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, GRID),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 1.2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ]
        if bold_last:
            style.append(("LINEABOVE", (0, -1), (-1, -1), 0.6, INK_2))
        t.setStyle(TableStyle(style))
        return t


def _eur(x: float) -> str:
    return f"{x:,.0f}"


def _image(png: bytes, width: float) -> Image:
    img = Image(io.BytesIO(png))
    img.drawWidth, img.drawHeight = width, width * img.imageHeight / img.imageWidth
    return img


def _pct(conf: float) -> str:
    return f"{100 * conf:g}%"


def _summary(w: _Writer, d: ReportData) -> None:
    per = d.explain.per_instrument
    book = d.explain.book
    pv = float(per["pv_curr"].sum())
    unexpl_pct = (100 * book["unexplained"] / book["actual"]) if book["actual"] else 0.0
    var_l, es_l = f"VaR {_pct(d.var.var_confidence)}", f"ES {_pct(d.var.es_confidence)}"
    w.add(
        w.p(f"minibook daily risk report - {d.as_of}", w.h1),
        w.p(
            f"Valuation date {d.as_of} (P&amp;L from {d.prev}). Reporting currency EUR. "
            "Market data: ECB, U.S. Treasury, Japan MoF, Yahoo Finance (local use). "
            "Options are hypothetical contracts (not listed-contract replication); the "
            "volatility is an EWMA realized-vol proxy.",
            w.small,
        ),
    )
    w.add(w.p("1. Executive summary", w.h2))
    head = ["Book PV", "Actual P&amp;L", "Explained", "Unexplained", var_l, es_l]
    row = [
        _eur(pv),
        _eur(book["actual"]),
        _eur(book["explained"]),
        f"{_eur(book['unexplained'])} ({unexpl_pct:+.1f}%)",
        _eur(d.var.var),
        _eur(d.var.es),
    ]
    w.add(w.table(head, [row], [CONTENT_W / 6] * 6, numeric_from=0), Spacer(1, 3))
    flagged = per[per["flagged"]]
    w.add(
        w.p(
            f"<b>Breaches:</b> {len(flagged)} instrument(s) above the unexplained threshold "
            f"(max(5% of |actual|, EUR 1,000))"
            + (": " + ", ".join(flagged["instrument_id"]) if len(flagged) else ".")
        )
    )
    w.add(
        w.p(
            f"<b>Backtesting:</b> {d.backtest.status}. Exceptions so far: "
            f"{d.backtest.exceptions} (expected {d.backtest.expected:.1f})."
        )
    )
    w.add(w.p("<b>Data quality</b>", w.body))
    for line in d.quality:
        w.add(w.p(f"- {line}", w.small))


def _positions(w: _Writer, d: ReportData) -> None:
    w.add(w.p("2. Positions and valuations (EUR)", w.h2))
    rows = [
        [
            p.instrument_id,
            p.description,
            str(p.maturity),
            _eur(p.pv_prev),
            _eur(p.pv_curr),
            _eur(p.pv_curr - p.pv_prev),
        ]
        for p in d.positions
    ]
    tot_prev = sum(p.pv_prev for p in d.positions)
    tot = sum(p.pv_curr for p in d.positions)
    rows.append(["Book", "", "", _eur(tot_prev), _eur(tot), _eur(tot - tot_prev)])
    widths = [30 * mm, 75 * mm, 18 * mm, 19 * mm, 19 * mm, CONTENT_W - 161 * mm]
    w.add(
        w.table(
            ["Instrument", "Description", "Maturity", f"PV {d.prev}", f"PV {d.as_of}", "Change"],
            rows,
            widths,
            numeric_from=3,
            bold_last=True,
        )
    )
    w.add(w.p("PV change includes no cashflows; P&amp;L below adds cashflows received.", w.small))


def _greeks(w: _Writer, d: ReportData) -> None:
    g = d.greeks
    w.add(w.p("3. Greeks (EUR; change in PV for an increase of the factor)", w.h2))

    def val(inst: str, measure: str, factor: str | None = None) -> float:
        m = (g["instrument_id"] == inst) & (g["measure"] == measure)
        if factor is not None:
            m &= g["risk_factor"] == factor
        return float(g.loc[m, "value"].sum())

    rows = []
    for p in d.positions:
        i = p.instrument_id
        rows.append(
            [
                i,
                _eur(val(i, "theta_1d")),
                _eur(val(i, "dv01", "PAR:EUR")),
                _eur(val(i, "dv01", "PAR:USD")),
                _eur(val(i, "dv01", "PAR:JPY")),
                _eur(val(i, "vega_1pt")),
                _eur(val(i, "div_10bp")),
            ]
        )
    w.add(
        w.table(
            [
                "By instrument",
                "Theta 1d",
                "DV01 EUR",
                "DV01 USD",
                "DV01 JPY",
                "Vega 1pt",
                "q +10bp",
            ],
            rows,
            [36 * mm] + [(CONTENT_W - 36 * mm) / 6] * 6,
        )
    )
    w.add(Spacer(1, 3))
    factors = sorted({f for f in g["risk_factor"] if f.startswith(("EQ:", "FX:"))})
    frows = []
    for f in factors:
        m = g["risk_factor"] == f
        name = f.split(":", 1)[1]
        label = f"EUR/{name}" if f.startswith("FX:") else name
        delta = float(g.loc[m & (g["measure"] == "delta_1pct"), "value"].sum())
        gamma = float(g.loc[m & (g["measure"] == "gamma_1pct"), "value"].sum())
        vega = float(g.loc[(g["risk_factor"] == f"VOL:{name}"), "value"].sum())
        div = float(g.loc[(g["risk_factor"] == f"DIV:{name}"), "value"].sum())
        frows.append(
            [
                label,
                _eur(delta),
                _eur(gamma),
                _eur(vega) if f.startswith("EQ:") else "",
                _eur(div) if f.startswith("EQ:") else "",
            ]
        )
    w.add(
        w.table(
            ["By risk factor", "Delta 1%", "Gamma 1%", "Vega 1pt", "q +10bp"],
            frows,
            [36 * mm] + [(CONTENT_W - 36 * mm) / 4] * 4,
        )
    )
    w.add(
        Spacer(1, 3),
        _image(charts.kr_dv01_chart(g, d.key_pillars, ["EUR", "USD", "JPY"]), CONTENT_W),
    )
    w.add(
        w.p(
            "DV01 and key-rate DV01 are central differences [PV(+1bp) - PV(-1bp)]/2 on zero "
            "rates. Gamma 1% is the Taylor gamma (0.01 S)^2 V_SS. Theta is one calendar day "
            "with the market held constant. q +10bp: sensitivity to the owner's dividend-yield "
            "assumption.",
            w.small,
        )
    )


def _pnl(w: _Writer, d: ReportData) -> None:
    e = d.explain
    w.add(w.p("4. P&amp;L attribution", w.h2))
    comp = e.components.groupby("component")["value"].sum()
    steps = [(label, float(comp.get(key, 0.0))) for key, label in COMPONENT_LABELS.items()]
    b = e.book
    w.add(
        _image(
            charts.waterfall_chart(steps, b["explained"], b["unexplained"], b["actual"]), CONTENT_W
        )
    )
    rows = []
    for r in e.per_instrument.to_dict("records"):
        rows.append(
            [
                r["instrument_id"],
                _eur(r["actual"]),
                _eur(r["explained"]),
                _eur(r["unexplained"]),
                _eur(r["omitted_2nd_order"]),
                "BREACH" if r["flagged"] else "",
            ]
        )
    rows.append(
        [
            "Book",
            _eur(b["actual"]),
            _eur(b["explained"]),
            _eur(b["unexplained"]),
            _eur(float(e.per_instrument["omitted_2nd_order"].sum())),
            "",
        ]
    )
    w.add(
        w.table(
            ["Instrument", "Actual", "Explained", "Unexplained", "Vanna+volga (diag.)", "Flag"],
            rows,
            [36 * mm] + [(CONTENT_W - 36 * mm) / 5] * 5,
            bold_last=True,
        )
    )
    notes = e.per_instrument[e.per_instrument["flagged"]]
    for r in notes.to_dict("records"):
        w.add(w.p(f"<b>{r['instrument_id']}</b>: {r['note']}", w.small))
    st = e.steps.pivot_table(
        index="instrument_id", columns="step", values="value", aggfunc="sum", sort=False
    )
    cols = [*d.step_order, "other"]
    srows = [[i, *[_eur(float(st.loc[i, c])) for c in cols]] for i in st.index]
    w.add(
        Spacer(1, 3),
        w.p(
            "Revaluation step attribution (full revaluation, order: "
            + " -> ".join(cols)
            + "; order-dependent, methodology §7.1)",
            w.small,
        ),
    )
    w.add(
        w.table(
            ["Instrument", *cols],
            srows,
            [36 * mm] + [(CONTENT_W - 36 * mm) / len(cols)] * len(cols),
        )
    )


def _risk(w: _Writer, d: ReportData) -> None:
    v = d.var
    var_l, es_l = f"VaR {_pct(v.var_confidence)}", f"ES {_pct(v.es_confidence)}"
    w.add(
        w.p(
            f"5. Risk: historical simulation, full revaluation, {v.n_scenarios} scenarios, 1 day",
            w.h2,
        )
    )
    hist = charts.histogram_chart(v.pnl.sum(axis=1).to_numpy(), v.var, v.es, var_l, es_l)
    histo = charts.var_history_chart(d.var_history, var_l, es_l)
    pair = Table(
        [[_image(hist, CONTENT_W / 2 - 2 * mm), _image(histo, CONTENT_W / 2 - 2 * mm)]],
        colWidths=[CONTENT_W / 2] * 2,
    )
    w.add(pair)
    dg = (
        ""
        if v.delta_gamma_var is None
        else f"; delta-gamma {var_l} {_eur(v.delta_gamma_var)}, "
        f"{es_l} {_eur(v.delta_gamma_es or 0)}"
    )
    w.add(
        w.p(
            f"<b>{var_l}</b> {_eur(v.var)}, <b>{es_l}</b> {_eur(v.es)} (EUR, positive = loss). "
            f"Sum of standalone {var_l}: {_eur(float(v.standalone['var'].sum()))}; "
            f"diversification benefit {_eur(v.diversification_var)}{dg}. ES and VaR are at "
            "different confidence levels, so ES can be below VaR."
        )
    )
    rows = [[i, _eur(float(r["var"])), _eur(float(r["es"]))] for i, r in v.standalone.iterrows()]
    left = w.table(["Standalone", var_l, es_l], rows, [32 * mm, 22 * mm, 22 * mm])
    wrows = []
    for date_, r in v.worst.iterrows():
        contrib = r.drop("total")
        top = str(contrib.abs().idxmax())
        wrows.append([str(date_), _eur(float(r["total"])), f"{top} {_eur(float(contrib[top]))}"])
    right = w.table(
        ["Worst scenario", "Book P&amp;L", "Largest contributor"],
        wrows,
        [22 * mm, 20 * mm, 52 * mm],
    )
    w.add(
        Spacer(1, 3),
        Table(
            [[left, right]],
            colWidths=[80 * mm, CONTENT_W - 80 * mm],
            style=[("VALIGN", (0, 0), (-1, -1), "TOP")],
        ),
    )


def _market(w: _Writer, d: ReportData) -> None:
    w.add(w.p("6. Market", w.h2))
    curve = charts.eur_curve_chart(d.eur_curve, str(d.as_of), str(d.prev))
    moves = charts.moves_chart(d.moves)
    w.add(
        Table(
            [[_image(curve, CONTENT_W / 2 - 2 * mm), _image(moves, CONTENT_W / 2 - 2 * mm)]],
            colWidths=[CONTENT_W / 2] * 2,
            style=[("VALIGN", (0, 0), (-1, -1), "TOP")],
        )
    )
    rows = [
        [r["underlying"], f"{100 * r['vol']:.1f}%", f"{100 * r['change']:+.2f} pts"]
        for r in d.vols.to_dict("records")
    ]
    w.add(
        w.table(
            ["Vol proxy (EWMA, lambda 0.94)", "Level", "1-day change"],
            rows,
            [50 * mm, 25 * mm, 25 * mm],
        )
    )


def _notes(w: _Writer, d: ReportData) -> None:
    w.add(w.p("Notes, sources and simplifications", w.h2))
    for n in d.notes:
        w.add(w.p(f"- {n}", w.small))
    w.add(w.p("<b>Sources:</b> " + "; ".join(d.sources), w.small))
    stamps = ", ".join(f"{k}: {v}" for k, v in sorted(d.data_timestamps.items()))
    w.add(w.p(f"<b>Data first fetched (UTC):</b> {stamps}", w.small))
    w.add(w.p(f"<b>Build:</b> git {d.git_sha}, config {d.config_hash}.", w.small))


def render(d: ReportData, path: Path, forbidden_levels: Sequence[float]) -> list[str]:
    """Write the PDF to ``path`` and return every string drawn.

    Raises ``IndexLevelLeakError`` (before writing) if a forbidden index level is rendered.
    """
    w = _Writer()
    _summary(w, d)
    _positions(w, d)
    w.add(PageBreak())
    _greeks(w, d)
    w.add(PageBreak())
    _pnl(w, d)
    w.add(PageBreak())
    _risk(w, d)
    _market(w, d)
    w.add(PageBreak())
    _notes(w, d)
    check_no_levels(w.texts, forbidden_levels)

    footer = f"minibook risk report {d.as_of} - git {d.git_sha[:7]} - config {d.config_hash[:8]}"
    w.texts.append(footer)

    def on_page(canvas: Canvas, doc: SimpleDocTemplate) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(INK_2)
        canvas.drawString(MARGIN, 7 * mm, footer)
        canvas.drawRightString(A4[0] - MARGIN, 7 * mm, f"page {doc.page}")
        canvas.restoreState()

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN + 3 * mm,
        title=f"minibook risk report {d.as_of}",
        author="minibook",
        subject="Daily risk report",
        creator="minibook",
    )
    doc.build(w.story, onFirstPage=on_page, onLaterPages=on_page)
    return w.texts
