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

- **Owner decisions round 3** (CLAUDE.md 12-14): secret `BOOK_PRIVATE_YAML_B64` + digest
  check; no index levels in committed outputs; EWMA confirmed and documented
  (methodology §4); dividend yields as `assumptions` block.
- **M4 Greeks** (`risk/greeks.py`, ADR-020): analytic option delta/gamma/vega/q-sensitivity
  and FX delta/gamma (EUR translation included), all vs central FD at rel 1e-4; theta by
  1-day revaluation with today's fixings set; DV01 and key-rate DV01 for EUR/USD/JPY
  (DV01 = closed form on flat 2.5%, = annuity·e^z·1bp to 1e-3; key rates sum to parallel).
  Real-book run 2026-11-11: IRS DV01 +4.2k/bp, EURUSD fwd +49.7k per 1%. 177 tests, 98% coverage.

- **Dividend assumptions** (owner): SX5E 2.6%, CAC 40 3.0%, FTSE MIB 3.9%, look-ahead flagged
  (ADR-021); seasonality limitation in methodology §6; roadmap item.
- **M5 P&L explain** (`pnl/explain.py`, ADR-022): actual (with cashflows) vs Greeks-based
  explained per instrument; factor components; flag at max(5%, EUR 1k); vanna+volga
  diagnostic and breach notes; exact revaluation step attribution; `fixing_service.py`
  records each day's due fixings (also used by init-book). Convergence: spot-only cubic,
  spot+vol quadratic, rates quadratic. Real run 3-11 Nov: breaches only on options, on
  big-move days, vanna+volga = 90-115% of each breach's unexplained. 186 tests, 98% coverage.

## Next
- M6 VaR/ES: 500 joint historical shocks (full revaluation, valuation date fixed), VaR99,
  ES97.5, standalone and diversification, 5 worst scenarios with dates; Gaussian tests;
  bonus delta-gamma VaR and backtesting (Kupiec, traffic light).

## Open issues (owner)
1. **Dividend yields** (SX5E, CAC 40, FTSE MIB): owner sends them as assumptions (value,
   source, date). Three of four options cannot be priced until then. Until then options
   cannot be priced in a report (placeholder in tests only). DAX q = 0 (total-return index).
2. **Yahoo ^STOXX50E gaps** on Swiss holidays (ADR-013): forward-filled as "source gap".
   Fine for now; a better SX5E close source would remove them.
3. **GitHub secret** `BOOK_PRIVATE_YAML_B64` to be created by the owner (needed from M8).
