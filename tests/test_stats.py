import tempfile
from khub.api import App
from khub.db import Store
from khub.storage import ManagedLibrary
from khub.models import CanonicalDoc
import pytest
pytestmark = pytest.mark.smoke



def test_stats_endpoint():
    d = tempfile.mkdtemp()
    store = Store(":memory:")
    lib = ManagedLibrary(d + "/lib")
    app = App(store, lib)
    # 初始化 ops 表以支持运营统计断言
    from khub.ops.store import init as ops_init
    ops_init(store)
    # 添加几篇不同来源的文档
    store.store_document(
        CanonicalDoc(
            canonical_id="o1",
            title="o",
            content="",
            source="obsidian",
            source_id="o1",
        )
    )
    store.store_document(
        CanonicalDoc(
            canonical_id="i1",
            title="i",
            content="",
            source="ima",
            source_id="i1",
        )
    )
    code, obj = app.dispatch("GET", "/stats")
    assert code == 200
    assert obj["total"] == 2
    assert "sources" in obj
    assert "obsidian" in obj["sources"]
    # 运营统计（表存在时应含字段）
    assert "appointments_by_status" in obj
    assert "schedules_coverage" in obj


def test_stats_recent_is_list():
    """recent 字段应为列表且含 id/title。"""
    import tempfile
    from khub.api import App
    from khub.storage import ManagedLibrary
    d = tempfile.mkdtemp()
    store = Store(":memory:")
    lib = ManagedLibrary(d + "/lib")
    app = App(store, lib)
    from khub.models import CanonicalDoc
    store.store_document(CanonicalDoc(canonical_id="r1", title="最近文档", content="内容", source="test", source_id="r1"))
    code, obj = app.dispatch("GET", "/stats")
    assert code == 200
    assert len(obj["recent"]) >= 1
    assert "id" in obj["recent"][0]
