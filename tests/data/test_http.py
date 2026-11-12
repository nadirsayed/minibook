from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import requests

from minibook.config.settings import Settings
from minibook.data.http import FetchError, RequestsClient

FIXED_NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


class FakeResponse:
    def __init__(self, status: int, body: bytes = b"ok") -> None:
        self.status_code = status
        self.content = body
        self.url = "https://example.test/x?a=1"
        self.headers = {"Content-Type": "text/csv"}


class FakeSession(requests.Session):
    """Synthetic: replays a scripted sequence of responses / exceptions."""

    def __init__(self, script: list[FakeResponse | Exception]) -> None:
        super().__init__()
        self.script = script
        self.calls = 0

    def get(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        item = self.script[self.calls]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return item


def make(
    settings: Settings, script: list[FakeResponse | Exception]
) -> tuple[RequestsClient, FakeSession, list[float]]:
    sleeps: list[float] = []
    session = FakeSession(script)
    client = RequestsClient(
        settings.http, session=session, sleep=sleeps.append, clock=lambda: FIXED_NOW
    )
    return client, session, sleeps


def test_success_first_try(settings: Settings) -> None:
    client, session, sleeps = make(settings, [FakeResponse(200, b"payload")])
    res = client.get("https://example.test/x", {"a": "1"})
    assert res.content == b"payload"
    assert res.fetched_at == FIXED_NOW
    assert res.content_type == "text/csv"
    assert session.calls == 1 and sleeps == []
    assert session.headers["User-Agent"] == settings.http.user_agent


def test_retries_with_exponential_backoff(settings: Settings) -> None:
    script: list[FakeResponse | Exception] = [
        requests.Timeout("slow"),
        FakeResponse(503),
        FakeResponse(200),
    ]
    client, _session, sleeps = make(settings, script)
    assert client.get("https://example.test/x").status == 200
    h = settings.http
    assert sleeps == [h.backoff_initial_s, h.backoff_initial_s * h.backoff_factor]


def test_gives_up_after_max_retries(settings: Settings) -> None:
    n = settings.http.max_retries + 1
    client, session, sleeps = make(settings, [requests.ConnectionError("down")] * n)
    with pytest.raises(FetchError, match=f"failed after {n} attempts"):
        client.get("https://example.test/x")
    assert session.calls == n and len(sleeps) == n - 1


def test_client_error_not_retried(settings: Settings) -> None:
    client, session, _ = make(settings, [FakeResponse(404)])
    with pytest.raises(FetchError) as info:
        client.get("https://example.test/x")
    assert info.value.status == 404 and session.calls == 1
