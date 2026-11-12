from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from minibook.data.http import FetchError, FetchResult
from minibook.data.replay import FixtureClient, RecordingClient, request_id


def test_request_id_ignores_param_order() -> None:
    assert request_id("u", {"b": "2", "a": "1"}) == request_id("u", {"a": "1", "b": "2"})
    assert request_id("u", None) == "u"


def test_record_then_replay(tmp_path: Path) -> None:
    class Live:  # SYNTHETIC upstream
        def get(self, url: str, params: dict[str, str] | None = None) -> FetchResult:
            return FetchResult(
                url + "?q=1", 200, b"body", datetime(2026, 11, 2, tzinfo=UTC), "text/plain"
            )

    rec = RecordingClient(Live(), tmp_path)
    rec.get("https://x.test/a", {"q": "1"})
    replay = FixtureClient(tmp_path)
    res = replay.get("https://x.test/a", {"q": "1"})
    assert res.content == b"body" and res.fetched_at.year == 2026
    with pytest.raises(FetchError, match="no recorded fixture"):
        replay.get("https://x.test/other")
