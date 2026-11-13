# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added
- Scenario artefact flag (ADR-028): ECB AAA vs all-ratings gap detector (> 5 sigma move,
  mostly reversed within 2 business days; thresholds in config). Flagged scenarios stay in
  VaR/ES; the report lists them and shows VaR99/ES97.5 with and without them.
- Executive summary shows the 90% bootstrap interval next to VaR99 and ES97.5.
- M8: `minibook run --date`, `backfill`, `daily` (scheduled catch-up with ECB readiness
  check), incremental `fetch`; daily GitHub Actions workflow; committed outputs and reports.
- Seeded bootstrap confidence intervals for VaR99 and ES97.5 (shown in the report).
- M7 PDF report (<= 5 pages): summary, positions, Greeks + key-rate charts, P&L waterfall
  with breach notes and step attribution, VaR/ES histogram and history, worst scenarios,
  market moves; notes and sources; index-level guard; deterministic output.
- M6: historical scenarios (500 x 71 factors), full-revaluation VaR99/ES97.5, standalone,
  diversification, worst scenarios, delta-gamma VaR; backtesting (Kupiec POF, Basel traffic
  light, "insufficient observations" below 250).
- M5 P&L explain: actual vs explained per instrument, factor components, breach flag,
  vanna+volga diagnostic with breach notes, revaluation step attribution; fixing service.
- Owner dividend-yield assumptions (ADR-021).
- M4 Greeks engine: analytical option and FX Greeks, revaluation theta, DV01 and key-rate
  DV01 per currency, option dividend-yield sensitivity (EUR per +10bp); long-format output.
- Private option terms digest (`private_terms_sha256`) to detect a wrong secret.
- M3 pricers: EUR IRS (QuantLib cross-checked), FX forwards with spot-date discounting,
  BSM index options with analytical partials; immutable EURIBOR proxy fixing store;
  config/book.yaml with pydantic models; `minibook init-book` (freeze + verify).
- U.S. Treasury daily par yield curve fetcher (primary USD source) with FRED cross-check
  quality flag; exchange calendars (Euronext Paris, Xetra, Eurex, Borsa Italiana);
  docs/methodology.md (forward-fill and VaR reopening-day treatment).
- M2: TARGET/US/JP calendars, day counts, tenors, schedules; ZeroCurve with key-rate
  tents; ECB Svensson EUR curve with validation; USD/JPY par-to-zero bootstrap; EWMA vol
  proxy; immutable MarketSnapshot with risk factors and bumps; SnapshotBuilder with
  forward-fill log and staleness checks (market-closure exemption, off by default).
- M1 data layer: HTTP client with retry/backoff; raw payload archive and parquet store
  with fetch timestamps, revision log and `as_of` filtering; ECB, FRED, MoF and yfinance
  fetchers; record/replay fixtures; `minibook fetch` command.
- CLAUDE.md with standing instructions and owner decisions; docs/data_sources.md.

### Changed
- P&L explain uses the period theta (revaluation t-1 -> t, market held at t-1) instead of
  theta_1d x calendar days (owner, ADR-022).
- DV01 and key-rate DV01 are central differences (owner).
- Snapshot builder: indexed as-of lookups and one-pass EWMA (22x faster, identical results).
- Step attribution accepts any order.
- Dividend yields moved to `assumptions.dividend_yields` (value, source, date; ADR-019).
- Market-closure exemption to the 3-day forward-fill limit enabled (ADR-011).
- USD curve bootstrapped from Treasury (adds 2M and 4M bill pillars); FRED is cross-check.
- Trade date moved to 2026-11-02 (ADR-004); run schedule Mon–Fri (ADR-001).
- STOXX VSTOXX file and Yahoo ^V2TX removed from the source probe (ADR-002).

### Fixed
- ECB request URLs are now independent of key order (deterministic caching and replay).

- `scripts/probe_sources.py`: probes every market-data source, prints sample rows, checks
  history coverage, and validates the ECB Svensson rebuild against SR_1Y/5Y/10Y.
- Project scaffold: uv/pyproject (Python 3.12), src layout, Typer CLI stubs
  (`init-book`, `fetch`, `run`, `backfill`), ruff, mypy --strict, pytest, pre-commit, CI.
