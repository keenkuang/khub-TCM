"""审计日志增强测试。"""
from khub.db import Store
from khub.audit import record, search_audit


def test_record():
    store = Store(":memory:")
    record(store, "test.event", actor="user1", scope="test", details={"key": "val"})
    logs = search_audit(store, event="test.event")
    assert len(logs) >= 1


def test_search_by_actor():
    store = Store(":memory:")
    record(store, "login", actor="admin")
    logs = search_audit(store, actor="admin")
    assert len(logs) >= 1


def test_search_empty():
    store = Store(":memory:")
    assert search_audit(store, event="nonexistent") == []
