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

- **Round 4 adjustments**: central DV01 (rates explain now cleanly quadratic, key rates sum
  to parallel at 1e-6); orderable step attribution + worked example (methodology §7.1);
  9 Nov FX check: weekend spot-date jump not captured by theta_1d x 3 (ADR-022, fix proposed).
- **M6 VaR/ES** (`risk/scenarios.py`, `risk/var.py`, `risk/backtest.py`, ADR-023/024): 500 joint
  scenarios x 71 factors, full revaluation at fixed D, VaR99/ES97.5, standalone,
  diversification, 5 worst; delta-gamma VaR; Kupiec + traffic light with the small-sample
  rule. Snapshot builder 22x faster (identical results). Real run 11 Nov: VaR99 74.1k,
  ES97.5 70.7k, dg-VaR 73.8k; 3.7 s. 204 tests, 97% coverage.

- **Process change (owner, 2026-11-13)**: commits authored by Nadir Sayed with trailer
  `Co-authored-by: Claude <noreply@anthropic.com>`. At each milestone end the owner commits
  one small contribution via github.com; wait for it, check CI, `git pull --rebase` before
  pushing.
- **M7 PDF report** (`reporting/model.py`, `charts.py`, `pdf.py`, `guard.py`, ADR-025):
  5 pages, all brief sections + vol-proxy/dividend/simplification notes; index-level guard;
  deterministic bytes; real 11 Nov render reviewed page by page (local only, not committed).
  210 tests, 98% coverage.

- **M6 review (owner, 2026-11-13)**: period theta in the explain (9 Nov FX unexplained
  -467.5 -> -55.5 and -359.3 -> -0.9 EUR); worst scenario 2 Oct investigated (ADR-026,
  kept); seeded bootstrap 90% CIs for VaR99/ES97.5 (VaR noisier: 21% vs 17% width).

- **M8 pipeline** (`pipeline.py`, `daily.py`, `fetching.py`, CLI run/backfill/daily/fetch,
  `.github/workflows/daily.yml`, ADR-027): 6 outputs per date + reports/ copy, all text
  outputs guarded; incremental fetch; catch-up schedule with ECB readiness and exit 75;
  backfill 3-11 Nov 2026 done (4.5-8 s per date). 218 tests.

- **M8 review (owner, 2026-11-13)**: 2 Oct kept; automated artefact flag (ADR-028, ECB
  all-ratings spot rates, only 2 Oct flagged on 11 Nov: VaR99 74,139 -> 70,872 without it);
  bootstrap intervals in the executive summary; reports 3-11 Nov regenerated.

- **M9 / v1.0.0 (2026-11-13, tagged early at the owner's request)**: README rewritten for readers outside the project; reports index;
  fresh-clone reproduction timed at about 2 minutes (sync 2 s, fetch 98 s, init-book 3 s,
  run 5 s), which exposed two gaps, now fixed: init-book restore of the private terms, and
  EWMA seeding at history_start (data outputs now byte-identical across clones).

## Next
- Watch the scheduled runs through December (22 TARGET days).
- v1.0.0 tagged on 2026-11-13. December runs use the tagged code; fixes go to
  [Unreleased] and a patch release if needed. The 31 Dec report arrives on 4 or 5 Jan 2027.

## Open issues (owner)
1. **Yahoo ^STOXX50E gaps** on Swiss holidays (ADR-013): forward-filled as "source gap".
   Fine for now; a better SX5E close source would remove them.
2. **Worst scenario 2 Oct 2026** (ADR-026/028): decided: kept, flagged automatically.
   README limitation (AAA curve as swap-curve proxy) to be added in M9.
