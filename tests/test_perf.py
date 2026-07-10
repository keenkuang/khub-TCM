"""性能优化测试。"""
import time
from khub.db import Store
from khub.cache import get, set, clear, invalidate


def test_cache_basic():
    clear()
    set("key1", "value1", ttl=10)
    assert get("key1") == "value1"


def test_cache_expiry():
    clear()
    set("expire_key", "val", ttl=0)
    import time as _t
    _t.sleep(0.01)
    # TTL 0 用默认 5 秒，不应过期
    assert get("expire_key") == "val"


def test_cache_clear():
    set("a", 1)
    set("b", 2)
    clear()
    assert get("a") is None
    assert get("b") is None


def test_cache_invalidate_prefix():
    set("stats:daily", "data1")
    set("stats:weekly", "data2")
    set("other", "data3")
    invalidate("stats:")
    assert get("stats:daily") is None
    assert get("stats:weekly") is None
    assert get("other") == "data3"


def test_db_indexes_exist():
    store = Store(":memory:")
    indexes = store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
    ).fetchall()
    index_names = [r["name"] for r in indexes]
    # 核心表索引（init_schema 中创建的表的索引）
    assert "idx_documents_source_ids" in index_names
    assert "idx_documents_updated" in index_names
    assert "idx_document_versions_doc" in index_names
    assert "idx_embeddings_doc_id" in index_names
    assert "idx_notifications_user" in index_names
    assert "idx_followup_plans_patient" in index_names
    assert "idx_workflow_instances_def" in index_names
    assert "idx_wechat_articles_status" in index_names
    assert "idx_kg_relations_source" in index_names
    assert "idx_sync_changes_entity" in index_names
    # patients/records/consultations/appointments 表为惰性创建，对应索引在
    # 首次使用对应模块后才会存在；此处只校验 init_schema 阶段创建的索引数。
    assert len(index_names) >= 12
