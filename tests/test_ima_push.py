import os, json, pytest
from khub.db import Store
from khub.ima import _push_doc, sync_adapter


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch):
    monkeypatch.setenv("IMA_CLIENT_ID", "test")
    monkeypatch.setenv("IMA_API_KEY", "test")


def _patch_req(monkeypatch, responses):
    """替换 khub.ima._req 返回预设响应。"""
    import khub.ima as ima
    def fake_req(endpoint, body):
        if endpoint in responses:
            return responses[endpoint]
        return {}
    monkeypatch.setattr(ima, "_req", fake_req)


def test_push_document(monkeypatch):
    _patch_req(monkeypatch, {
        "create_media": {"media_id": "push_m1"},
        "add_knowledge": {"media_id": "push_m1"},
    })
    store = Store(":memory:")
    mid = _push_doc(store, "kb1", "推送正文", "推送标题")
    assert mid == "push_m1"


def test_push_raises_on_no_media_id(monkeypatch):
    _patch_req(monkeypatch, {
        "create_media": {},
    })
    store = Store(":memory:")
    with pytest.raises(RuntimeError):
        _push_doc(store, "kb1", "正文", "标题")


def test_sync_adapter_returns_adapter():
    adapter = sync_adapter(None, "kb1")
    assert adapter.name == "ima:kb1"
    assert adapter.direction == "both"
    assert hasattr(adapter, "pull")
    assert hasattr(adapter, "push")
    assert hasattr(adapter, "delete")
