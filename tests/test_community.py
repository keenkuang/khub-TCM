import pytest
pytestmark = pytest.mark.smoke

from khub.db import Store
from khub.community.articles import create_article, list_articles, get_article, list_tags
from khub.community.comments import add_comment, list_comments


def test_create_article():
    store = Store(":memory:")
    aid = create_article(store, "桂枝汤方解", "桂枝汤由五味药组成...", tags=["方剂", "伤寒论"])
    assert aid > 0


def test_list_articles():
    store = Store(":memory:")
    create_article(store, "A", "内容A", tags=["中医"])
    create_article(store, "B", "内容B", tags=["西医"])
    assert len(list_articles(store)) == 2


def test_get_article():
    store = Store(":memory:")
    aid = create_article(store, "测试", "内容")
    a = get_article(store, aid)
    assert a["title"] == "测试"
    assert a["view_count"] >= 1


def test_tags():
    store = Store(":memory:")
    create_article(store, "A", "x", tags=["方剂"])
    create_article(store, "B", "y", tags=["针灸"])
    tags = list_tags(store)
    assert "方剂" in tags
    assert "针灸" in tags


def test_comments():
    store = Store(":memory:")
    aid = create_article(store, "文章", "内容")
    cid = add_comment(store, aid, "好文章！")
    assert cid > 0
    comments = list_comments(store, aid)
    assert len(comments) == 1
    assert comments[0]["content"] == "好文章！"
