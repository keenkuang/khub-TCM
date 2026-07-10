"""通知系统——创建/列表/未读数/标记已读。"""
from __future__ import annotations
from .db import Store


def create(store: Store, user_id: int, title: str, body: str = "",
           event_type: str = "", resource_type: str = "",
           resource_id: str = "") -> int:
    store.conn.execute(
        "INSERT INTO notifications (user_id, title, body, event_type, resource_type, resource_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id or None, title, body, event_type, resource_type, resource_id))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def list_recent(store: Store, user_id: int, limit: int = 20) -> list[dict]:
    return store.conn.execute(
        "SELECT * FROM notifications WHERE user_id=? OR user_id IS NULL "
        "ORDER BY created_at DESC LIMIT ?", (user_id, limit)).fetchall()


def unread_count(store: Store, user_id: int) -> int:
    row = store.conn.execute(
        "SELECT count(*) as c FROM notifications WHERE (user_id=? OR user_id IS NULL) AND read=0",
        (user_id,)).fetchone()
    return row["c"] if row else 0


def mark_read(store: Store, notification_id: int, user_id: int):
    store.conn.execute(
        "UPDATE notifications SET read=1 WHERE id=? AND (user_id=? OR user_id IS NULL)",
        (notification_id, user_id))


def mark_all_read(store: Store, user_id: int):
    store.conn.execute(
        "UPDATE notifications SET read=1 WHERE (user_id=? OR user_id IS NULL) AND read=0",
        (user_id,))
