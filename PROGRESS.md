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

- **External audit (2026-11-13)**, [docs/audit.md](docs/audit.md): PR #1 merged (stale
  artifact upload, 18:05 retry, reproducibility wording, two leaked closes removed);
  disclosure option A recorded in ADR-019, README and report notes.

## Unattended-operation proof (tracked separately, owner decision 23)
- Status: **PROVEN (2026-11-16 21:03 UTC).** Cron-triggered run #4 published the 13 Nov
  report unattended (45ad4f7, "chore(reports): daily risk report 2026-11-13"); #5-#7
  published 16, 17 and 18 Nov the same way. "Runs unattended" restored in the README.
- Pattern so far: exactly one scheduled run per day, created 19:25-21:03 UTC (20:25-22:03
  Berlin) although the triggers are 11:17-17:17 UTC; i.e. GitHub fires one trigger a day,
  hours late. Each run produced one date, the artifact held only the new PDF, and the
  bot commit names the valuation date. Reports therefore arrive in the evening, not in
  the 13:00-18:00 window of decision 1 (owner to decide whether that matters).
- History: cron fires, publication not yet proven (until 16 Nov). No cron-triggered run fired on
  2026-11-13 with the hourly `5 11-17` schedule (0 scheduled runs since registration at
  00:55 UTC). Schedule moved to `17,47 11-17 * * 1-5` at ~15:05 UTC (ADR-027). The first
  cron-triggered run ever (#3) came at 21:27 UTC and published nothing (window, below).
- Done when: a run with event `schedule` commits a report. Then restore "runs unattended"
  in the README.
- Hypothesis under test (owner, 2026-11-13): scheduled runs are tied to the account that
  last edited the cron line. Every earlier cron edit (4523b78, 220e4d5) was pushed from this
  Claude session; the owner re-registered it from their own account at 15:11 UTC (0474908,
  "47,17") and 15:15 UTC (34cdf32, back to "17,47"). Evidence so far: 0 scheduled runs
  through 15:25 UTC, including the 15:17 trigger after 220e4d5. First trigger after the
  re-registration: 15:47 UTC. **Result (17:31 UTC): evidence against.** Still 0 runs with
  event `schedule`: none at 15:47, 16:17, 16:47 or 17:17 UTC after the owner's 34cdf32,
  as before at 15:17 after 220e4d5. Caveat: GitHub documents that scheduled runs can be
  delayed or dropped under load, and a new schedule may take time to register, so four
  missed triggers do not exclude a slow registration.
  **Later result (owner, checked 2026-11-14): evidence for.** Daily report #3,
  [run 43510848207](https://github.com/nadirsayed/minibook/actions/runs/43510848207), was
  the first cron-triggered run ever, created 2026-11-13 21:27:27 UTC on 15e8e90, after the
  owner's re-registration (34cdf32) and after no trigger fired for the Claude-pushed cron
  edits. GitHub started it ~3.5–4 h late (likely a delayed 17:17 or 17:47 UTC
  trigger), so it fell outside the then 13:00–19:00 window and logged "outside the publishing window ... nothing to do"
  (with UTC mislabelled "local"). Fixed 2026-11-14: no upper bound, Berlin-time log label.
  One run is suggestive, not proof; GitHub's docs tie the scheduled run's actor to the last
  editor of the cron line, so the cron line is now edited only from the owner's account
  (later commits from this session leave it untouched). Next evidence: Monday 16 Nov.
  **Monday 16 Nov check (17:32 UTC): no cron-triggered run.** Total runs with event
  `schedule` is still 1 (#3, Fri 13 Nov 21:27 UTC). None of today's 13 triggers
  (11:17-17:17 UTC) has produced a run so far; the 13 Nov report is not published. Since
  #3, the only change to `daily.yml` was 583ee99 (Sat 14 Nov, pushed from this session):
  it changed comments and the commit step, not the cron line (the last commit changing
  the cron string is still the owner's 34cdf32). Two readings: (a) a push of the workflow
  file from this session's account re-registers the schedule under it, whatever line
  changes, which would fit both the zero runs after 4523b78/220e4d5 and the run after
  34cdf32; (b) GitHub delays: #3 started 3.5-4 h late, so today's runs may still arrive
  tonight (the window has no upper bound now, so a late run would publish). No manual
  dispatch without the owner.
  **Outcome:** reading (b). Run #4 came at 21:02 UTC on 16 Nov on c9476d7, i.e. after
  583ee99 (a push of the workflow file from this session that left the cron line alone),
  and published 13 Nov; #5-#7 followed daily. Reading (a) is refuted; the data fit GitHub's
  documented rule (the schedule's actor is the last editor of the cron line) plus long
  delays. The zero runs on 13 Nov daytime remain unexplained (registration latency?).
- **Manual run, 2026-11-13 17:31 UTC** (workflow_dispatch, owner-approved, NOT the
  unattended proof): [run 43473649607](https://github.com/nadirsayed/minibook/actions/runs/43473649607)
  produced 2026-11-12 (`produced: ['2026-11-12']`, 5.6 s) and the bot committed it
  (9aefdeb) with the reports index. Yahoo fetch on the runner worked (2 new bars per index).
  Artifact `reports-43473649607` holds only the new PDF (178 KB). Local reproduction:
  valuations, greeks and pnl_explain CSVs byte-identical; VaR/ES JSON equal to ~1e-13
  relative (summation order differs between CPUs).

## Next
- Monday 16 Nov: first full cron window with the fixed window check (report for Fri 13 Nov).
- 13 Nov evening: check the first scheduled Daily report runs. If the 12 Nov report was
  published unattended, tag v1.0.1 (PR #1 + disclosure note); otherwise report first.
- Watch the scheduled runs through December (22 TARGET days).
- v1.0.0 tagged on 2026-11-13. December runs use the tagged code; fixes go to
  [Unreleased] and a patch release if needed. The 31 Dec report arrives on 4 or 5 Jan 2027.

## Open issues (owner)
1. **Yahoo ^STOXX50E gaps** on Swiss holidays (ADR-013): forward-filled as "source gap".
   Fine for now; a better SX5E close source would remove them.
2. **Worst scenario 2 Oct 2026** (ADR-026/028): decided: kept, flagged automatically.
   README limitation (AAA curve as swap-curve proxy) to be added in M9.
