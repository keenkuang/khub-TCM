import os
import tempfile

from khub.db import Store
from khub.models import CanonicalDoc


def _add(store, cid, title, content, source="test"):
    store.store_document(CanonicalDoc(
        canonical_id=cid, title=title, content=content,
        source=source, source_id=cid))


def test_search_pagination():
    store = Store(":memory:")
    for i in range(30):
        _add(store, f"d{i}", f"文档{i}", "太阳病" + str(i))
    hits, total = store.search("太阳病", page=0, per_page=10)
    assert len(hits) == 10
    assert total == 30
    hits2, _ = store.search("太阳病", page=1, per_page=10)
    assert hits2[0][0] == "d10"


def test_search_source_filter():
    store = Store(":memory:")
    _add(store, "o1", "obsidian文档", "内容", source="obsidian")
    _add(store, "i1", "ima文档", "内容", source="ima")
    hits, total = store.search("内容", source="obsidian")
    assert total == 1
    assert hits[0][0] == "o1"


def test_search_pagination_api():
    """测试 API 返回格式含分页信息。"""
    from khub.api import App
    from khub.storage import ManagedLibrary
    d = tempfile.mkdtemp()
    store = Store(":memory:")
    lib = ManagedLibrary(os.path.join(d, "lib"))
    app = App(store, lib)
    for i in range(5):
        store.store_document(CanonicalDoc(
            canonical_id=f"d{i}", title="文档", content="test",
            source="test", source_id=f"d{i}"))
    code, obj = app.dispatch("GET", "/search?q=test&page=0&per=2")
    assert code == 200
    assert "total" in obj
    assert len(obj["hits"]) == 2


def test_search_empty_query():
    """空查询应返回空结果。"""
    store = Store(":memory:")
    hits, total = store.search("")
    assert total == 0
    assert hits == []


def test_search_special_chars():
    """特殊字符不应导致崩溃。"""
    store = Store(":memory:")
    from khub.models import CanonicalDoc
    store.store_document(CanonicalDoc(canonical_id="s1", title="文档", content="正常内容", source="test", source_id="s1"))
    # 各种特殊字符
    for q in ["<script>", "%%%", "' OR '1'='1", "--", "\\n", "苍术(炒)", "（"]:
        try:
            store.search(q)
        except Exception as e:
            assert False, f"搜索 {q!r} 引发异常: {e}"
