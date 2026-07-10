"""社区文章 CRUD。"""
from __future__ import annotations
import json
from ..db import Store


def create_article(store: Store, title: str, content: str, author_id: int = 0,
                   tags: list[str] | None = None, is_public: bool = True) -> int:
    store.conn.execute(
        "INSERT INTO community_articles (title, content, author_id, tags, is_public) VALUES (?, ?, ?, ?, ?)",
        (title, content, author_id, json.dumps(tags or []), 1 if is_public else 0))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def list_articles(store: Store, tag: str = "", is_public: bool = True) -> list[dict]:
    sql = "SELECT * FROM community_articles WHERE status='published' AND is_public=?"
    params = [1 if is_public else 0]
    if tag:
        sql += " AND tags LIKE ?"
        params.append(f"%{tag}%")
    return store.conn.execute(sql + " ORDER BY id DESC LIMIT 50", params).fetchall()


def get_article(store: Store, aid: int) -> dict | None:
    store.conn.execute("UPDATE community_articles SET view_count=view_count+1 WHERE id=?", (aid,))
    return store.conn.execute("SELECT * FROM community_articles WHERE id=?", (aid,)).fetchone()


def list_tags(store: Store) -> list[str]:
    rows = store.conn.execute("SELECT DISTINCT tags FROM community_articles WHERE status='published'").fetchall()
    tags: set[str] = set()
    for r in rows:
        for t in (json.loads(r["tags"]) if isinstance(r["tags"], str) else (r["tags"] or [])):
            tags.add(t)
    return sorted(tags)
