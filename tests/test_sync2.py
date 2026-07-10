import pytest
from khub.db import Store
from khub.sync2 import record_change, push, pull, status


def test_record_and_pull():
    store = Store(":memory:")
    record_change(store, "patient", "1", "update", {"name": "张三"})
    result = pull(store, "test-client")
    assert len(result["changes"]) >= 1
    assert result["changes"][0]["entity_type"] == "patient"


def test_push():
    store = Store(":memory:")
    changes = [{"entity_type": "appointment", "entity_id": "5", "action": "create", "data": {"date": "2026-08-01"}}]
    result = push(store, "phone-1", changes)
    assert result["applied"] == 1
    assert len(result["conflicts"]) == 0


def test_status():
    store = Store(":memory:")
    st = status(store)
    assert "total_changes" in st
    assert "devices" in st


def test_conflict_detection():
    store = Store(":memory:")
    record_change(store, "doc", "d1", "update", {"title": "v1"})
    # 客户端携带旧版本号
    changes = [{"entity_type": "doc", "entity_id": "d1", "action": "update", "data": {"title": "v0"}, "version": 0}]
    result = push(store, "client-1", changes)
    assert len(result["conflicts"]) >= 1  # 检测到冲突


def test_pull_empty():
    store = Store(":memory:")
    result = pull(store, "new-client", since_version=0)
    assert result["changes"] == []
