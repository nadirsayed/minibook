# PROGRESS

Resume point for a new session. Updated after each milestone.

## Done
- **Source probe** (`scripts/probe_sources.py`, run 2026-11-12): all primary sources
  reachable with history from 2023-06-01 or earlier. Svensson rebuild vs ECB SR_1Y/5Y/10Y:
  max |error| 1.4e-8 bp over 881 days (tolerance 0.1 bp).
  - ECB YC Svensson, EXR USD/JPY, €STR: OK. (EXR USD timed out once at 60 s; fetchers need
    retry with backoff.)
  - FRED fredgraph.csv: OK from Python `requests`. Plain `curl` with its default user agent
    gets an empty reply (Akamai), so use the requests client.
  - MoF jgbcme.csv (current month) + jgbcme_all.csv (to previous month end): OK, stitched.
  - STOXX h_v2tx.txt: OK (1999 onwards). Yahoo ^V2TX: not available (ADR-002).
  - yfinance ^STOXX50E, ^GDAXI, ^FCHI, FTSEMIB.MI: OK; current-day bar is intraday (ADR-003).
- **M0 scaffold + CI**: uv project, src layout, Typer CLI stubs, ruff, mypy --strict,
  pytest + coverage, pre-commit, GitHub Actions workflow.

## Next
- M1: data layer (ecb, fred, mof, equities, stoxx), raw payload + parquet cache with fetch
  timestamps, recorded fixtures in tests/fixtures/.

## Open issues
- GitHub repo `nadirsayed/minibook` not accessible from this session (not found, or no
  access). Commits are local only; CI has not run on GitHub yet.
- MoF JGB yield convention (compounding / par vs. yield-to-maturity of benchmark issues)
  still to be confirmed from MoF documentation before the M2 bootstrap.
- Usage terms of the STOXX h_v2tx.txt file still to be documented (M1).
- Dividend-yield factsheets (trade date 2026-11-30) can only be retrieved after the trade date.
- Schedule changed from Tue–Sat to Mon–Fri (ADR-001); awaiting owner confirmation.
