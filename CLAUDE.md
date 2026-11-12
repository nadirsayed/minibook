# CLAUDE.md: standing instructions for minibook

Read `PROGRESS.md` first: it has the resume point (done / next / open issues).
Methodology choices and their justification are in `docs/decisions.md` (ADRs).

## Working agreement
- Milestones, in order: M0 scaffold+CI, M1 data, M2 dates/curves/bootstrap, M3 pricers,
  M4 Greeks, M5 P&L explain, M6 VaR/ES, M7 PDF, M8 pipeline/CLI/schedule/backfill,
  M9 docs/polish/v1.0.0. After each one: run `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy`, `uv run pytest`; show the real output, summarize in ≤ 10 lines, commit
  (conventional commits), update PROGRESS.md and CHANGELOG.md.
- Never invent market data, numbers or test reference values. Cite the source of each one
  in a comment. Synthetic test data is labelled synthetic.
- Open methodological choice: pick the market standard, record an ADR, continue. Stop and
  ask only if scope changes. If the brief looks wrong, say so; never silently work around it.
- Network blocked (proxy 403, bot check): report it, do not circumvent.
- From scratch with numpy/scipy. QuantLib only in tests, as a like-for-like cross-check.
- Python 3.12, uv, mypy --strict on src, ruff, numpy-style docstrings stating formulas,
  `logging` never `print`, no magic numbers (they live in config), deterministic outputs.

## Approved owner decisions (2026-11-12)
1. **Schedule (ADR-001).** Run Mon–Fri on TARGET business days. The report for D is
   produced once the ECB curve for D is published (about noon CET on the next TARGET day):
   first attempt ~13:00 CET, retries until ~18:00 CET. Cron is UTC, so handle CET/CEST.
   The 31 Dec 2026 report arrives on 4 Jan 2027 without re-tagging; the v1.0.0 tag
   deadline stays 31 Dec 2026.
2. **Equity bars (ADR-003).** Never use the current session's intraday bar, and drop any
   bar dated after the valuation date D (no look-ahead).
3. **Trade date = 2026-11-02** (changed from 2026-11-30). `init-book --trade-date 2026-11-02`
   freezes the par rate, outright forwards and strikes in `config/book.yaml`.
4. **Dividend yields (ADR-005).** Use the latest official index factsheet *published on or
   before the trade date* (no look-ahead) and cite its date and URL in book.yaml. If archived
   factsheets cannot be retrieved, use the closest available one, flag the look-ahead in
   book.yaml, the README and the report, and tell the owner.

## Data rules (from the brief)
- Keep raw payloads plus normalized parquet under `data/raw/`, with fetch timestamps.
- Forward-fill at most 3 calendar days, logging observation date, age and reason; beyond
  that fail explicitly. Never fill silently.
- EURIBOR fixings: curve-implied proxy, stored immutably on the fixing date; never
  recompute past fixings from today's curve.
- Yahoo `^V2TX` does not exist (ADR-002); VSTOXX comes from the STOXX file only, with EWMA
  as fallback.
- FRED: use the Python `requests` client (curl's default user agent gets an empty reply).

## Git
- Remote: github.com/nadirsayed/minibook (default branch `main`).
