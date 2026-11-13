# minibook

A mini multi-asset derivatives book (EUR IRS, FX forwards, index options), valued every
TARGET business day from real public market data, with Greeks, P&L explain, 99% historical
VaR / 97.5% ES, and a PDF risk report.

> **Status: under construction (M0 scaffold).** See [PROGRESS.md](PROGRESS.md).
> Full README (methodology, sign conventions, limitations) lands in M9.

```bash
uv sync
uv run minibook --help
uv run pytest
```

## How this project was built

I defined the goal and scope of minibook and directed its development. The
specification (the book, the data sources, the methodology, the tests and the
definition of done) was drafted with Claude, Anthropic's AI assistant, and refined
through review. I made the final call on each methodological and data decision,
for example moving the trade date, making the U.S. Treasury the primary USD source,
keeping Yahoo-derived terms out of this public repository, switching DV01 to
central differences and showing no backtesting zone below 250 observations. Each
decision is recorded in [docs/decisions.md](docs/decisions.md). I reviewed every
milestone before the next one started.

The code, the tests and the first drafts of the documentation were written with
[Claude Code](https://claude.com/claude-code), Anthropic's coding agent, working
from the specification and the standing instructions in [CLAUDE.md](CLAUDE.md).
The git history attributes its work: as author up to M6, as co-author from M7 on.

## Daily reports

A risk report is produced for every TARGET business day after the trade date (2 November
2026). It runs on the next TARGET business day, once the ECB has published its yield curve
for the day (around noon CET); the scheduled GitHub Actions workflow "Daily report" retries
every hour until 18:00 CET.

- PDF reports, one per valuation date: [reports/](reports/)
- Data outputs (valuations, Greeks, P&L explain, VaR/ES, run metadata): [output/](output/)

Reports produced after the fact (backfills) say so in their notes. No committed file shows an
index level: option strikes appear as a percentage of the trade-date spot, index moves as
returns.

## Data sources and attribution

- Euro area yield curve (Svensson parameters), euro foreign exchange reference rates, €STR:
  **Source: ECB Data Portal** (ESCB statistics reuse policy).
- U.S. Treasury par yield curve: **Source: U.S. Department of the Treasury** (public domain).
- Cross-check: **Source: FRED, Federal Reserve Bank of St. Louis**; Board of Governors of
  the Federal Reserve System (H.15).
- JGB yields: **Source: Ministry of Finance Japan** (Public Data License 1.0).
- Equity index closes: Yahoo Finance via yfinance, used locally for personal,
  non-commercial purposes. Not redistributed: no equity data is committed to this
  repository.

Details and terms of use: [docs/data_sources.md](docs/data_sources.md).

## Roadmap (beyond v1.0.0)

- JPY short-end anchor: the curve is flat below 1Y today (no free JPY money-market data
  wired in). Candidate: an official overnight or bill rate with terms that allow
  automated use.
- Implied-volatility source that allows automated use, replacing the EWMA proxy.
- Symmetric (Shapley-style) revaluation P&L attribution: average each block's marginal
  contribution over all step orders, removing the order dependence of the current steps.
- Discrete dividends: replace the flat dividend yield q with discrete dividend forecasts
  (ex-dates concentrated in April-May) or a dividend curve implied from dividend futures.

License: MIT.
