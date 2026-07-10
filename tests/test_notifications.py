import pytest
pytestmark = pytest.mark.smoke

import pytest
from khub.db import Store
from khub.notifications import create, list_recent, unread_count, mark_read, mark_all_read


def test_create():
    store = Store(":memory:")
    nid = create(store, 1, "新预约", "张医生 2026-08-01", event_type="appointment.created")
    assert nid > 0


def test_list_recent():
    store = Store(":memory:")
    create(store, 1, "通知A", ""); create(store, 1, "通知B", "")
    assert len(list_recent(store, 1)) >= 2


def test_unread_count():
    store = Store(":memory:")
    create(store, 1, "未读通知", "")
    assert unread_count(store, 1) >= 1


def test_mark_read():
    store = Store(":memory:")
    nid = create(store, 1, "标记已读", "")
    mark_read(store, nid, 1)
    notifs = list_recent(store, 1)
    for n in notifs:
        if n["id"] == nid:
            assert n["read"] == 1


def test_mark_all_read():
    store = Store(":memory:")
    create(store, 1, "通知1", ""); create(store, 1, "通知2", "")
    mark_all_read(store, 1)
    assert unread_count(store, 1) == 0


def test_broadcast_no_side_effects():
    from khub.events import broadcast
    broadcast("test.event", {"msg": "hello"})  # 不应抛出异常
