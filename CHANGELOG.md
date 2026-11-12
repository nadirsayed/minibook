# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added
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
