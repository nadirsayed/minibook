"""Fetcher tests on fixtures recorded from real downloads (scripts/record_fixtures.py,
recorded 2026-11-12, window 2026-10-26..2026-11-06). Reference values below are copied
from those recorded files. Cases marked SYNTHETIC use hand-written bodies."""

from __future__ import annotations

import logging
from datetime import date

import pytest

from minibook.config.settings import Settings
from minibook.data import ecb, fred, mof
from minibook.data.cache import RawStore
from minibook.data.http import FetchError
from minibook.data.replay import FixtureClient

START, END = date(2026, 10, 26), date(2026, 11, 6)
TRADE = date(2026, 11, 2)


# ------------------------------------------------------------------------------------ ECB
def test_ecb_yield_curve(client: FixtureClient, store: RawStore, settings: Settings) -> None:
    obs = ecb.fetch_yield_curve(client, store, settings.ecb, START, END)
    # 9 series (6 Svensson params + 3 validation spot rates) x 10 TARGET days.
    assert len(obs) == 90
    wide = store.load_wide("ecb", "yield_curve")
    row = wide.loc["2026-11-02"]
    # Values from the recorded ECB YC payload (tests/fixtures/http/57b7d73bc0746750).
    assert row["BETA0"] == 1.6613627859
    assert row["TAU2"] == 14.1883835055
    assert row["SR_10Y"] == 3.3265191239
    payloads = list((store.root / "ecb" / "yield_curve" / "payloads").glob("*.csv.gz"))
    assert len(payloads) == 1


def test_ecb_fx_and_estr(client: FixtureClient, store: RawStore, settings: Settings) -> None:
    ecb.fetch_fx(client, store, settings.ecb, START, END)
    ecb.fetch_estr(client, store, settings.ecb, START, END)
    fx = store.load_wide("ecb", "fx").loc["2026-11-02"]
    # Recorded ECB reference rates for 2026-11-02 (fixture 6cbd17c2819123a3).
    assert fx["USD"] == 1.1216
    assert fx["JPY"] == 177.1
    # Recorded EUR STR for 2026-11-02 (fixture a8faae229704ad39).
    assert store.load_wide("ecb", "estr").loc["2026-11-02", "ESTR"] == 2.441


def test_ecb_series_url_combines_keys() -> None:
    url = ecb.series_url("B", "YC", ["P.Q.TAU1", "P.Q.BETA0"])
    assert url == "B/YC/P.Q.BETA0+TAU1"
    url = ecb.series_url("B", "EXR", ["D.USD.EUR.SP00.A", "D.JPY.EUR.SP00.A"])
    assert url == "B/EXR/D.JPY+USD.EUR.SP00.A"
    # Order-independent, so caching and fixture replay are deterministic.
    assert url == ecb.series_url("B", "EXR", ["D.JPY.EUR.SP00.A", "D.USD.EUR.SP00.A"])
    with pytest.raises(ValueError, match="dimensionality"):
        ecb.series_url("B", "X", ["A.B", "A.B.C"])


def test_ecb_empty_body_means_no_data() -> None:
    # SYNTHETIC: the ECB answers 200 with an empty body for a period without data
    # (observed for EXR 2026-12-25..26 on 2026-11-12).
    assert ecb.parse_csvdata(b"", "EXR", {"D.USD.EUR.SP00.A": "USD"}).empty


def test_ecb_rejects_unrequested_series() -> None:
    body = b"KEY,TIME_PERIOD,OBS_VALUE\nEXR.D.GBP.EUR.SP00.A,2026-11-02,0.85\n"  # SYNTHETIC
    with pytest.raises(ValueError, match="unexpected ECB series"):
        ecb.parse_csvdata(body, "EXR", {"D.USD.EUR.SP00.A": "USD"})


def test_ecb_flags_status_and_drops_empty(caplog: pytest.LogCaptureFixture) -> None:
    body = (  # SYNTHETIC
        b"KEY,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
        b"EXR.D.USD.EUR.SP00.A,2026-11-02,1.1,E\n"
        b"EXR.D.USD.EUR.SP00.A,2026-11-03,,A\n"
    )
    with caplog.at_level(logging.WARNING):
        out = ecb.parse_csvdata(body, "EXR", {"D.USD.EUR.SP00.A": "USD"})
    assert len(out) == 1
    assert "OBS_STATUS=E" in caplog.text and "dropping 1" in caplog.text


def test_ecb_404_is_empty(store: RawStore, settings: Settings) -> None:
    class NotFound:
        def get(self, url: str, params: object = None) -> object:
            raise FetchError(url, "HTTP 404", 404)

    class ServerError:
        def get(self, url: str, params: object = None) -> object:
            raise FetchError(url, "HTTP 500", 500)

    assert ecb.fetch_fx(NotFound(), store, settings.ecb, START, END).empty  # type: ignore[arg-type]
    with pytest.raises(FetchError):
        ecb.fetch_fx(ServerError(), store, settings.ecb, START, END)  # type: ignore[arg-type]


# ----------------------------------------------------------------------------------- FRED
def test_fred_all_tenors(client: FixtureClient, store: RawStore, settings: Settings) -> None:
    obs = fred.fetch_ust_cmt(client, store, settings.fred, START, END)
    assert set(obs["series"]) == set(settings.fred.series)
    wide = store.load_wide("fred", "ust_cmt")
    # Recorded DGS2 for 2026-11-02 (fixture 33e8d5b8410f1576).
    assert wide.loc["2026-11-02", "2Y"] == 4.59
    assert len(client.requests) == len(settings.fred.series)  # one request per series


def test_fred_missing_values_dropped() -> None:
    body = b"observation_date,DGS10\n2026-10-09,4.10\n2026-10-12,\n2026-10-13,.\n"  # SYNTHETIC
    out = fred.parse_fredgraph(body, "DGS10", "10Y")
    assert list(out["obs_date"]) == [date(2026, 10, 9)]


def test_fred_bad_header() -> None:
    with pytest.raises(ValueError, match="unexpected FRED CSV header"):
        fred.parse_fredgraph(b"when,what\n2026-10-09,1\n", "DGS10", "10Y")  # SYNTHETIC


# ------------------------------------------------------------------------------------ MoF
def test_mof_history_and_latest(client: FixtureClient, store: RawStore, settings: Settings) -> None:
    mof.fetch_jgb(client, store, settings.mof)
    wide = store.load_wide("mof", "jgb_cm")
    # Recorded jgbcme_all.csv row 2026/10/30 and jgbcme.csv row 2026/11/2.
    assert wide.loc["2026-10-30", "10Y"] == 2.817
    assert wide.loc["2026-11-02", "1Y"] == 1.671
    assert wide.loc["2026-11-02", "40Y"] == 3.96
    # 2026-11-03 is a Japanese holiday (Culture Day): no row.
    assert "2026-11-03" not in wide.index.strftime("%Y-%m-%d")


def test_mof_parser_handles_missing_and_footer() -> None:
    body = (  # SYNTHETIC, same layout as the MoF file
        "Interest Rate,,,(Unit : %)\n"
        "Date,1Y,30Y,40Y\n"
        "1974/9/24,10.327,-,-\n"
        ",,,\n"
        '"  note: clear the browser cache",,,\n'
    ).encode("latin-1")
    out = mof.parse_jgbcme(body, "latin-1", "-")
    assert list(out["series"]) == ["1Y"] and list(out["value"]) == [10.327]


def test_mof_parser_requires_header() -> None:
    with pytest.raises(ValueError, match="header line"):
        mof.parse_jgbcme(b"nothing here\n", "latin-1", "-")  # SYNTHETIC
