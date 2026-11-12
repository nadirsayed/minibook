# Architecture / methodology decisions (ADR log)

Each entry: context, decision, consequences. Newest last.

## ADR-001: Report for D runs on the next TARGET business day, Mon–Fri

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

## ADR-002: VSTOXX source: official STOXX file only, no Yahoo fallback

**Context.** Yahoo `^V2TX` returns "Quote not found" (probe of 2026-11-12), so it cannot be
verified as a fallback.

**Decision.** Use STOXX `h_v2tx.txt` as the primary source. If it fails, fall back to the
brief's EWMA (λ = 0.94) realized-vol proxy, flagged in the report. Do not use Yahoo for VSTOXX.

## ADR-003: Exclude the current day's partial bar from equity data

**Context.** yfinance returns an intraday bar for the current session (the probe at
13:45 CET on 2026-11-12 returned a 2026-11-12 close).

**Decision.** Only accept an equity close for D once D's session is over: the fetch
timestamp must be after the exchange close in Europe/Berlin or Europe/Rome time, or D must
be earlier than the fetch date. The fetch timestamp is stored with every observation.
