# Architecture / methodology decisions (ADR log)

Each entry: context, decision, consequences. Newest last.

## ADR-001: Report for D runs on the next TARGET business day, Mon–Fri

**Status.** Approved by owner 2026-11-12.

**Context.** The brief schedules runs Tuesday–Saturday. The ECB publishes the Svensson
curve for day D at around noon CET on the *next TARGET business day*, not on Saturday.
Evidence from `updatedAfter` queries on 2026-11-12: the observation dated Fri 2026-11-06 was
last updated on Mon 2026-11-09 between 11:00 and 14:00 CET. Under a Tue–Sat schedule the
Saturday run would never find Friday's curve, and Friday's report would slip to Tuesday.

**Decision.** Run Monday–Friday around 13:00 CET with retries until about 18:00 CET.
Each run targets the latest TARGET business day before today whose ECB curve is available.
Non-TARGET days exit cleanly. Example: the 31 Dec 2026 curve is expected on Mon 4 Jan 2027,
because 1 Jan is a TARGET holiday.

**Consequences.** Cron runs in UTC at both the CET and CEST offsets, and the job checks the
Europe/Berlin local time itself.

## ADR-002: No STOXX data (VSTOXX file, SX5E factsheet): pending owner decision

**Context.** The brief makes the STOXX file `h_v2tx.txt` the primary VSTOXX source and asks
for its usage terms to be documented. The STOXX Conditions of Use
(https://stoxx.com/legal/stoxx-conditions-of-use/, read 2026-11-12) say:
- §3.1/§3.2: without a licence agreement, all data on the website, including freely
  available data, is *view-only*. Users must not "download, save, print, copy or redistribute
  the Data", nor use it "in connection with the ... valuation of any financial instrument".
- §3.5: no "crawler, robot, spider, scraper, bot ... or similar automated means", whatever
  the purpose (research included).
- §3.6: the data must not be input into any AI system.

Yahoo `^V2TX` returns "Quote not found" (probe of 2026-11-12), so it is not an alternative.

**Decision.** minibook does not download or store any STOXX website data. The copies
fetched during the 2026-11-12 probe, before the terms were read, were deleted. Nothing from
stoxx.com was ever committed. Vol proxy until the owner decides: the brief's fallback, EWMA
realized vol (λ = 0.94) per index, labelled as a proxy.

**Status.** Pending owner decision.

## ADR-003: Exclude the current day's partial bar from equity data

**Context.** yfinance returns an intraday bar for the current session (the probe at
13:45 CET on 2026-11-12 returned a 2026-11-12 close).

**Decision.** Only accept an equity close for D once D's session is over: the fetch
timestamp must be after the exchange close in Europe/Berlin or Europe/Rome time, or D must
be earlier than the fetch date. Any bar dated after the valuation date D is also dropped
(owner decision 2026-11-12), so a backfill run can never see future closes. The fetch
timestamp is stored with every observation.

**Status.** Approved by owner 2026-11-12.

## ADR-004: Trade date 2026-11-02

**Context.** The original trade date (2026-11-30) was after the date the project started,
and its dividend factsheets could not exist until December.

**Decision.** Owner moved the trade date to Mon 2026-11-02. It is a TARGET, US and Japanese
business day (3 Nov is a Japanese holiday, which does not affect the trade date itself).

## ADR-005: Dividend yields without look-ahead

**Decision.** For SX5E, CAC 40 and FTSE MIB, use the trailing dividend yield from the latest
official factsheet *published on or before* the trade date. Cite the factsheet date and URL
in book.yaml. If no archived factsheet can be retrieved, use the closest available one and
mark it `look_ahead: true` in book.yaml, the README and the report.

## ADR-006: Raw market-data cache is not committed

**Context.** The brief keeps raw payloads and parquet under `data/raw/`. Committing them
would redistribute third-party data. ECB (ESCB reuse policy), MoF (Public Data License 1.0)
and FRED's H.15 series (public domain, citation requested) allow that, but Yahoo / index
levels may not.

**Decision.** `data/raw/` is git-ignored and rebuilt with `minibook fetch`. Offline tests use
verbatim recordings of the openly licensed sources only (`tests/fixtures/http/`). Equity
tests use labelled synthetic bars. Revisit in M8 for the "reproduce in 5 minutes" goal.

## ADR-007: Days on which the ECB publishes no yield curve

**Context.** The ECB publishes FX reference rates on every TARGET day but sometimes no yield
curve. Over 2015–2025 the 24 Dec and 31 Dec curves were often missing: 31 Dec was
published only in 2021 and 2025. Inside the VaR window, 2024-12-31 has FX but no curve.
So the 24 Dec and 31 Dec 2026 reports will likely have no curve for D.

**Decision.** Market standard: use the last published curve, under the brief's
forward-fill rule (≤ 3 calendar days, observation date, age and reason logged in
`run_metadata.json` and shown in the report). A missing curve for D is only known for sure
once the ECB has published a *later* date. The scheduled run therefore waits for the D+1
curve before forward-filling D: if 31 Dec 2026 is not published, its report comes out with
the 4 Jan 2027 curve on 5 Jan 2027. History gaps such as 2024-12-31 are forward-filled the
same way.

**Status.** Proposed; owner to confirm the 5 Jan timing.

## ADR-008: MoF JGB yields are semi-annual compounded constant-maturity yields

**Source.** MoF FAQ (https://www.mof.go.jp/faq/jgbs/04hc.htm, 04hb.htm, 04he.htm): each
issue's yield is a semi-annually compounded yield from JSDA reference prices. A curve is
fitted through the issue yields and read at exact maturities. Publication is around 09:30
JST on the next business day (04hf.htm).

**Decision (for M2).** Treat each tenor as the par yield of a semi-annual-coupon bond at
that maturity, and bootstrap to continuous zero rates. This is an approximation: a
constant-maturity yield read off a curve of issue yields is not exactly a par yield.
Documented as a limitation.

**Short end.** MoF publishes nothing below 1Y. JPY zero rates below 1Y are flat-extrapolated
from the 1Y zero, and the 3M/6M key pillars are inserted at that flat value. This mainly
affects the 3M USD/JPY forward. Limitation: no JPY money-market data. The fallback in the
brief (BoJ policy rate) covers only an MoF outage, not this gap.

## ADR-009: Curve representation and the EUR pillar grid

**Decision.**
- Every curve is a `ZeroCurve`: continuously compounded zero rates on pillars, DF = e^{-z t},
  linear in z between pillars, flat outside. Linear-in-zero is the brief's choice. It is
  simple, local (a pillar shock moves the curve only between its neighbours) and
  bump-friendly. Its known weakness is saw-tooth forwards.
- Time t is ACT/365F from the valuation date; pillar times are nominal (3M = 0.25). The
  ECB Svensson maturity m is set to t.
- The key-rate pillars (3M, 6M, 1Y, 2Y, 3Y, 5Y, 7Y, 10Y) are inserted into every curve. A
  key-rate shift is then a tent in t with knots on pillars, so the shifted curve equals
  z(t) + tent(t) everywhere, and the key-rate tents add up exactly to a parallel shift.
- EUR is sampled from Svensson on 38 pillars: monthly to 1Y, quarterly to 3Y, semi-annual
  to 10Y, then 12/15/20/30Y. The coarser grids tested had larger worst-case errors
  (measured 2026-11-12 over the 881 curves of 2023-06-01..2026-11-11, t in [1M, 10.5Y]):
  8 key pillars 40.6 bp; 19 pillars 2.7 bp; 32 pillars quarterly to 3Y 2.5 bp (short-end
  hump on 2023-09-01). Chosen grid: **0.54 bp**. These pillars are also the EUR VaR risk
  factors.

## ADR-010: USD Treasury bills (1M, 3M, 6M) in the bootstrap

**Context.** Treasury CMT yields are bond-equivalent yields. Bills pay no coupon.

**Decision.** 1M, 3M and 6M are simple yields: DF(T) = 1/(1 + yT), T = 1/12, 0.25, 0.5. From
1Y on, each quote is the par yield of a semi-annual coupon bond on a regular 0.5-year grid.
The 52-week bill is treated as a 1Y par bond. Simplification: nominal times, no actual
bill day counts or settlement dates.

## ADR-011: Market-closure exemption to the 3-day forward-fill limit

**Context.** On the live cache, a strict 3-day rule fails on 9 TARGET business days of the
VaR window. All of them are JGB data during official Japanese market closures: 2024-01-02/03,
2024-05-06, 2025-01-03, 2025-05-06, 2026-05-05/06, 2026-09-22/23. Ages are 4–5 days. With a
strict rule those snapshots cannot be built, which breaks the 500-day joint history.

**Proposal.** `market.market_closure_exempt: true` allows an older observation only when
*every* weekday since it is a holiday of that source's own market calendar. When the market
is closed, its last close is the current value. The fill is still logged with age and
reason. With the exemption, 0 stale days remain in 2023-06..2026-11. Any other gap, such as
a failed publication, still fails explicitly.

**Status.** Implemented, but **off by default** (brief rule). Owner decision needed before
M6 (VaR).

## ADR-012: FRED is one business day late for the D+1 run

**Evidence.** At 13:20 UTC on 2026-11-12, FRED's latest DGS observation was 2026-11-09,
while the U.S. Treasury par-yield CSV already had 2026-11-10 (the values for 2026-11-09
match). FRED republishes the Fed's H.15 release, which comes out the business day after the
observation. At the ~13:00 CET D+1 run, the USD curve for D would therefore usually come
from D-1 (a 1-day forward-fill on almost every report).

**Proposal.** Fetch the Treasury "Daily Treasury Par Yield Curve Rates" CSV (original source,
U.S. government work) as the primary USD source, and keep FRED as a cross-check.

**Status.** Owner decision needed (the brief names FRED).
