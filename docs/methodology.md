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
