# Methodology

The deeper maths behind minibook. Design decisions and their justification are in
[decisions.md](decisions.md). This document grows milestone by milestone.

## 1. Market data alignment and forward-fill

A snapshot for TARGET business day D reads every series with `obs_date <= D` (no
look-ahead). For each series:

1. If an observation dated D exists, it is used.
2. Otherwise the latest earlier observation is used if it is at most 3 calendar days old.
   The fill is recorded (series, observation date, age, reason) and shown in the report's
   data-quality section.
3. A longer gap is accepted only if every weekday in it is a holiday of that series' own
   market calendar: JP for JGBs, US (Federal Reserve) for Treasuries, the exchange for each
   index (ADR-011, ADR-013). The fill is again recorded, with reason "market closed".
4. Any other gap fails the run explicitly (`StaleDataError`).

**Consequence for VaR.** Historical scenarios are day-on-day changes between consecutive
TARGET-day snapshots. When a market was closed for several days (e.g. Japanese Golden Week),
the snapshots during the closure repeat the last value: their JPY rate changes are exactly
zero. The **reopening day carries the whole multi-day move** as a single 1-day scenario.
This is the standard treatment of non-synchronous holidays in historical simulation.
It slightly understates volatility during the closure, overstates it on the reopening day,
and leaves the total move unchanged.

**Source gaps** (e.g. Yahoo's missing ^STOXX50E bars on Swiss holidays, ADR-013) are
different. The market was open but no value was recorded. They are forward-filled only
within the 3-day limit and flagged as "source gap".

## 2. Curves

See ADR-009 (representation, EUR grid), ADR-010 (USD bills), ADR-008 (JGB conventions and
the flat JPY short end) and the module docstrings of `minibook.market`.

## 3. Pricers

All PVs are in EUR at `as_of`. Times are ACT/365F from `as_of`, and DF(t) = e^{−z(t) t}.

**IRS** (payer, s = +1): PV = s · (N Σ_j L_j τ_j DF(t_j) − N K Σ_i τ_i DF(t_i)), with
fixed τ on 30/360 Bond Basis and float τ on ACT/360, over unpaid periods. L_j is the stored
fixing (past), the stored-or-proxy fixing (today), or the projected forward
(DF(s_j)/DF(e_j) − 1)/τ_j (future). Par rate K* = PV_float / annuity.
Cross-checked against QuantLib (`VanillaSwap`, par coupons, same curve nodes): PVs agree to
1e-4 EUR and the par rate to 1e-12.

**FX forward** (ADR-015): F = S · [DF_b(T)/DF_b(s)]/[DF_q(T)/DF_q(s)],
PV_q = N_b (F − K) DF_q(T), PV_EUR = PV_q / (EUR/q).

**Index options**: generalized BSM with continuous dividend yield (see
`minibook.instruments.bsm` for d1, d2, price and analytical partials), scaled by
quantity × multiplier. Checked against Hull's and Haug's worked examples, put-call parity,
central finite differences (rel 1e-4), QuantLib's analytic engine (rel 1e-12), and the
limits σ → 0 and T → 0.

## 4. Volatility proxy (EWMA) and its consequences

There is no free implied-volatility source whose terms allow automated use (ADR-002). Each
index uses a flat EWMA realized volatility, λ = 0.94:

    σ²_t = λ σ²_{t−1} + (1 − λ) r_t²   (daily),   σ_t^ann = sqrt(252 σ²_t)

with r_t the log return of day t. The vol in the snapshot for day t includes r_t.

**(a) Level: option values are likely understated versus market.** Index implied volatility
usually sits above the volatility that is subsequently realized (the variance risk premium;
e.g. Carr & Wu, "Variance Risk Premiums", *Review of Financial Studies*, 2009). Implied
volatility is also higher for low strikes (skew). A flat realized vol therefore probably
understates option values versus market, most of all for the long out-of-the-money puts
(DAX 95%, FTSE MIB 90%). It also understates the liability of the short CAC 40 call. Vega
is exact *given* the proxy, but the proxy level is not a market quote.

**(b) Dynamics: vega P&L and delta/gamma P&L are not independent.** From the recursion, the
day's vol change is a deterministic function of the day's return:

    Δσ²_t = (1 − λ)(r_t² − σ²_{t−1})   ⇒   Δσ_t ≈ (1 − λ)(252 r_t² − σ²_{t−1}) / (2 σ_{t−1})

Vol rises when |r_t| exceeds one daily standard deviation, in either direction, and decays
on quiet days.

*P&L explain.* The vega term Vega_1pt · Δσ/0.01 is, like the gamma term ½ G_1% (u/0.01)², a
function of u², the squared spot return of the same day. On large-move days a long option
shows gamma *and* vega gains. On quiet days it shows theta *and* vega losses. The split of
explained P&L between "gamma" and "vega" is therefore partly mechanical, and the two terms
must not be read as independent risk drivers. The unexplained P&L is not distorted: the
explain uses the actual Δσ that also enters the revaluation.

*VaR.* Each historical scenario applies, on the same date, the spot log return and the
absolute change of that day's EWMA vol. The vol shock is consistent with the spot shock, but
it follows a symmetric "|move| ⇒ vol up" rule. Implied vol, in contrast, typically jumps
when equities fall and eases when they rally, and its daily changes are larger than an
EWMA's (only 1 − λ = 6% weight on the new day). As a result, vega losses in sell-off
scenarios are likely understated, and rally scenarios may show vol-up gains that implied
vol would not deliver. Vega VaR should be read as a lower bound.

Both points (a) and (b) are repeated in the report footer.

## 5. Sensitivities

Definitions and units are in `minibook.instruments.base.Measure` and ADR-020. Sign
convention: every number is the EUR change in PV for an *increase* of the factor (+1% spot or
FX rate EUR/ccy, +1 vol point, +1 bp rate, +10 bp dividend yield, +1 calendar day).

## 6. Dividends: flat yield vs seasonality

The options use a constant continuous dividend yield q over their life (owner assumptions,
ADR-021). In reality, European index dividends are paid at discrete ex-dates that
concentrate in **April–May**. A flat annual q spreads the expected dividends evenly over the
year, so:

- **3M options (Nov 2026 – Feb 2027)** fall mostly *outside* the dividend season. A flat q
  charges about a quarter of a year of dividends that will largely not be paid, which
  **overstates** expected dividends (forward too low: calls undervalued, puts overvalued).
- **6M options (Nov 2026 – May 2027)** span the spring season. Most of the year's dividends
  fall inside their life, but a flat q charges only about half a year's worth, which
  **understates** expected dividends (forward too high: puts undervalued, calls overvalued).

The DAX is a total-return index (q = 0), so it is not affected. Desks instead use discrete
dividend forecasts (amount and ex-date per constituent, or index-point forecasts) or
listed **dividend futures** (e.g. on the EURO STOXX 50) to build the implied dividend
curve. This is on the roadmap. The report's `div_10bp` sensitivity shows how much each
option's value depends on the assumption.

## 7. P&L explain

    Actual      = PV_t(mkt_t) − PV_{t−1}(mkt_{t−1}) + CF(t−1, t]
    Explained   = Σ [D_1% (u/0.01) + ½ G_1% (u/0.01)²]   (equity spots, EUR/USD, EUR/JPY)
                + Σ Vega_1pt (Δσ/0.01) + Theta_period + Σ_ccy Σ_k KR_DV01_k Δr_k(bp)
    Unexplained = Actual − Explained

The Greeks are from t−1, u = ΔS/S, and Δt is in calendar days (3 over a weekend).

**Theta over the actual window (ADR-022).** The theta term is the *period theta*:

    Theta_period = PV(mkt_{t−1} rolled to t) + CF(t−1, t] − PV(mkt_{t−1})

**"Market held constant"** means, throughout minibook, constant *zero rates per tenor*
(the curve keeps its shape in time to maturity, so instruments roll down it) with spots, FX,
vols, dividend yields and fixings unchanged. Fixings due on t−1 are set first. This is the
convention of theta_1d (one day), of the period theta (the actual window), and of the
tenor-based pillar shocks in DV01, key-rate DV01 and VaR, so every measure moves the same
coordinates. Over a weekend or holiday the period theta contains effects a one-day theta
times Δt would miss, such as the jump of an FX forward's spot value date (on 9 Nov 2026 this
removed ~0.8k EUR of unexplained P&L from the two FX forwards). theta_1d is still reported
as the per-day sensitivity.

**What remains unexplained, and why.** Third-order spot terms (cubic in u). The cross and
convexity terms the formula omits: vanna (spot × vol), volga (vol²), charm (spot × time),
rate convexity, and spot-date jumps of FX forwards over holidays. With the EWMA proxy the
vol change is itself driven by u² (§4), so vanna and volga are *systematically* large on
big-move days. The report therefore shows, next to each instrument's unexplained P&L, the
vanna + volga estimate and the remainder. For each breach of
max(5% |Actual|, EUR 1,000) it adds a note and the full-revaluation step attribution
(time → rates → FX → spots → vols → other).

First real-data run (3–11 Nov 2026, live cache, owner dividend assumptions): book
unexplained between −5.4k and +0.9k EUR, against daily actual P&L of 12k–58k EUR. Option
breaches on 4, 6 and 9 Nov (five instrument-days): the vanna + volga estimate is 90–115% of
each breaching option's unexplained P&L, leaving remainders of 101–289 EUR.

### 7.1 Step attribution is order-dependent

The revaluation steps move one block of inputs at a time, so each step is valued at
partly-moved inputs. The steps always add up to Actual, but **the split between steps
depends on the order**, because cross effects (here spot × vol: vanna) go to whichever step
comes second. Worked example, Fri 6 → Mon 9 Nov 2026 (live data), equity and vol steps of
each option in the two orders (EUR):

| Option | Moves (spot, vol) | Equity, spot first | Vol, spot first | Vol, vol first | Equity, vol first |
|---|---|---|---|---|---|
| SX5E 100% call | +1.94%, +1.39 pts | +33,556 | +8,048 | +8,217 | +33,388 |
| DAX 95% put | +1.73%, +0.85 pts | −11,584 | +4,805 | +5,187 | −11,966 |
| CAC 40 105% call (short) | +1.16%, +0.34 pts | −8,971 | −1,482 | −1,351 | −9,102 |
| FTSE MIB 90% put | +2.69%, +2.34 pts | −20,928 | +18,741 | +22,151 | −24,338 |

The sum of the two steps is identical in both orders (e.g. −2,187 for the FTSE MIB put), but
3,410 EUR moves from the spot step to the vol step when the order is swapped. minibook uses
the fixed order time → rates → FX → spots → vols → other and labels it as such.

**Alternative (roadmap):** a symmetric, Shapley-style attribution averages each block's
marginal contribution over all orders (5! = 120 for five blocks, or a sampled subset). It is
order-independent and splits cross effects evenly, at the cost of many more revaluations.

## 8. VaR and ES

Historical simulation, full revaluation, 1-day horizon, 500 joint scenarios (ADR-023):

    P&L_i  = Σ_instruments [PV(apply(mkt_D, shock_i)) − PV(mkt_D)]          (valuation date D)
    VaR_99 = −P_(5),   ES_97.5 = −mean(P_(1..13))                           (N = 500)

Standalone VaR/ES use the same scenarios per instrument. Diversification =
Σ standalone VaR − VaR (may be negative). The five worst scenarios are reported with their
dates and per-instrument P&L. Index moves are shown as % returns only (ADR-019).

First real run (D = 11 Nov 2026, scenarios 26 Nov 2024 – 11 Nov 2026, owner dividend
assumptions): VaR99 = EUR 74,139, ES97.5 = EUR 70,730, Σ standalone VaR = EUR 229,244,
diversification = EUR 155,105. Delta-gamma VaR = EUR 73,782 (0.5% below full revaluation).
The worst scenario is 2 Oct 2026 (−83,321, mostly the payer swap).

**Sampling noise: VaR is noisier than ES.** VaR99 rests on a single order statistic, the
5th worst of 500 P&Ls, so it can jump when one scenario enters or leaves the window. ES97.5
averages the worst 13. The report gives seeded, deterministic bootstrap intervals (2,000
resamples of the 500 scenario P&Ls, seed in `config/settings.yaml`, 90% two-sided). On
11 Nov 2026: VaR99 74,139 (90% CI 64,476 – 80,003, width 21% of the level) vs ES97.5
70,730 (63,887 – 75,729, width 17%). The i.i.d. bootstrap of an extreme quantile is crude
(bootstrap VaRs can only take sample values), so these intervals indicate noise rather
than exact coverage.

**Scenario check: 2 Oct 2026 (worst scenario, investigated, not altered).** See ADR-026.
The EUR AAA curve fell 11.5/13.6/12.8 bp (2Y/5Y/10Y) on that day, against 2.0/3.6/7.7 bp for
the ECB all-ratings curve. Over 1 → 5 Oct both curves fell by similar amounts, so the rally
is real, but the AAA curve concentrated it on 2 Oct, with a 4.7σ jump in its Svensson
BETA3. Most of the AAA vs all-ratings divergence reversed on 5–6 Oct.

Backtesting (exceptions, Kupiec POF, Basel traffic light) follows ADR-024: with fewer than
250 observations the report states "insufficient observations (N = x)".
