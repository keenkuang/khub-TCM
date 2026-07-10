import pytest
from khub.db import Store
from khub.search2 import unified_search

pytestmark = pytest.mark.smoke


def test_search_empty():
    store = Store(":memory:")
    results = unified_search(store, "")
    assert results == []


def test_search_docs():
    store = Store(":memory:")
    store.conn.execute("INSERT INTO documents (canonical_id, title, source_ids) VALUES ('doc1', '感冒治疗', '[]')")
    # FTS 表需要手动同步，此处验证接口不崩
    results = unified_search(store, "感冒")
    assert isinstance(results, list)


def test_search_patients():
    store = Store(":memory:")
    from khub.clinical.patients import add_patient
    add_patient(store, "1", "张三")
    results = unified_search(store, "张三", type="patients")
    assert len(results) >= 1
    assert results[0]["title"] == "张三"


def test_search_courses():
    store = Store(":memory:")
    from khub.course.store import add_course
    add_course(store, "中医基础", teacher="李教授")
    results = unified_search(store, "中医", type="courses")
    assert len(results) >= 1


def test_search_herbs():
    store = Store(":memory:")
    from khub.knowledge.herbs import add_herb
    add_herb(store, "桂枝", nature="温", flavor="辛甘", channel="心/肺/膀胱", category="解表药")
    results = unified_search(store, "桂枝", type="herbs")
    assert len(results) >= 1


def test_search_type_filter():
    store = Store(":memory:")
    results = unified_search(store, "test", type="docs")
    for r in results:
        assert r["entity_type"] == "document"
