from khub.db import Store
from khub.models import CanonicalDoc


def _add(store, cid, title, content):
    store.store_document(CanonicalDoc(canonical_id=cid, title=title,
                                       content=content, source="test",
                                       source_id=cid))


def test_bm25_ranks_relevant_first():
    store = Store(":memory:")
    _add(store, "d1", "桂枝汤", "太阳病，发热汗出，桂枝汤主之。")
    _add(store, "d2", "麻黄汤", "太阳病，无汗而喘，麻黄汤主之。")
    hits = store.search_old("桂枝汤")
    assert hits[0][0] == "d1"  # 精确标题匹配排第一


def test_bm25_short_query_like():
    store = Store(":memory:")
    _add(store, "d1", "大黄", "大黄牡丹汤主之。")
    _add(store, "d2", "地黄", "六味地黄丸。")
    hits = store.search_old("大黄")
    assert hits[0][0] == "d1"


def test_bm25_multi_token():
    store = Store(":memory:")
    _add(store, "d1", "桂枝麻黄", "桂枝麻黄各半汤。")
    _add(store, "d2", "桂枝汤", "太阳病，桂枝汤。")
    _add(store, "d3", "麻黄汤", "太阳病，麻黄汤。")
    hits = store.search_old("桂枝 麻黄")
    # 同时包含两者的排最前
    assert hits[0][0] == "d1"
