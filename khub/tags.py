"""0.2.9 标签系统 CRUD。"""
from __future__ import annotations
from .db import Store


def add_tag(store: Store, doc_id: str, tag: str):
    store.conn.execute(
        "INSERT OR IGNORE INTO doc_tags (doc_id, tag) VALUES (?, ?)",
        (doc_id, tag.strip()))


def remove_tag(store: Store, doc_id: str, tag: str):
    store.conn.execute(
        "DELETE FROM doc_tags WHERE doc_id=? AND tag=?", (doc_id, tag))


def list_tags(store: Store) -> list[dict]:
    return store.conn.execute(
        "SELECT tag, count(*) as count FROM doc_tags GROUP BY tag ORDER BY count DESC"
    ).fetchall()


def get_doc_tags(store: Store, doc_id: str) -> list[str]:
    rows = store.conn.execute(
        "SELECT tag FROM doc_tags WHERE doc_id=?", (doc_id,)).fetchall()
    return [r["tag"] for r in rows]
