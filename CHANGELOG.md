# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added
- `scripts/probe_sources.py`: probes every market-data source, prints sample rows, checks
  history coverage, and validates the ECB Svensson rebuild against SR_1Y/5Y/10Y.
- Project scaffold: uv/pyproject (Python 3.12), src layout, Typer CLI stubs
  (`init-book`, `fetch`, `run`, `backfill`), ruff, mypy --strict, pytest, pre-commit, CI.
