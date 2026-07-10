"""Webhook 事件推送系统。"""
from __future__ import annotations
import hashlib
import hmac
import json
import logging
import os
import threading
import time
import urllib.request
import urllib.error
from .db import Store

logger = logging.getLogger("khub.webhook")
_EVENTS = ["document.created", "appointment.created", "consultation.created",
           "followup.due", "course.enrolled", "record.created"]


def subscribe(store: Store, event: str, url: str, secret: str = "") -> int:
    if event not in _EVENTS:
        raise ValueError(f"不支持的事件类型: {event}，支持: {','.join(_EVENTS)}")
    store.conn.execute(
        "INSERT INTO webhook_subscriptions (event, url, secret) VALUES (?, ?, ?)",
        (event, url, secret))
    store.conn.commit()
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def unsubscribe(store: Store, sub_id: int):
    store.conn.execute("DELETE FROM webhook_subscriptions WHERE id=?", (sub_id,))
    store.conn.commit()


def list_subscriptions(store: Store) -> list[dict]:
    rows = store.conn.execute(
        "SELECT * FROM webhook_subscriptions ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def trigger(event: str, payload: dict, store: Store | None = None):
    """触发事件（异步投递到所有订阅者 + 通知 + SSE 广播）。

    Args:
        event: 事件类型名称
        payload: 事件负载
        store: Store 实例。如为 None，在投递线程中自动打开独立连接。
    """
    threading.Thread(target=_deliver, args=(event, payload, store),
                     daemon=True).start()
    # 0.6.1 通知 + SSE 广播
    if store is not None:
        from .notifications import create as _create_notification
        try:
            _create_notification(store, 0, f"事件: {event}",
                                 json.dumps(payload, ensure_ascii=False),
                                 event_type=event)
        except Exception:
            pass
    from .events import broadcast as _broadcast
    _broadcast(event, payload)


def _sign_payload(payload: bytes, secret: str) -> str:
    """用 HMAC-SHA256 对负载签名。"""
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _deliver(event: str, payload: dict, store: Store | None):
    """向所有订阅了该事件的 Webhook URL 投递负载。"""
    db_path = None
    close_store = False
    if store is None:
        db_path = os.environ.get("KHUB_DB", os.path.expanduser("~/.khub/khub.db"))
        if os.path.isfile(db_path):
            try:
                store = Store(db_path)
                close_store = True
            except Exception as e:
                logger.warning("Webhook 无法打开 Store(%s): %s", db_path, e)
                return
        else:
            logger.info("Webhook 事件: %s (无 DB，跳过投递)", event)
            return

    try:
        subs = store.conn.execute(
            "SELECT * FROM webhook_subscriptions WHERE event=? AND active=1",
            (event,)).fetchall()
    except Exception as e:
        logger.warning("Webhook 查询订阅失败: %s", e)
        if close_store:
            store.conn.close()
        return

    for sub in subs:
        sub_id = sub["id"]
        url = sub["url"]
        secret = sub.get("secret") or ""
        body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Event": event,
            "X-Webhook-Signature": _sign_payload(body_bytes, secret),
        }
        req = urllib.request.Request(url, data=body_bytes, headers=headers,
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp_body = resp.read().decode("utf-8", errors="replace")
                status_code = resp.status
                logger.info("Webhook 投递成功: sub=%d %s -> %d", sub_id, url, status_code)
        except urllib.error.HTTPError as e:
            resp_body = e.read().decode("utf-8", errors="replace")
            status_code = e.code
            logger.warning("Webhook 投递 HTTP %d: sub=%d %s", status_code, sub_id, url)
        except Exception as e:
            resp_body = str(e)
            status_code = 0
            logger.warning("Webhook 投递失败: sub=%d %s: %s", sub_id, url, e)

        # 记录投递结果到 webhook_deliveries
        try:
            store.conn.execute(
                "INSERT INTO webhook_deliveries "
                "(subscription_id, event, payload, status, response_code, response_body) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sub_id, event, json.dumps(payload, ensure_ascii=False),
                 "success" if 200 <= status_code < 300 else "failed",
                 status_code, resp_body[:1000]))
            store.conn.commit()
        except Exception as e:
            logger.warning("Webhook 投递记录写入失败: %s", e)

    if close_store:
        store.conn.close()
