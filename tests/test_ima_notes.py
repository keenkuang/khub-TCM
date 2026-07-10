import json
import urllib.request
import pytest
from khub.db import Store
pytestmark = pytest.mark.net



class FakeResp:
    def __init__(self, content):
        self._c = json.dumps(content).encode()

    def read(self):
        return self._c

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("IMA_CLIENT_ID", "test")
    monkeypatch.setenv("IMA_API_KEY", "test")


@pytest.fixture(autouse=True)
def _mock(monkeypatch):
    responses = {}

    def fake(url, *a, **kw):
        u = url.get_full_url() if hasattr(url, "get_full_url") else str(url)
        if "list_notebook" in u:
            return FakeResp({
                "code": 0,
                "data": {
                    "note_folder_infos": [
                        {"folder_id": "f1", "name": "中医笔记", "note_number": 2},
                    ],
                    "is_end": True,
                },
            })
        if "list_note" in u:
            return FakeResp({
                "code": 0,
                "data": {
                    "note_book_list": [
                        {
                            "note_id": "n1",
                            "title": "经方心得",
                            "note_ext_info": {"folder_name": "中医笔记"},
                        },
                        {
                            "note_id": "n2",
                            "title": "诊余笔记",
                            "note_ext_info": {"folder_name": "中医笔记"},
                        },
                    ],
                    "is_end": True,
                },
            })
        if "get_doc_content" in u:
            return FakeResp({
                "code": 0,
                "data": {"content": "太阳病，桂枝汤主之。"},
            })
        return FakeResp({"code": 0, "data": {}})

    monkeypatch.setattr(urllib.request, "urlopen", fake)


def test_list_notebooks():
    from khub.ima_notes import list_notebooks

    nbs = list_notebooks()
    assert len(nbs) == 1
    assert nbs[0]["name"] == "中医笔记"


def test_list_notes():
    from khub.ima_notes import list_notes

    notes = list_notes("f1")
    assert len(notes) == 2
    assert notes[0]["title"] == "经方心得"


def test_get_note_content():
    from khub.ima_notes import get_note_content

    content = get_note_content("n1")
    assert "桂枝汤" in content


def test_sync_all(monkeypatch):
    from khub.ima_notes import _req

    def fake_req(endpoint, body):
        if endpoint == "list_notebook":
            return {
                "note_folder_infos": [
                    {"folder_id": "f1", "name": "中医笔记", "note_number": 1},
                ],
                "is_end": True,
            }
        if endpoint == "list_note":
            return {
                "note_book_list": [
                    {
                        "note_id": "n1",
                        "title": "经方心得",
                        "note_ext_info": {"folder_name": "中医笔记"},
                    },
                ],
                "is_end": True,
            }
        if endpoint == "get_doc_content":
            return {"content": "太阳病，桂枝汤主之。"}
        return {}

    monkeypatch.setattr("khub.ima_notes._req", fake_req)

    store = Store(":memory:")
    from khub.ima_notes import sync_all

    res = sync_all(store, verbose=False)
    assert len(res) == 1
    assert res[0]["ingested"] >= 1
    doc = store.search_old("桂枝汤")
    assert len(doc) >= 1
