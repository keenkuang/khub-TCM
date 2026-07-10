"""微信公众号发布系统测试（离线，不调用真实 API）。"""
import json
import pytest
from khub.db import Store
from khub.wechat.store import (
    add_article, list_articles, get_article,
    add_schedule, scan_due_schedules,
    sync_followers,
)


def test_add_article():
    store = Store(":memory:")
    aid = add_article(store, "测试文章", "<p>测试内容</p>", author="作者")
    assert aid > 0
    a = get_article(store, aid)
    assert a["title"] == "测试文章"
    assert a["author"] == "作者"
    assert a["status"] == "draft"


def test_list_articles():
    store = Store(":memory:")
    add_article(store, "文章A", "内容A")
    add_article(store, "文章B", "内容B")
    assert len(list_articles(store)) == 2


def test_list_by_status():
    store = Store(":memory:")
    add_article(store, "草稿", "内容")
    articles = list_articles(store, status="draft")
    assert len(articles) >= 1
    assert list_articles(store, status="published") == []


def test_add_schedule():
    store = Store(":memory:")
    aid = add_article(store, "排期测试", "内容")
    sid = add_schedule(store, aid, "2026-08-01T08:00:00")
    assert sid > 0


def test_scan_due_schedules():
    store = Store(":memory:")
    aid = add_article(store, "到期测试", "内容")
    add_schedule(store, aid, "2020-01-01T00:00:00")  # 已过期
    due = scan_due_schedules(store)
    assert len(due) >= 1
    assert due[0]["article_title"] == "到期测试"


def test_scan_due_no_match():
    store = Store(":memory:")
    aid = add_article(store, "未来", "内容")
    add_schedule(store, aid, "2099-01-01T00:00:00")  # 未到期
    due = scan_due_schedules(store)
    assert len(due) == 0


def test_sync_followers():
    store = Store(":memory:")
    followers = [
        {"openid": "o1", "nickname": "张三", "city": "北京", "subscribe": 1},
        {"openid": "o2", "nickname": "李四", "city": "上海", "subscribe": 1},
    ]
    sync_followers(store, followers)
    rows = store.conn.execute("SELECT count(*) as c FROM wechat_followers").fetchone()
    assert rows["c"] == 2
