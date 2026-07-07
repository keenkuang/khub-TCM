"""Tests for khub/quip.py — uses mocked HTTP, no real network calls."""

import json
import urllib.request

from khub.db import Store
from khub.quip import pull_all


# ── Mock HTTP helpers ─────────────────────────────────────────────────────────

MOCK_RESPONSES = {
    "/1/folders/ROOT": {
        "folder": {"id": "ROOT"},
        "children": [{"thread_id": "T1"}, {"folder_id": "SUB"}],
    },
    "/1/folders/SUB": {
        "folder": {"id": "SUB"},
        "children": [{"thread_id": "T2"}],
    },
    "/1/threads/T1": {
        "thread": {"id": "T1", "title": "文档1"},
        "html": "<p>正文1</p>",
    },
    "/1/threads/T2": {
        "thread": {"id": "T2", "title": "文档2"},
        "html": "<p>正文2</p>",
    },
}


class FakeResponse:
    """A file-like object returned by urlopen, usable as a context manager."""

    def __init__(self, data: bytes):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._data


def fake_urlopen(request, *args, **kwargs):
    """Return a FakeResponse based on the request URL."""
    url = request.full_url if isinstance(request, urllib.request.Request) else request
    # Strip base to get path
    path = url.replace("https://platform.quip.com", "")
    body = MOCK_RESPONSES.get(path)
    if body is None:
        raise urllib.error.HTTPError(
            url, 404, f"Not found: {path}", {}, None
        )
    return FakeResponse(json.dumps(body).encode("utf-8"))


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestQuipPull:
    def test_ingest_documents(self, monkeypatch):
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        store = Store(":memory:")

        ingested, skipped = pull_all(store, "fake_token", "ROOT")

        assert ingested == 2, f"expected 2 ingested, got {ingested}"
        assert skipped == 0, f"expected 0 skipped, got {skipped}"

        # Verify FTS search works
        results = store.search_old("正文1")
        assert len(results) >= 1, "should find document containing '正文1'"
        found_ids = {r[0] for r in results}
        assert "quip:T1" in found_ids

    def test_idempotent_skip(self, monkeypatch):
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        store = Store(":memory:")

        # First pull
        pull_all(store, "fake_token", "ROOT")

        # Second pull — all should be skipped
        ingested, skipped = pull_all(store, "fake_token", "ROOT")

        assert ingested == 0, f"expected 0 ingested on second call, got {ingested}"
        assert skipped == 2, f"expected 2 skipped on second call, got {skipped}"
