"""微信公众号CRUD——文章/排期/粉丝管理。"""
from __future__ import annotations
import json

from ..db import Store


def init(store: Store):
    """确保微信业务表已创建（幂等——表已在 _init_schema 中创建）。"""
    pass


def add_article(store: Store, title: str, content: str,
                author: str = "", digest: str = "",
                content_source_url: str = "", doc_id: str = "") -> int:
    store.conn.execute(
        "INSERT INTO wechat_articles (title, author, digest, content, content_source_url, doc_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (title, author, digest, content, content_source_url, doc_id))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def list_articles(store: Store, status: str | None = None) -> list[dict]:
    if status:
        return store.conn.execute(
            "SELECT * FROM wechat_articles WHERE status=? ORDER BY id DESC", (status,)).fetchall()
    return store.conn.execute("SELECT * FROM wechat_articles ORDER BY id DESC").fetchall()


def get_article(store: Store, aid: int) -> dict | None:
    return store.conn.execute("SELECT * FROM wechat_articles WHERE id=?", (aid,)).fetchone()


def add_schedule(store: Store, article_id: int, publish_at: str, tag_id: int = 0) -> int:
    store.conn.execute(
        "INSERT INTO wechat_schedules (article_id, publish_at, tag_id) VALUES (?, ?, ?)",
        (article_id, publish_at, tag_id))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def scan_due_schedules(store: Store) -> list[dict]:
    """扫描到期未发布的排期。"""
    return store.conn.execute(
        "SELECT s.*, a.title as article_title, a.content, a.thumb_media_id "
        "FROM wechat_schedules s JOIN wechat_articles a ON s.article_id=a.id "
        "WHERE s.status='pending' AND s.publish_at <= datetime('now') "
        "ORDER BY s.publish_at ASC").fetchall()


def update_schedule_status(store: Store, sid: int, status: str, error_msg: str = ""):
    store.conn.execute(
        "UPDATE wechat_schedules SET status=?, error_msg=? WHERE id=?",
        (status, error_msg, sid))


def update_article_status(store: Store, aid: int, status: str,
                          wechat_media_id: str = "", wechat_url: str = ""):
    store.conn.execute(
        "UPDATE wechat_articles SET status=?, wechat_media_id=?, wechat_url=? WHERE id=?",
        (status, wechat_media_id, wechat_url, aid))


def sync_followers(store: Store, followers: list[dict]):
    """同步粉丝数据（upsert）。"""
    for f in followers:
        store.conn.execute(
            "INSERT OR REPLACE INTO wechat_followers "
            "(openid, subscribe, nickname, sex, city, province, country, "
            " headimgurl, subscribe_time, tagid_list, subscribe_scene) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f.get("openid", ""), f.get("subscribe", 1),
             f.get("nickname", ""), f.get("sex", 0),
             f.get("city", ""), f.get("province", ""), f.get("country", ""),
             f.get("headimgurl", ""), f.get("subscribe_time", ""),
             json.dumps(f.get("tagid_list", [])), f.get("subscribe_scene", "")))
