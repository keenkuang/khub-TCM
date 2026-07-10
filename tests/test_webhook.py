"""0.6.0 Webhook 系统测试。"""
import pytest
from khub.db import Store
from khub.webhook import subscribe, unsubscribe, list_subscriptions


def test_subscribe():
    """基本的 Webhook 订阅和列出功能。"""
    store = Store(":memory:")
    sid = subscribe(store, "document.created",
                    "http://hook.example.com", secret="s3cr3t")
    assert sid > 0
    subs = list_subscriptions(store)
    assert len(subs) == 1
    assert subs[0]["event"] == "document.created"
    assert subs[0]["url"] == "http://hook.example.com"
    assert subs[0]["secret"] == "s3cr3t"
    assert subs[0]["active"] == 1


def test_subscribe_invalid_event():
    """不合法的事件类型应抛出 ValueError。"""
    store = Store(":memory:")
    with pytest.raises(ValueError, match="不支持"):
        subscribe(store, "invalid.event", "http://x.com")


def test_unsubscribe():
    """取消订阅后列表应为空。"""
    store = Store(":memory:")
    sid = subscribe(store, "appointment.created", "http://x.com")
    unsubscribe(store, sid)
    assert len(list_subscriptions(store)) == 0


def test_multiple_subscriptions():
    """多个订阅应全部列出。"""
    store = Store(":memory:")
    s1 = subscribe(store, "document.created", "http://a.com")
    s2 = subscribe(store, "appointment.created", "http://b.com")
    s3 = subscribe(store, "consultation.created", "http://c.com")
    subs = list_subscriptions(store)
    assert len(subs) == 3
    events = {s["event"] for s in subs}
    assert events == {"document.created", "appointment.created",
                       "consultation.created"}


def test_subscribe_default_secret():
    """secret 参数默认为空字符串。"""
    store = Store(":memory:")
    sid = subscribe(store, "record.created", "http://x.com")
    subs = list_subscriptions(store)
    assert subs[0]["secret"] == ""


def test_all_event_types():
    """所有预定义事件类型均可订阅。"""
    store = Store(":memory:")
    events = ["document.created", "appointment.created",
              "consultation.created", "followup.due",
              "course.enrolled", "record.created"]
    for event in events:
        sid = subscribe(store, event, f"http://{event}.com")
        assert sid > 0
    assert len(list_subscriptions(store)) == 6
