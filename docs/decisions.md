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

Owner question (2026-11-12): do the terms allow *personal, non-commercial* use? No.
§3.1 allows viewing on screen "for your own internal information and reference purposes
only, and on a non-commercial basis", and in the same paragraph forbids downloading,
saving, copying and creating any "model" from the data. §3.5 forbids automated access
"regardless of your purpose, including research". §3.6 forbids inputting the data into
any AI system. A daily automated download, stored locally and processed by this pipeline,
breaks all three even for personal use.

**Decision.** minibook does not download or store any STOXX website data. The copies
fetched during the 2026-11-12 probe, before the terms were read, were deleted. Nothing from
stoxx.com was ever committed. The vol proxy is therefore the brief's fallback, EWMA realized vol (λ = 0.94) per index,
labelled as a proxy. The owner's preferred VSTOXX-scaled proxy is not possible under these
terms.

**Status.** Decided 2026-11-12: EWMA is the vol proxy (owner made VSTOXX conditional on
the terms allowing personal use, and they do not).

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

**Status.** Approved by owner 2026-11-12 and **on by default**. The calendar is the
source's own: JP for JGBs, US for Treasuries, each index's exchange (ADR-013). Every such
fill is logged and shown in the report's data-quality section. In the VaR history, the
reopening day carries the whole multi-day move (docs/methodology.md). Any other gap longer
than 3 days still fails.

## ADR-012: FRED is one business day late for the D+1 run

**Evidence.** At 13:20 UTC on 2026-11-12, FRED's latest DGS observation was 2026-11-09,
while the U.S. Treasury par-yield CSV already had 2026-11-10 (the values for 2026-11-09
match). FRED republishes the Fed's H.15 release, which comes out the business day after the
observation. At the ~13:00 CET D+1 run, the USD curve for D would therefore usually come
from D-1 (a 1-day forward-fill on almost every report).

**Proposal.** Fetch the Treasury "Daily Treasury Par Yield Curve Rates" CSV (original source,
U.S. government work) as the primary USD source, and keep FRED as a cross-check.

**Status.** Approved by owner 2026-11-12. Treasury is primary
(`minibook.data.treasury`), with tenors 1M, 2M, 3M, 4M, 6M (bills) and 1Y–10Y. FRED is a
cross-check: |Treasury − FRED| > 1 bp on the same date raises a `FRED_CROSSCHECK` quality
flag. A missing FRED value is normal, given the lag. Over 2023-06-01..2026-11-09 the two
agree exactly on all 860 shared dates.

## ADR-013: Exchange calendars for equity indices; Yahoo SX5E gaps

**Decision.** Each index uses its exchange calendar, for forward-fill reasons and for the
closure exemption:
- Euronext Paris (CAC 40): 1 Jan, Good Friday, Easter Monday, 1 May, 25–26 Dec.
- Xetra (DAX) and Eurex (EURO STOXX 50): the above plus 24 and 31 Dec.
- Borsa Italiana (FTSE MIB): the Xetra set plus 15 Aug.

**Evidence.** These rules reproduce exactly the weekdays with and without a Yahoo close
for CAC 40, DAX and FTSE MIB over 2023-01-02..2026-11-11 (checked 2026-11-12; the data is
not committed). QuantLib agrees for Eurex and Borsa Italiana. It differs in two places,
where the data contradicts it: France.Exchange closes 24/31 Dec, but CAC closes exist on
those days (early close); Germany.Xetra keeps 31 Dec open, but there was no DAX close in
2024 or 2025. The tests pin these documented differences.

**Data-quality finding.** Yahoo's `^STOXX50E` history has no bar on 15 Eurex trading days
in that window, all Swiss holidays: 2 Jan, Ascension, Whit Monday, 1 Aug. DAX and CAC
closes exist on those days, so the index was calculated. This is a feed artifact, not a
closure. Those days are forward-filled (≤ 3 days) with the reason "source gap", flagged in
the report, and never covered by the closure exemption.

## ADR-014: Yahoo data stays local; dividend placeholder

**Decision (owner, 2026-11-12).** yfinance is used for personal, non-commercial purposes.
Yahoo and STOXX data is never committed: it lives only in the git-ignored `data/raw/`
cache. Tests use labelled synthetic equity closes. Committed fixtures are ECB, U.S.
Treasury, FRED (H.15, public domain) and MoF data only, all redistributable with
attribution. Until the owner provides the dividend yields, a clearly marked placeholder
exists in tests only. A report can never use it: the option pricer fails without a real
dividend yield in book.yaml.

## ADR-015: FX forwards are discounted from the spot date

**Context.** The brief writes F = S · DF_base(T) / DF_quote(T), which treats S as a rate for
value today. ECB reference rates are spot rates (value T+2), and the brief also asks for
pair-specific spot lags and settlement calendars.

**Decision.** F = S · [DF_base(T)/DF_base(s)] / [DF_quote(T)/DF_quote(s)], where s is the
pair's spot date seen from the valuation date (market standard). Spot rules: the lag is
counted on the non-USD calendar(s), then the date rolls to a day that is good in every
settlement calendar (EURUSD: TARGET+US, USDJPY: JP+US). Delivery is spot + tenor, modified
following, with the end-of-month rule. Inception PV is 0 either way. The difference from the
brief's formula is about (r_base − r_quote) × 2/365 in F.

## ADR-016: EURIBOR fixing proxy and its immutable store

**Decision.** The fixing proxy for a coupon is the ACT/360 simple forward over the coupon's
accrual period from the EUR curve of the *fixing date*. On that date it equals the
projected rate, so PV is continuous. It is recorded once in
`data/fixings/EURIBOR6M_proxy.csv` (append-only; committed, being derived from ECB data). A
different value for an existing date raises `FixingConflictError`. Pricing a coupon whose
fixing date is in the past without a stored fixing raises. Past fixings are never
recomputed from a later curve. The trade-date fixing (2026-11-02) is recorded by
`init-book`; later ones by the daily run (M8).

## ADR-017: Option conventions

**Decision.**
- Expiry = trade date + tenor, modified following on the exchange calendar (ADR-013).
- T = ACT/365F from the valuation date. r = EUR zero rate z(T) from the AAA government curve
  (single curve, documented simplification).
- Cash settlement at expiry, using the index close as the settlement level. Listed contracts
  use an exchange settlement price instead (simplification).
- Strikes = strike_pct × index close on the trade date, at full float precision.
- A missing dividend yield is a pricing error: no option PV without an owner-provided q.

## ADR-018: Option trade terms live in a git-ignored private file

**Context.** init-book derives option strikes from Yahoo index closes on the trade date
(`spot_at_trade`; for the 100% SX5E call the strike *is* the close). The owner's rule is that
raw Yahoo data is never committed (ADR-014). A push of book.yaml containing them was blocked.

**Decision.** init-book writes option frozen terms to `config/book.private.yaml`
(git-ignored). `load_book` merges them, and refuses option terms found in the public
book.yaml. Swap and FX frozen terms, derived from ECB and Treasury data, stay in book.yaml.
To reproduce, run `minibook fetch` and then `minibook init-book --trade-date 2026-11-02`: the
same strikes are rebuilt deterministically from the same closes.

**Status.** Confirmed by owner 2026-11-12.

**Scheduled runs.** GitHub Actions gets the file from the encrypted secret
`BOOK_PRIVATE_YAML_B64`: the base64 of `config/book.private.yaml`, decoded to disk before
`minibook run` (M8 workflow). book.yaml's `frozen_metadata.private_terms_sha256` (a SHA-256
of the option terms, which reveals nothing about them) makes a wrong or corrupted secret
fail loudly instead of pricing other strikes. People who clone the repo reproduce the file
with `minibook fetch` + `minibook init-book`.

## ADR-019: Owner assumptions; no index levels in anything committed

**Dividend yields (owner, 2026-11-12).** SX5E, CAC 40 and FTSE MIB yields are *documented
model assumptions* provided by the owner, not sourced data (the STOXX terms cover their
factsheets too). They live in book.yaml under `assumptions.dividend_yields`, each with
`value`, `source` and `date`. The report shows each option's sensitivity to q (EUR per +10bp,
`div_10bp`), so the effect of the assumption is visible. ADR-005 (factsheet rule) is
superseded.

**Committed outputs (owner, 2026-11-12).** The rule of ADR-014/018 applies to everything
committed, including PDF reports and CSV outputs. Option strikes are shown as % of the
trade-date spot. Index moves are shown as % returns, never as index levels or level history.
PVs, Greeks, P&L and VaR (EUR amounts) are fine. M7/M8 add an automated check that no index
level appears in committed outputs.

## ADR-020: Greek conventions

- Analytical where available (options: delta, gamma, vega, dV/dq; FX forwards: delta and
  gamma on EUR/USD and EUR/JPY including the EUR translation), each checked against central
  finite differences (rel 1e-4).
- DV01 and key-rate DV01: **central differences** [PV(+1 bp) − PV(−1 bp)] / 2, reported per
  +1 bp, per currency (owner, after M5: the brief's one-sided difference carried an
  O(1 bp) convexity bias). FX forwards carry risk in both of their currencies. Key-rate tents
  add up to the parallel shift; with central differences the sum matches the parallel DV01
  to O(bp²) (tested at 1e-6 relative).
- Theta: PV(t + 1 calendar day) + cashflows in (t, t + 1] − PV(t), "market held constant":
  curves fixed as functions of time to maturity, spots/FX/vols/fixings unchanged. Fixings
  due today are set first (curve proxy). Consequence: FX forward theta includes the jump of
  the spot value date over weekends and holidays (S is held constant while its value date
  moves), so it is larger before weekends. Actual P&L contains the same effect.
- The option sensitivity to q is reported as 0.001 · V_q (first order, EUR per +10 bp).

## ADR-021: Dividend-yield assumptions (owner, 2026-11-12)

**Decision.** Continuous annual dividend yields for the trade date 2026-11-02, provided by the
owner as model assumptions and stored in `assumptions.dividend_yields`:

| Index | q | Basis (owner) |
|---|---|---|
| SX5E | 2.6% | iShares Core EURO STOXX 50 UCITS ETF Dist (IE0008471009) trailing distribution yield 2.47-2.60% across data providers; 2026 distributions ~2.83% |
| CAC 40 | 3.0% | Amundi CAC 40 UCITS ETF Dist (FR0007052782) trailing ~2.72% (EUR 2.32 paid Dec 2025) before its 0.25% TER; press: Paris market yield 3.3-3.7% |
| FTSE MIB | 3.9% | 2026 consensus index dividend yield (Milano Finanza, July 2026); Amundi FTSE MIB ETF trailing 3.70% (Apr 2026) |
| DAX | 0% | Total-return index (methodology) |

**Look-ahead (flagged).** The sources were consulted on 2026-11-12, ten days after the trade
date. Each entry carries `look_ahead: true`, and the report shows the flag. The effect is
small (trailing yields move slowly), but it is not strictly point-in-time.

**Model limitation.** A flat annual q ignores dividend seasonality; see methodology §6.
Each option's sensitivity to q (EUR per +10 bp) is reported, so the assumption's weight is
visible.

## ADR-022: P&L explain conventions and breach diagnostics

- Actual = PV_t(mkt_t) − PV_{t−1}(mkt_{t−1}) + cashflows in (t−1, t] (brief). Fixings due on
  t−1 are set on mkt_{t−1} first (curve proxy), as the daily run records them.
- Explained uses the t−1 Greeks exactly as in the brief. Rate moves are zero-rate changes at
  the key-pillar times, on a time-to-maturity grid (consistent with "market held constant"
  theta). The parallel DV01 is not used (the key rates span it), and q is held constant.
- Unexplained is additive per instrument; the factor table splits only the explained part.
- **Diagnostics, not part of Explained:** for options, `omitted_2nd_order` = vanna ΔS Δσ +
  ½ volga Δσ² from t−1 (analytic BSM). On real data (Nov 2026), the vanna + volga estimate
  was 90–115% of each breaching option's unexplained P&L (remainders 101–289 EUR). This is expected with the EWMA proxy, whose vol jumps on
  big spot days (methodology §4). Each flagged row gets a plain-words `note`.
- **Step attribution (bonus):** full revaluation, moving time (with cashflows), rates, FX,
  spots, vols, then other, in that order. It adds up exactly to Actual (checked at 1e-6 EUR)
  and depends on the order.
- Convergence (tests): a pure spot move leaves a cubic residual; a joint spot+vol move a
  quadratic one (omitted cross terms), and the diagnostic leaves < 1% of it. A parallel
  rate move leaves ½ PV'' Δ², cleanly quadratic from 0.5 bp to 8 bp, since DV01 became a
  central difference. (With the original one-sided DV01 it was ½ PV'' Δ (Δ − 1 bp), which
  vanishes at exactly 1 bp.)
- Step attribution is order-dependent (methodology §7.1, worked example on 9 Nov 2026).
- **Known gap: theta × Δt over weekends/holidays (owner decision pending).** theta_1d is a
  one-day roll from t−1. On a Friday, the roll to Saturday keeps the same FX spot value date,
  so theta_1d × 3 misses the jump of the spot value date over the weekend (and over US/JP
  holidays), which actual P&L contains. On Mon 9 Nov 2026 this was −412 EUR (EUR/USD 6M,
  unexplained −468) and −358 EUR (USD/JPY 3M, unexplained −359), with the spot date jumping
  from Tue 10 to Thu 12 Nov over the US holiday of 11 Nov. Proposed fix: in the explain,
  replace theta_1d × Δt with the period theta PV(t−1 rolled to t) + CF − PV(t−1), the
  revaluation "time" step, while still reporting theta_1d per day.
