"""Record and replay HTTP responses (test fixtures and offline reproduction).

Fixture layout (``directory``)::

    manifest.json        {request_id: {file, url, status, content_type, fetched_at_utc, note}}
    <file>               response body exactly as received (or as documented in ``note``)

``request_id`` is the URL plus the sorted, url-encoded query parameters, so the replay
lookup does not depend on parameter order.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from minibook.data.http import HTTP_OK_MAX, HTTP_OK_MIN, FetchError, FetchResult, HttpClient

MANIFEST = "manifest.json"
ID_HASH_LEN = 16


def request_id(url: str, params: Mapping[str, str] | None) -> str:
    """Return a canonical id for a GET request: URL plus sorted query parameters."""
    if not params:
        return url
    return f"{url}?{urlencode(sorted(params.items()))}"


def _load_manifest(directory: Path) -> dict[str, dict[str, str | int | None]]:
    path = directory / MANIFEST
    if not path.exists():
        return {}
    data: dict[str, dict[str, str | int | None]] = json.loads(path.read_text())
    return data


class FixtureClient:
    """Replays responses from a fixture directory; unknown requests raise ``FetchError``."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._manifest = _load_manifest(directory)
        self.requests: list[str] = []

    def get(self, url: str, params: Mapping[str, str] | None = None) -> FetchResult:
        """Return the recorded response for this request."""
        rid = request_id(url, params)
        self.requests.append(rid)
        entry = self._manifest.get(rid)
        if entry is None:
            raise FetchError(rid, "no recorded fixture for this request")
        status = int(entry["status"] or 0)
        if not HTTP_OK_MIN <= status <= HTTP_OK_MAX:
            raise FetchError(rid, f"HTTP {status}", status)
        return FetchResult(
            url=str(entry["url"]),
            status=status,
            content=(self.directory / str(entry["file"])).read_bytes(),
            fetched_at=datetime.fromisoformat(str(entry["fetched_at_utc"])),
            content_type=None if entry["content_type"] is None else str(entry["content_type"]),
        )


class RecordingClient:
    """Wraps a live client and saves every successful response into a fixture directory."""

    def __init__(self, inner: HttpClient, directory: Path) -> None:
        self.inner = inner
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self._manifest = _load_manifest(directory)

    def get(self, url: str, params: Mapping[str, str] | None = None) -> FetchResult:
        """Fetch through the inner client and record the response."""
        result = self.inner.get(url, params)
        rid = request_id(url, params)
        name = hashlib.sha256(rid.encode()).hexdigest()[:ID_HASH_LEN]
        self.record(rid, name, result, note="verbatim")
        return result

    def body_path(self, rid: str) -> Path:
        """Path of the recorded body for request ``rid``."""
        return self.directory / str(self._manifest[rid]["file"])

    def set_note(self, rid: str, note: str) -> None:
        """Replace the provenance note of a recorded request (e.g. after truncation)."""
        self._manifest[rid]["note"] = note
        self._write_manifest()

    def _write_manifest(self) -> None:
        (self.directory / MANIFEST).write_text(
            json.dumps(self._manifest, indent=2, sort_keys=True) + "\n"
        )

    def record(self, rid: str, name: str, result: FetchResult, note: str) -> None:
        """Write one body plus its manifest entry."""
        (self.directory / name).write_bytes(result.content)
        self._manifest[rid] = {
            "file": name,
            "url": result.url,
            "status": result.status,
            "content_type": result.content_type,
            "fetched_at_utc": result.fetched_at.isoformat(),
            "note": note,
        }
        self._write_manifest()
