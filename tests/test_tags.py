from khub.db import Store
from khub.tags import add_tag, remove_tag, list_tags, get_doc_tags


def test_add_tag():
    store = Store(":memory:")
    add_tag(store, "doc1", "中医")
    tags = get_doc_tags(store, "doc1")
    assert "中医" in tags


def test_remove_tag():
    store = Store(":memory:")
    add_tag(store, "doc1", "中医")
    remove_tag(store, "doc1", "中医")
    assert get_doc_tags(store, "doc1") == []


def test_list_tags():
    store = Store(":memory:")
    add_tag(store, "doc1", "中医")
    add_tag(store, "doc2", "中医")
    add_tag(store, "doc1", "方剂")
    all_tags = {t["tag"]: t["count"] for t in list_tags(store)}
    assert all_tags.get("中医", 0) == 2
    assert all_tags.get("方剂", 0) == 1


def test_duplicate_rejected():
    store = Store(":memory:")
    add_tag(store, "doc1", "中医")
    add_tag(store, "doc1", "中医")  # 重复，INSERT OR IGNORE
    assert len(get_doc_tags(store, "doc1")) == 1
