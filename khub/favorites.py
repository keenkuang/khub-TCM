"""0.2.9 收藏/书签系统。"""
from __future__ import annotations
from .db import Store


def toggle_favorite(store: Store, doc_id: str) -> bool:
    row = store.conn.execute(
        "SELECT id FROM favorites WHERE doc_id=?", (doc_id,)).fetchone()
    if row:
        store.conn.execute("DELETE FROM favorites WHERE doc_id=?", (doc_id,))
        return False  # 取消收藏
    else:
        store.conn.execute("INSERT INTO favorites (doc_id) VALUES (?)", (doc_id,))
        return True   # 收藏


def list_favorites(store: Store) -> list[dict]:
    return store.conn.execute(
        "SELECT f.doc_id, d.title, f.created_at FROM favorites f "
        "LEFT JOIN documents d ON f.doc_id=d.canonical_id "
        "ORDER BY f.created_at DESC"
    ).fetchall()


def is_favorite(store: Store, doc_id: str) -> bool:
    return store.conn.execute(
        "SELECT 1 FROM favorites WHERE doc_id=?", (doc_id,)).fetchone() is not None
