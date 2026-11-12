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
- **CI**: pushed to github.com/nadirsayed/minibook; GitHub Actions run 43226781882 green
  (ruff, format, mypy --strict, pytest).

- **M2 dates, curves, bootstrap, snapshot**:
  - `dates/`: TARGET, US (Fed), Japan calendars match QuantLib on every day 2022–2030;
    ACT/360, ACT/365F, 30/360 Bond Basis (QuantLib, hypothesis); MF/F/P; tenors;
    backward schedules (swap schedules identical to QuantLib).
  - `market/curves.py` ZeroCurve (ADR-009); `svensson.py` (rebuild ≤ 0.1 bp on every
    fixture day; 38-pillar EUR grid, 0.54 bp worst interpolation error); `bootstrap.py`
    (USD bills + semi-annual par, JGB semi-annual par; inputs reprice to < 1e-8 bp);
    `vol.py` EWMA proxy; `snapshot.py` immutable MarketSnapshot, risk factors, `bump/apply`;
    `builder.py` builds a snapshot for D with fill log, staleness errors, Svensson check.
  - 122 tests, 98% coverage overall.

- **Owner decisions 2026-11-12 (round 2)** applied: ADR-011 on (closure exemption with
  per-market calendars), ADR-012 (Treasury primary, FRED cross-check, identical on all 860
  shared dates), exchange calendars ADR-013 (match observed closes exactly), Yahoo local
  only ADR-014, EWMA vol (STOXX terms forbid personal use too). 131 tests.

- **M3 pricers**: `instruments/` swap (QuantLib-identical), FX forward (spot-date
  discounting, ADR-015), BSM option (Hull/Haug/QuantLib checks), immutable EURIBOR proxy
  fixing store (ADR-016), book.yaml + pydantic models, instrument factory.
- **init-book run 2026-11-12** on real data, trade date 2026-11-02: par rate 3.113412%,
  EURUSD 6M outright 1.129906 (spot 1.1216), USDJPY 3M outright 156.8976 (spot 157.8994),
  option strikes from the 2 Nov closes; fixing EURIBOR6M 2026-11-02 = 2.700604%. Re-run
  verifies (idempotent). Option terms in git-ignored config/book.private.yaml (ADR-018). Swap and forwards PV = 0.00 at the trade date. 162 tests, 98%.

## Next
- M4 Greeks: delta/gamma/vega/theta per brief units, DV01 + key-rate DV01 per currency
  (FX forwards too), FX risk on EUR/USD and EUR/JPY; every analytical Greek vs central FD;
  DV01 on synthetic flat 2.5% vs analytic annuity.

## Open issues (owner)
1. **Dividend yields** (SX5E, CAC 40, FTSE MIB): owner sends them. Three of four options
   cannot be priced until then. Until then options
   cannot be priced in a report (placeholder in tests only). DAX q = 0 (total-return index).
2. **Yahoo ^STOXX50E gaps** on Swiss holidays (ADR-013): forward-filled as "source gap".
   Fine for now; a better SX5E close source would remove them.
3. **Option terms location** (ADR-018): option strikes/closes are in the git-ignored
   `config/book.private.yaml` (Yahoo-derived, never committed). Owner to confirm, or allow
   committing them as trade terms.
