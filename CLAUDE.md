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

5. **Forward-fill closure exemption ON (ADR-011).** A gap longer than 3 calendar days is
   allowed only if every weekday in it is a holiday of that market's own calendar (JP for
   JGBs, US for Treasuries, each exchange for its index, ADR-013). It is logged and shown in
   the report's data-quality section. Any other gap > 3 days fails.
6. **USD source (ADR-012).** U.S. Treasury daily par yield curve is primary. FRED is a
   cross-check only: flag |diff| > 1 bp.
7. **Yahoo (ADR-014).** yfinance approved for personal, non-commercial use. Raw Yahoo or
   STOXX data never enters the repo (local git-ignored cache only). Tests use labelled
   synthetic equity closes.
8. **Vol proxy (ADR-002).** EWMA (λ = 0.94). The VSTOXX-scaled proxy is not used: the STOXX
   terms forbid download, automated access and AI use, even for personal use.
9. **JPY below 1Y** is flat (documented limitation; short-end anchor on the roadmap).
10. **31 Dec 2026 report** published on 5 Jan 2027 if the ECB skips 31 Dec (ADR-007): OK.
11. **Dividend yields** are owner-provided model assumptions in book.yaml
    `assumptions.dividend_yields` (value, source, date; ADR-019). Never source SX5E (or any
    index) yields from stoxx.com. Until provided, a clearly marked placeholder in tests only,
    never in a report. The report shows each option's q sensitivity (EUR per +10bp).

## Approved owner decisions (2026-11-12, round 3)
12. **Option A confirmed (ADR-018).** The scheduled workflow restores
    `config/book.private.yaml` from the GitHub secret `BOOK_PRIVATE_YAML_B64` (base64)
    before running; `frozen_metadata.private_terms_sha256` verifies it.
13. **No index levels in anything committed (ADR-019)**, including PDF reports and CSV
    outputs: strikes as % of trade-date spot, index moves as % returns. PVs, Greeks, P&L and
    VaR are fine.
14. **Vol proxy EWMA confirmed.** methodology.md §4 and the report footer must state that
    (a) realized vol usually sits below implied, so option values are likely understated vs
    market, and (b) EWMA vol changes are driven by the day's squared return, so vega and
    delta/gamma P&L are not independent (effects on the explain and on the VaR vol shocks).

## Approved owner decisions (round 4, after M5)
15. **DV01 and key-rate DV01 are central differences** [PV(+1bp) − PV(−1bp)] / 2 (ADR-020).
16. **Backtesting with N < 250**: show "insufficient observations (N = x)", never a zone or a
    misleading green (ADR-024).
17. Step attribution is order-dependent: always state the order; Shapley on the roadmap.

## Approved owner decisions (round 5, after M6/M7)
18. **Commits**: author Nadir Sayed (`git config user.*` set in the repo), committer Claude so
    GitHub verifies the signature: `GIT_COMMITTER_NAME=Claude
    GIT_COMMITTER_EMAIL=noreply@anthropic.com git commit ...` (also for `git pull --rebase`).
    Every message ends with `Co-authored-by: Claude <noreply@anthropic.com>`. Never rewrite
    past commits.
19. **Owner contributions**: at each milestone end, give the owner one small self-contained
    contribution (path, create/edit, exact content ending with a newline, commit message,
    step-by-step github.com clicks). Wait for confirmation, check CI, `git pull --rebase`
    before the next push.
20. **Period theta in the explain** (ADR-022): one-step revaluation t-1 -> t with the market
    held at t-1; "market held constant" = constant zero rates per tenor (roll-down), same
    as DV01/VaR pillar shocks. theta_1d stays in the report.
21. **Never filter or alter a VaR scenario without an owner decision.**

## Approved owner decisions (round 6, external audit 2026-11-13, docs/audit.md)
22. **Disclosure, option A (ADR-019).** Index levels are not published, but they can be
    recovered from the published option outputs; this is stated in the README limitations
    and in every report. Keep the index-level guard. Never write a real index level into any
    committed file, docs and examples included (two did leak; they stay in history).
23. **v1.0.1** only after the 12 Nov 2026 report is published unattended by the scheduled
    workflow; otherwise report what failed first.

## Data rules (from the brief)
- Keep raw payloads plus normalized parquet under `data/raw/`, with fetch timestamps.
- Forward-fill at most 3 calendar days, logging observation date, age and reason; beyond
  that fail explicitly. Never fill silently.
- EURIBOR fixings: curve-implied proxy, stored immutably on the fixing date; never
  recompute past fixings from today's curve.
- **Terms of use first.** Read a provider's terms before automating access to any new
  source, and record them in `docs/data_sources.md`. Do not download from stoxx.com,
  euronext.com or ftserussell.com/lseg.com: their terms forbid bots and AI tools (ADR-002).
  Dividend yields are entered by the owner by hand. VSTOXX is not used (decision 8).
- Option frozen terms (strikes, trade-date closes) go to the git-ignored
  `config/book.private.yaml`, never to book.yaml (ADR-018).
- Never commit `data/raw/` (ADR-006). Never commit real equity index levels: equity tests
  use labelled synthetic bars.
- The ECB may publish no curve on 24/31 Dec (ADR-007): forward-fill under the ≤ 3-day rule.
- FRED (cross-check only): use the Python `requests` client (curl's default user agent
  gets an empty reply).

## Git
- Remote: github.com/nadirsayed/minibook (default branch `main`).
