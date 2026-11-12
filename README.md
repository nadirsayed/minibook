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
- Discrete dividends: replace the flat dividend yield q with discrete dividend forecasts
  (ex-dates concentrated in April-May) or a dividend curve implied from dividend futures.

License: MIT.
