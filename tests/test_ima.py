import json
import urllib.request
import pytest
from khub.db import Store
from khub.ima import list_knowledge_bases, get_knowledge_base, sync_all


class _FakeResponse:
    """Mock HTTP response supporting context manager."""

    def __init__(self, content: bytes):
        self._content = content

    def read(self):
        return self._content

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


_dl_counter = [0]


def _fake_urlopen(req_or_url, timeout=None):
    if isinstance(req_or_url, str):
        url = req_or_url
        body = b""
    else:
        url = req_or_url.get_full_url()
        body = getattr(req_or_url, "data", b"") or b""

    # --- search_knowledge_base ---
    if "search_knowledge_base" in url:
        return _FakeResponse(
            json.dumps(
                {
                    "code": 0,
                    "data": {
                    "info_list": [
                        {
                            "kb_id": "kb1",
                            "kb_name": "中医库",
                            "content_count": "2",
                        },
                        {
                            "kb_id": "kb2",
                            "kb_name": "西医库",
                            "content_count": "5",
                        },
                    ],
                        "is_end": True,
                    },
                }
            ).encode("utf-8")
        )

    # --- get_knowledge_base ---
    if "get_knowledge_base" in url:
        return _FakeResponse(
            json.dumps(
                {
                    "code": 0,
                    "data": {
                        "infos": {
                            "kb1": {
                                "id": "kb1",
                                "name": "中医库",
                            }
                        }
                    },
                }
            ).encode("utf-8")
        )

    # --- get_knowledge_list ---
    if "get_knowledge_list" in url:
        body_obj = json.loads(body) if body else {}
        if body_obj.get("folder_id") == "f1":
            payload = {
                "code": 0,
                "data": {
                    "knowledge_list": [
                        {
                            "title": "金匮要略",
                            "media_id": "m2",
                            "file_info": {"file_name": "金匮要略.md", "file_size": 500},
                            "doc_type": 1,
                        }
                    ],
                    "is_end": True,
                },
            }
        else:
            payload = {
                "code": 0,
                "data": {
                    "knowledge_list": [
                        {
                            "title": "伤寒论",
                            "media_id": "m1",
                            "file_info": {"file_name": "伤寒论.txt", "file_size": 1000},
                            "doc_type": 1,
                        },
                        {
                            "title": "子目录",
                            "media_id": "",
                            "doc_type": 2,
                            "folder_id": "f1",
                        },
                    ],
                    "is_end": True,
                },
            }
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    # --- get_media_info ---
    if "get_media_info" in url:
        body_obj = json.loads(body) if body else {}
        mid = body_obj.get("media_id", "")
        if mid == "m1":
            payload = {
                "code": 0,
                "data": {
                    "media_type": 1,
                    "url_info": {
                        "url": "http://fake/dl",
                        "file_name": "伤寒论.txt",
                        "file_size": 1000,
                    },
                },
            }
        else:
            payload = {
                "code": 0,
                "data": {
                    "media_type": 1,
                    "url_info": {
                        "url": "http://fake/dl",
                        "file_name": "金匮要略.md",
                        "file_size": 500,
                    },
                },
            }
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    # --- file download ---
    if url == "http://fake/dl":
        _dl_counter[0] += 1
        if _dl_counter[0] == 1:
            return _FakeResponse(
                b"\xe5\xa4\xaa\xe9\x98\xb3\xe7\x97\x85\xef\xbc\x8c"
                b"\xe5\x8f\x91\xe7\x83\xad\xe6\xb1\x97\xe5\x87\xba"
                b"\xef\xbc\x8c\xe6\xa1\x82\xe6\x9e\x9d\xe6\xb1\xa4"
                b"\xe4\xb8\xbb\xe4\xb9\x8b\xe3\x80\x82"
            )
        return _FakeResponse(
            b"\xe9\x87\x91\xe5\x8c\xa1\xe8\xa6\x81\xe7\x95\xa5"
            b"\xef\xbc\x8c\xe8\x84\x8f\xe8\x85\x91\xe7\xbb\x8f"
            b"\xe7\xbb\x9c\xe5\x85\x88\xe5\x90\x8e\xe7\x97\x85"
            b"\xe3\x80\x82"
        )

    raise RuntimeError(f"Unexpected URL: {url}")


@pytest.fixture
def store():
    return Store()


@pytest.fixture(autouse=True)
def _reset_dl_counter():
    _dl_counter[0] = 0
    yield


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    monkeypatch.setenv("IMA_CLIENT_ID", "test")
    monkeypatch.setenv("IMA_API_KEY", "test")


def test_list_knowledge_bases(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    result = list_knowledge_bases()
    assert len(result) == 2
    assert result[0]["name"] == "中医库"
    assert result[1]["name"] == "西医库"


def test_get_knowledge_base(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    result = get_knowledge_base("kb1")
    assert result["id"] == "kb1"
    assert result["name"] == "中医库"


def test_sync_all(monkeypatch, store):
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    results = sync_all(store)
    # sync_all processes both kb1 and kb2, but both share same media_ids.
    # kb1 sync finds 2 docs (伤寒论 + 金匮要略 via subfolder), ingests both.
    # kb2 sync finds same docs already ingested, so skipped.
    # Total ingested = 2 across both KBs.
    total = sum(r["ingested"] for r in results)
    assert total == 2
    assert len(results) == 2

    # Verify documents are searchable
    hits = store.search("太阳病")
    assert len(hits) >= 1
    hits2 = store.search("金匮要略")
    assert len(hits2) >= 1


def test_idempotent(monkeypatch, store):
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    results1 = sync_all(store)
    total1 = sum(r["ingested"] for r in results1)
    assert total1 == 2
    # Reset download counter for second pass
    _dl_counter[0] = 0
    results2 = sync_all(store)
    total2 = sum(r["ingested"] for r in results2)
    assert total2 == 0
