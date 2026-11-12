"""HTTP access with retry/backoff, behind a small protocol so tests can replay fixtures.

Every fetcher depends on :class:`HttpClient`, never on ``requests`` directly. Production
uses :class:`RequestsClient`; tests use :class:`minibook.data.fixtures.FixtureClient`, which
replays responses recorded from real downloads.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import requests

from minibook.config.settings import HttpSettings

LOG = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
HTTP_OK_MIN, HTTP_OK_MAX = 200, 299


@dataclass(frozen=True)
class FetchResult:
    """One HTTP response, as received.

    Attributes
    ----------
    url
        Final URL, including the query string.
    status
        HTTP status code.
    content
        Raw response body (bytes, undecoded).
    fetched_at
        Time the response was received (timezone-aware, UTC).
    content_type
        ``Content-Type`` header, if any.
    """

    url: str
    status: int
    content: bytes
    fetched_at: datetime
    content_type: str | None = None


class FetchError(RuntimeError):
    """Raised when a request fails after all retries, or returns a non-2xx status."""

    def __init__(self, url: str, reason: str, status: int | None = None) -> None:
        super().__init__(f"{url}: {reason}")
        self.url = url
        self.status = status


class HttpClient(Protocol):
    """Minimal GET interface used by every fetcher."""

    def get(self, url: str, params: Mapping[str, str] | None = None) -> FetchResult:
        """GET ``url`` with query ``params``; raise :class:`FetchError` on failure."""
        ...


def utc_now() -> datetime:
    """Return the current time, timezone-aware UTC."""
    return datetime.now(UTC)


class RequestsClient:
    """``requests``-based client with exponential backoff.

    Retries connection errors, timeouts and statuses in ``RETRYABLE_STATUS``. The wait before
    retry k (0-based) is ``backoff_initial_s * backoff_factor**k``. Other non-2xx statuses
    fail immediately.

    Parameters
    ----------
    settings
        HTTP settings (timeout, retries, backoff, user agent).
    session
        Optional ``requests.Session`` (injected in tests).
    sleep, clock
        Injected for deterministic tests.
    """

    def __init__(
        self,
        settings: HttpSettings,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._s = settings
        self._session = session or requests.Session()
        self._session.headers["User-Agent"] = settings.user_agent
        self._sleep = sleep
        self._clock = clock

    def get(self, url: str, params: Mapping[str, str] | None = None) -> FetchResult:
        """GET with retries. See class docstring."""
        attempts = self._s.max_retries + 1
        last_reason = "no attempt made"
        for k in range(attempts):
            try:
                resp = self._session.get(url, params=params, timeout=self._s.timeout_s)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_reason = f"{type(exc).__name__}: {exc}"
            else:
                if HTTP_OK_MIN <= resp.status_code <= HTTP_OK_MAX:
                    return FetchResult(
                        url=resp.url,
                        status=resp.status_code,
                        content=resp.content,
                        fetched_at=self._clock(),
                        content_type=resp.headers.get("Content-Type"),
                    )
                if resp.status_code not in RETRYABLE_STATUS:
                    raise FetchError(resp.url, f"HTTP {resp.status_code}", resp.status_code)
                last_reason = f"HTTP {resp.status_code}"
            if k < attempts - 1:
                wait = self._s.backoff_initial_s * self._s.backoff_factor**k
                LOG.warning(
                    "GET %s failed (%s); retry %d/%d in %.1fs",
                    url,
                    last_reason,
                    k + 1,
                    self._s.max_retries,
                    wait,
                )
                self._sleep(wait)
        raise FetchError(url, f"failed after {attempts} attempts: {last_reason}")
