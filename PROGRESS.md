# PROGRESS

Resume point for a new session. Updated after each milestone. Standing rules: CLAUDE.md.

## Done
- **Source probe** (2026-11-12): ECB (YC Svensson, EXR, €STR), FRED, MoF, yfinance indices OK
  from 2023-06-01. Svensson rebuild vs SR_1Y/5Y/10Y: max |error| 1.4e-8 bp over 881 days.
- **M0 scaffold + CI**: uv, src layout, Typer CLI, ruff, mypy --strict, pytest, pre-commit,
  GitHub Actions workflow.
- **Owner decisions 2026-11-12** recorded in CLAUDE.md and ADR-001/003/004/005.
- **M1 data layer**:
  - `data/http.py`: client protocol, retry with exponential backoff.
  - `data/cache.py`: gzip raw payload archive with sha256/url/fetch-timestamp sidecar;
    long-format parquet store with first/last fetch timestamps; revisions logged and kept;
    `as_of` filter (no look-ahead).
  - Fetchers: `ecb.py` (YC, EXR, EST), `fred.py` (DGS*, one request per series), `mof.py`
    (history + current month), `equities.py` (yfinance, ADR-003 intraday/future-bar filter).
  - `data/replay.py`: record/replay clients. `scripts/record_fixtures.py` records verbatim
    fixtures (MoF history truncated, documented in the manifest).
  - `minibook fetch` CLI implemented. A live run on 2026-11-12 (ECB/FRED/MoF, 2023-06-01 →
    today) took 115 s over the network, and a re-fetch is idempotent.
  - 43 offline tests, 97% coverage on `minibook.data`.

## Next
- M2: TARGET/US/JP calendars, day counts, schedules; Svensson EUR curve (percent→decimal,
  validation ≤ 0.1 bp on fixtures); USD/JPY par→zero bootstrap (ADR-008 for JGB);
  MarketSnapshot with ≤ 3-day forward-fill log.
- `init-book` needs M2 curves + M3 pricers, then runs at trade date 2026-11-02.

## Open issues (owner)
1. **GitHub push blocked**: Claude has no GitHub access to nadirsayed/minibook (HTTP 403).
   Install the Claude GitHub App on the repo or reconnect GitHub. Commits are local only;
   CI has never run.
2. **VSTOXX**: STOXX terms forbid automated download and AI use (ADR-002). Proposal: EWMA
   (λ = 0.94) realized vol for all four indices, labelled as a proxy.
3. **Dividend yields**: the providers' terms forbid automated/AI access. The owner looks up
   the factsheets in a browser and fills `dividend_yields` in book.yaml (value, factsheet
   data date, publication date, URL). Seen during the probe, before the terms were read
   (verify yourself; not used):
   - CAC 40: 3.26%, as of 30 Sep 2026, published 15 Oct 2026 (no look-ahead).
   - FTSE MIB: 4.04%, data as at 30 Oct 2026, publication date unknown.
   - SX5E: 2.4% (STOXX "net dividend yield"), data as of 30 Oct 2026, generated on demand.
   Definitions differ (net vs. gross); flag this in the README.
4. **Yahoo/yfinance terms** restrict automated access and redistribution. The brief chose
   it; owner to confirm. Equity data is not committed (ADR-006).
5. **FRED vs U.S. Treasury**: FRED terms discourage scraping. The Treasury's own
   daily par-yield CSV (home.treasury.gov) is the original source, has more tenors (1.5M,
   2M, 4M), and is one day fresher. Proposal: switch to Treasury, keep FRED as a cross-check.
6. **31 Dec report timing** (ADR-007): if the ECB skips the 31 Dec curve, the report comes
   out on 5 Jan 2027 with a forward-filled 30 Dec curve.
