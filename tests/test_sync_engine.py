from khub.db import Store
from khub.sync_engine import TwoWaySyncEngine, TwoWaySyncAdapter


class FakeIMAAdapter(TwoWaySyncAdapter):
    name = "test_ima"
    direction = "both"

    def pull(self, store):
        return [
            {"source_id": "test:m1", "title": "文档1", "content": "正文1",
             "hash": "h1"},
        ]

    def push(self, store, doc_id, content, title):
        return doc_id


def test_sync_pull():
    store = Store(":memory:")
    engine = TwoWaySyncEngine(store)
    items = [{"source_id": "src:d1", "title": "测试", "content": "你好",
              "hash": "h1"}]
    res = engine.sync_pull("test_src", items)
    assert res["ingested"] == 1
    doc = store.get_document("src:d1")
    assert doc is not None and doc["title"] == "测试"
    state = store.get_sync_state("test_src", "src:d1")
    assert state is not None and state["hash"] == "h1"


def test_sync_push():
    store = Store(":memory:")
    from khub.models import CanonicalDoc
    doc = CanonicalDoc(canonical_id="test:d1", title="原始", content="v1",
                       source="test_source", source_id="test:d1")
    store.store_document(doc)
    store.upsert_sync_state("test_source", "test:d1", hash="old_hash",
                            direction="pull")
    # 在 kHUB 修改它
    doc2 = CanonicalDoc(canonical_id="test:d1", title="修改后", content="v2",
                        source="test_source", source_id="test:d1", origin="hub")
    store.store_document(doc2)
    engine = TwoWaySyncEngine(store)
    adapter = FakeIMAAdapter()
    res = engine.sync_push("test_source", adapter)
    assert res["pushed"] == 1
    state = store.get_sync_state("test_source", "test:d1")
    assert state["hash"] != "old_hash"


def test_sync_both():
    store = Store(":memory:")
    engine = TwoWaySyncEngine(store)
    adapter = FakeIMAAdapter()
    res = engine.sync("test_ima", adapter, direction="both")
    assert "pull" in res
    assert "push" in res
