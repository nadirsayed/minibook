"""Report charts (matplotlib, Agg backend) rendered to PNG bytes.

Style follows the dataviz method used for this report: light print surface, recessive grid
and axes, thin marks, one y-axis per chart (curve change gets its own panel, never a second
axis), blue/red only for signed quantities (with direct labels), and a legend only with two or
more series. Palette validated with the dataviz validator (blue #2a78d6 / red #e34948:
CVD ΔE 21.6, contrast >= 3:1 on #fcfcfb). Charts receive returns and EUR amounts only, never
index levels (ADR-019).
"""

from __future__ import annotations

import io
from collections.abc import Sequence

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
UP = "#2a78d6"  # gains / primary series
DOWN = "#e34948"  # losses
TOTAL = "#52514e"  # subtotals in the waterfall
DPI = 200
FONT = 7.0

mpl.rcParams.update(
    {
        "font.size": FONT,
        "font.family": "DejaVu Sans",
        "axes.edgecolor": AXIS,
        "axes.labelcolor": INK_2,
        "xtick.color": INK_2,
        "ytick.color": INK_2,
        "axes.titlesize": FONT + 1,
        "axes.titleweight": "bold",
        "axes.titlecolor": INK,
        "axes.facecolor": SURFACE,
        "figure.facecolor": SURFACE,
        "svg.hashsalt": "minibook",
    }
)


def _style(ax: Axes) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(length=2)


def _png(fig: Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(
        buf, format="png", dpi=DPI, bbox_inches="tight", metadata={"Software": None}
    )  # deterministic bytes
    plt.close(fig)
    return buf.getvalue()


def _axis_k(x: float, _pos: int | None = None) -> str:
    return f"{x / 1e3:,.0f}k" if abs(x) >= 1e3 else f"{x:,.0f}"


KFMT = FuncFormatter(_axis_k)


def _k(x: float) -> str:
    return f"{x / 1e3:+,.1f}k"


def kr_dv01_chart(
    greeks: pd.DataFrame, key_pillars: Sequence[str], currencies: Sequence[str]
) -> bytes:
    """Key-rate DV01 per currency (small multiples, EUR per +1bp, book totals)."""
    kr = greeks[greeks["measure"] == "kr_dv01"]
    fig, axes = plt.subplots(1, len(currencies), figsize=(7.1, 1.9), sharey=False)
    for ax, ccy in zip(np.atleast_1d(axes), currencies, strict=True):
        vals = [
            float(kr.loc[kr["risk_factor"] == f"KR:{ccy}:{p}", "value"].sum()) for p in key_pillars
        ]
        x = np.arange(len(key_pillars))
        ax.bar(x, vals, width=0.7, color=[UP if v >= 0 else DOWN for v in vals])
        ax.axhline(0.0, color=AXIS, linewidth=0.8)
        ax.margins(y=0.25)  # room for the direct label above/below the largest bar
        ax.set_xticks(x, key_pillars)
        ax.set_title(f"{ccy}", loc="left")
        ax.yaxis.set_major_formatter(KFMT)
        _style(ax)
        if any(vals):
            i = int(np.argmax(np.abs(vals)))
            ax.annotate(
                f"{vals[i]:+,.0f}",
                (x[i], vals[i]),
                ha="center",
                fontsize=FONT - 0.5,
                color=INK,
                va="bottom" if vals[i] >= 0 else "top",
                xytext=(0, 2 if vals[i] >= 0 else -2),
                textcoords="offset points",
            )
    np.atleast_1d(axes)[0].set_ylabel("key-rate DV01 (EUR per +1bp)")
    fig.tight_layout()
    return _png(fig)


def waterfall_chart(
    steps: Sequence[tuple[str, float]], explained: float, unexplained: float, actual: float
) -> bytes:
    """Explained components, then Explained, Unexplained and Actual (EUR)."""
    labels = [s for s, _ in steps] + ["Explained", "Unexplained", "Actual"]
    fig, ax = plt.subplots(figsize=(7.1, 2.3))
    running = 0.0
    for k, (_, v) in enumerate(steps):
        ax.bar(k, v, bottom=running, width=0.7, color=UP if v >= 0 else DOWN)
        ax.annotate(
            _k(v),
            (k, running + max(v, 0.0)),
            ha="center",
            va="bottom",
            fontsize=FONT - 0.5,
            color=INK,
            xytext=(0, 1),
            textcoords="offset points",
        )
        running += v
    n = len(steps)
    ax.bar(n, explained, width=0.7, color=TOTAL)
    ax.bar(
        n + 1,
        unexplained,
        bottom=explained,
        width=0.7,
        color=UP if unexplained >= 0 else DOWN,
        hatch="////",
        edgecolor=SURFACE,
    )
    ax.bar(n + 2, actual, width=0.7, color=TOTAL)
    for k, v, base in ((n, explained, 0.0), (n + 1, unexplained, explained), (n + 2, actual, 0.0)):
        ax.annotate(
            _k(v),
            (k, base + max(v, 0.0)),
            ha="center",
            va="bottom",
            fontsize=FONT - 0.5,
            color=INK,
            xytext=(0, 1),
            textcoords="offset points",
        )
    ax.axhline(0.0, color=AXIS, linewidth=0.8)
    ax.set_xticks(range(len(labels)), labels, rotation=0)
    ax.set_ylabel("EUR")
    ax.yaxis.set_major_formatter(KFMT)
    ax.margins(y=0.15)  # headroom for bar labels; the report section heading is the title
    _style(ax)
    fig.tight_layout()
    return _png(fig)


def histogram_chart(
    pnl_total: np.ndarray, var: float, es: float, var_label: str, es_label: str
) -> bytes:
    """Scenario P&L distribution with VaR and ES lines (EUR)."""
    fig, ax = plt.subplots(figsize=(3.5, 2.1))
    ax.hist(pnl_total, bins=40, color=UP, edgecolor=SURFACE, linewidth=0.5)
    for x, label, style, color in ((-var, var_label, "-", DOWN), (-es, es_label, "--", INK)):
        ax.axvline(x, color=color, linestyle=style, linewidth=1.2, label=f"{label} {abs(x):,.0f}")
    # VaR and ES lines are often a few k apart: a legend avoids colliding line labels.
    ax.legend(frameon=False, fontsize=FONT - 0.5, loc="upper right")
    ax.xaxis.set_major_formatter(KFMT)
    ax.set_xlabel("1-day scenario P&L (EUR)")
    ax.set_ylabel("scenarios")
    ax.set_title("Historical scenarios", loc="left")
    _style(ax)
    fig.tight_layout()
    return _png(fig)


def var_history_chart(history: pd.DataFrame, var_label: str, es_label: str) -> bytes:
    """VaR and ES over time (EUR); two series, legend plus last-point labels."""
    fig, ax = plt.subplots(figsize=(3.5, 2.1))
    h = history.sort_values("date")
    for col, label, color, style in (("var", var_label, UP, "-"), ("es", es_label, INK_2, "--")):
        ax.plot(
            pd.to_datetime(h["date"]),
            h[col],
            color=color,
            linewidth=1.6,
            linestyle=style,
            marker="o" if len(h) < 3 else None,
            markersize=3,
            label=label,
        )
    if len(h):
        last = h.iloc[-1]
        ax.annotate(
            f"{last['var']:,.0f}",
            (pd.to_datetime(last["date"]), last["var"]),
            fontsize=FONT - 0.5,
            color=INK,
            xytext=(3, 0),
            textcoords="offset points",
        )
    ax.set_ylabel("EUR")
    ax.set_title(f"VaR / ES history ({len(h)} day(s))", loc="left")
    ax.legend(frameon=False, fontsize=FONT - 0.5, loc="best")
    # matplotlib.dates is untyped: narrow ignores for these two constructor calls.
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=2, maxticks=5))  # type: ignore[no-untyped-call]
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))  # type: ignore[no-untyped-call]
    ax.yaxis.set_major_formatter(KFMT)
    ax.margins(y=0.15)
    _style(ax)
    fig.tight_layout()
    return _png(fig)


def eur_curve_chart(curve: pd.DataFrame, today: str, prev: str) -> bytes:
    """EUR zero curve today vs t-1 (top) and the change in bp (bottom panel, own axis)."""
    fig, (top, bottom) = plt.subplots(
        2, 1, figsize=(3.5, 2.8), sharex=True, gridspec_kw={"height_ratios": [2, 1]}
    )
    top.plot(curve["t"], curve["prev"], color=MUTED, linewidth=1.4, label=prev)
    top.plot(curve["t"], curve["today"], color=UP, linewidth=1.8, label=today)
    top.set_ylabel("zero rate (%)")
    top.set_title("EUR AAA zero curve (ECB Svensson)", loc="left")
    top.legend(frameon=False, fontsize=FONT - 0.5)
    change = 100 * (curve["today"] - curve["prev"])
    bottom.plot(curve["t"], change, color=UP, linewidth=1.4)
    bottom.axhline(0.0, color=AXIS, linewidth=0.8)
    bottom.set_ylabel("change (bp)")
    bottom.set_xlabel("maturity (years)")
    for ax in (top, bottom):
        _style(ax)
    fig.tight_layout()
    return _png(fig)


def moves_chart(moves: pd.DataFrame) -> bytes:
    """Daily % returns of EUR FX rates and indices, signed colours and direct labels."""
    m = moves.iloc[::-1]
    fig, ax = plt.subplots(figsize=(3.5, 2.1))
    vals = 100 * m["ret"].to_numpy()
    y = np.arange(len(m))
    ax.barh(y, vals, height=0.6, color=[UP if v >= 0 else DOWN for v in vals])
    ax.axvline(0.0, color=AXIS, linewidth=0.8)
    ax.set_yticks(y, m["name"])
    for yi, v in zip(y, vals, strict=True):
        ax.annotate(
            f"{v:+.2f}%",
            (v, yi),
            va="center",
            ha="left" if v >= 0 else "right",
            fontsize=FONT - 0.5,
            color=INK,
            xytext=(2 if v >= 0 else -2, 0),
            textcoords="offset points",
        )
    lim = max(0.5, float(np.abs(vals).max()) * 1.4) if len(vals) else 1.0
    ax.set_xlim(-lim, lim)
    ax.set_xlabel("1-day return (%)")
    ax.set_title("FX and index moves", loc="left")
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_axisbelow(True)
    fig.tight_layout()
    return _png(fig)
