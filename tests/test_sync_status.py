import os
import tempfile
import time

from khub.api import App
from khub.db import Store
from khub.storage import ManagedLibrary


def _app():
    store = Store(":memory:")
    lib = ManagedLibrary(tempfile.mkdtemp())
    return App(store, lib)


def _insert_sync(store, source_id, last_sync_at, direction="pull", doc_id="doc-1"):
    store.conn.execute(
        "INSERT INTO sync_states(source_id, doc_id, last_sync_at, etag, hash, direction) "
        "VALUES(?,?,?,?,?,?)",
        (source_id, doc_id, last_sync_at, "", "", direction))
    store.conn.commit()


def test_sync_status_empty():
    """无同步记录时返回空列表。"""
    app = _app()
    code, obj = app.dispatch("GET", "/sync-status")
    assert code == 200
    assert obj == []


def test_sync_status_with_data():
    """插入一条同步记录后正确返回。"""
    app = _app()
    _insert_sync(app.store, "feishu", "2026-07-10T01:00:00")
    code, obj = app.dispatch("GET", "/sync-status")
    assert code == 200
    assert len(obj) == 1
    assert obj[0]["source_id"] == "feishu"
    assert obj[0]["last_sync_at"] == "2026-07-10T01:00:00"
    assert obj[0]["direction"] == "pull"
    assert obj[0]["recent"] is True


def test_sync_status_recent():
    """验证 recent 标记逻辑：24h 内为 True，24h 前为 False。"""
    app = _app()
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    old = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 90000))  # ~25h ago
    _insert_sync(app.store, "obsidian", old, "pull")
    _insert_sync(app.store, "feishu", now, "pull", "doc-2")
    code, obj = app.dispatch("GET", "/sync-status")
    assert code == 200
    status = {s["source_id"]: s for s in obj}
    assert status["obsidian"]["recent"] is False
    assert status["feishu"]["recent"] is True


def test_sync_status_null_last_sync():
    """last_sync_at 为 null 时 recent 为 False。"""
    app = _app()
    _insert_sync(app.store, "obsidian", None, "pull")
    code, obj = app.dispatch("GET", "/sync-status")
    assert code == 200
    assert len(obj) == 1
    assert obj[0]["source_id"] == "obsidian"
    assert obj[0]["last_sync_at"] is None
    assert obj[0]["recent"] is False


def test_api_sync_status_endpoint():
    """HTTP 集成测试：验证端点按预期响应。"""
    app = _app()
    _insert_sync(app.store, "feishu", "2026-07-10T01:00:00")
    _insert_sync(app.store, "obsidian", None, "pull", "doc-3")
    code, obj = app.dispatch("GET", "/sync-status")
    assert code == 200
    assert len(obj) == 2
    ids = [s["source_id"] for s in obj]
    assert "feishu" in ids
    assert "obsidian" in ids
