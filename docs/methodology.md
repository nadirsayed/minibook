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
