# External audit (2026-11-13)

An independent review of minibook at v1.0.0 (`ca556d1`), carried out at the owner's
request. Verdict: **needs fixes**. This file records what was checked, what was found,
what was fixed and what was decided.

## What the audit checked

- **Software.** In a fresh clone, locked dependencies installed; live data fetched; private
  option terms restored from the committed digest; the 11 Nov 2026 report generated. The
  offline suite passed locally (230 tests), ruff and strict mypy passed, and
  [CI on main](https://github.com/nadirsayed/minibook/actions/runs/43405296876) reported the
  same 230 passes and 97% coverage.
- **Reproducibility.** Rerunning 11 Nov reproduced the numeric CSV files and the VaR/ES JSON;
  run metadata and PDF bytes differed with run details (fetch and run timestamps).
- **Financial calculations, within the documented model.** Across the seven reports
  (3–11 Nov), P&L reconciled to valuations and cashflows within EUR 0.01 of CSV rounding.
  Sorting the 500 full-revaluation scenario P&Ls independently recovered the published
  11 Nov VaR99 (EUR 74,138.65) and ES97.5 (EUR 70,730.46) exactly. The tests include
  QuantLib cross-checks, finite-difference Greeks, P&L identities and known-rank VaR/ES
  cases. These validate the implementation of the documented model, not market-quoted
  prices: the swap curve, volatility, fixings and some dividend inputs are documented
  proxies, and backtesting has only six observations.
- **Security, limited scope.** No exposed credential in the reviewed configuration or
  workflows. No dependency vulnerability scan was run.

## Findings

| # | Finding | Status |
|---|---|---|
| 1 | The only Daily report run so far was manual. It finished green but logged `produced: nothing` (ECB curve for 12 Nov not yet published) and still uploaded the seven older PDFs as an artifact. | Fixed in PR #1: only PDFs created or changed by the run are uploaded. |
| 2 | The hourly triggers end at 18:05 Europe/Berlin, but the local window closed at 18:00, so the last retry never ran in either season. | Fixed in PR #1: window end 18:15, with schedule tests for CET and CEST. |
| 3 | The README said the data outputs reproduce byte for byte; `run_metadata.json` and the PDFs do not. | Fixed in PR #1: the README states exactly which outputs reproduce. |
| 4 | Two real index closes appeared as examples in committed documentation (`docs/decisions.md`, `reporting/guard.py` docstring). | Removed from the current files in PR #1. They remain in git history, which is never rewritten (CLAUDE.md 18). |
| 5 | **Disclosure.** No index level is printed in the seven PDFs, but all four 11 Nov closes were reconstructed to the displayed precision from the published option outputs (PV, strike as % of spot, vol, dividend yield, rates). Keeping raw closes and private terms out of git does not prevent their disclosure. | Owner decision, option A (below). |
| 6 | Unattended daily publication not yet demonstrated: no scheduled run had happened at audit time. | To be verified on the first scheduled runs (13 Nov 2026). |
| 7 | An earlier CI failure (finite-difference volga test). | Already fixed before the audit: the case is pinned and the test passes. |

Later the same day (owner decision), the schedule moved off the top of the hour to two
triggers an hour (:17 and :47); the in-job window became 13:00–19:00 Berlin, admitting the
last trigger (18:47) in both seasons (ADR-027). This supersedes the 18:15 window of
finding 2.

PR #1 ([nadirsayed/minibook#1](https://github.com/nadirsayed/minibook/pull/1)) passed
[push CI](https://github.com/nadirsayed/minibook/actions/runs/43409990079) and
[PR CI](https://github.com/nadirsayed/minibook/actions/runs/43410059044) and was merged on
2026-11-13.

## Disclosure decision (owner, 2026-11-13)

**Option A: accept and disclose.** The option outputs stay in the reports. ADR-019, the
README limitations and a note printed in every report state that index levels are not
published here but can be recovered from the published option outputs.

- ADR-019 exists to avoid redistributing Yahoo/STOXX data files, which minibook still
  does not do. Index closes are public facts, published daily by the index providers and
  the press.
- Keeping the option detail private (option C) would not undo the disclosure: the
  3–11 Nov reports with option detail and the two leaked closes are already in git history,
  which is never rewritten.
- The index-level guard stays, because it still prevents direct publication of a level.

## Independent follow-up check

After the audit, every committed text file and the text of every committed PDF were
scanned against all 3,879 cached index closes (one or two decimals, with and without
thousands separators). The only decimal matches were the two closes of finding 4, plus
one coincidence: the swap's explained P&L on 6 Nov 2026 (EUR −6,210.17) equals an SX5E
close of 23 Jul 2026, outside any report window. Whole-number matches are coincidental,
because with that many closes almost any 4- or 5-digit amount matches one.
