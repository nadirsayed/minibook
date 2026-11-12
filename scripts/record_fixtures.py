"""Record real HTTP responses into tests/fixtures/http for offline tests.

Window: 2026-10-26 .. 2026-11-06 (around the trade date 2026-11-02).

* ECB YC / EXR / EST, U.S. Treasury par curve (2026 file) and FRED DGS*: verbatim.
* MoF jgbcme_all.csv (history since 1974, ~0.7 MB): truncated to the title, header and
  rows dated on or after 2026-10-01. Kept rows are byte-identical. The manifest ``note``
  says so.
* MoF jgbcme.csv (current month): verbatim.
* Equity index closes (yfinance) are NOT recorded: Yahoo terms and index-provider
  licences restrict redistribution, so equity tests use labelled synthetic bars.

Usage: uv run python scripts/record_fixtures.py
"""

from __future__ import annotations

import logging
import sys
import tempfile
from datetime import date
from pathlib import Path

from minibook.config.settings import load_settings
from minibook.data import ecb, fred, mof, treasury
from minibook.data.cache import RawStore
from minibook.data.http import RequestsClient
from minibook.data.replay import RecordingClient, request_id

LOG = logging.getLogger("record_fixtures")

FIXTURE_DIR = Path("tests/fixtures/http")
START, END = date(2026, 10, 26), date(2026, 11, 6)
MOF_HISTORY_KEEP_FROM = (2026, 10, 1)


def _truncate_mof_history(rec: RecordingClient, url: str) -> None:
    rid = request_id(url, None)
    path = rec.body_path(rid)
    lines = path.read_bytes().split(b"\n")
    kept = []
    for i, line in enumerate(lines):
        first = line.split(b",", 1)[0].decode("latin-1")
        parts = first.split("/")
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            if tuple(int(p) for p in parts) < MOF_HISTORY_KEEP_FROM:
                continue
        elif i > 1 and not line.strip(b", \r"):
            continue
        kept.append(line)
    path.write_bytes(b"\n".join(kept))
    rec.set_note(
        rid,
        (
            "truncated: title, header and rows dated >= 2026-10-01 kept byte-identical; "
            "earlier rows removed to keep the fixture small"
        ),
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)
    s = load_settings()
    rec = RecordingClient(RequestsClient(s.http), FIXTURE_DIR)
    with tempfile.TemporaryDirectory() as tmp:
        store = RawStore(Path(tmp))
        ecb.fetch_yield_curve(rec, store, s.ecb, START, END)
        ecb.fetch_fx(rec, store, s.ecb, START, END)
        ecb.fetch_estr(rec, store, s.ecb, START, END)
        treasury.fetch_par_curve(rec, store, s.treasury, START, END)
        fred.fetch_ust_cmt(rec, store, s.fred, START, END)
        mof.fetch_jgb(rec, store, s.mof, include_history=True)
    _truncate_mof_history(rec, s.mof.history_url)
    LOG.info("recorded responses into %s", FIXTURE_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
