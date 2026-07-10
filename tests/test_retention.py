"""数据保留策略引擎测试。"""
from datetime import datetime, timedelta
from khub.db import Store
from khub.retention import clean


def test_retention_clean():
    store = Store(":memory:")
    # 插入一条旧通知
    store.conn.execute(
        "INSERT INTO notifications (user_id, title, created_at) VALUES (1, '旧通知', '2020-01-01')"
    )
    store.conn.execute(
        "INSERT INTO notifications (user_id, title, created_at) VALUES (1, '新通知', datetime('now'))"
    )
    result = clean(store, table="notifications")
    assert result.get("notifications", 0) >= 1


def test_retention_dry_run():
    store = Store(":memory:")
    store.conn.execute(
        "INSERT INTO notifications (user_id, title, created_at) VALUES (1, '旧', '2020-01-01')"
    )
    result = clean(store, table="notifications", dry_run=True)
    assert result.get("notifications", 0) >= 1
    # dry run 不应该实际删除
    remaining = store.conn.execute(
        "SELECT count(*) as c FROM notifications"
    ).fetchone()["c"]
    assert remaining >= 1
