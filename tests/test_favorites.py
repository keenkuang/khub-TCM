from khub.db import Store
from khub.favorites import toggle_favorite, list_favorites, is_favorite


def test_toggle_add():
    store = Store(":memory:")
    result = toggle_favorite(store, "doc1")
    assert result is True  # 已收藏
    assert is_favorite(store, "doc1") is True


def test_toggle_remove():
    store = Store(":memory:")
    toggle_favorite(store, "doc1")
    result = toggle_favorite(store, "doc1")
    assert result is False  # 取消收藏


def test_list_favorites():
    store = Store(":memory:")
    toggle_favorite(store, "doc1")
    favs = list_favorites(store)
    assert len(favs) == 1
    assert favs[0]["doc_id"] == "doc1"


def test_list_favorites_empty():
    store = Store(":memory:")
    assert list_favorites(store) == []
