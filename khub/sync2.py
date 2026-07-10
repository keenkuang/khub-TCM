"""离线同步引擎——变更日志 + 推送/拉取/冲突合并。"""
from __future__ import annotations
import json

from .db import Store


def record_change(store: Store, entity_type: str, entity_id: str, action: str, data: dict, client_id: str = "server"):
    """记录数据变更。"""
    store.conn.execute(
        "INSERT INTO sync_changes (entity_type, entity_id, action, data, client_id) VALUES (?, ?, ?, ?, ?)",
        (entity_type, entity_id, action, json.dumps(data, ensure_ascii=False), client_id))


def push(store: Store, client_id: str, changes: list[dict]) -> dict:
    """客户端推送变更到服务器。返回处理结果。"""
    device = store.conn.execute("SELECT * FROM devices WHERE client_id=?", (client_id,)).fetchone()
    if not device:
        store.conn.execute("INSERT INTO devices (client_id) VALUES (?)", (client_id,))
    applied = 0
    conflicts = []
    for ch in changes:
        existing = store.conn.execute(
            "SELECT version FROM sync_changes WHERE entity_type=? AND entity_id=? ORDER BY version DESC LIMIT 1",
            (ch.get("entity_type",""), ch.get("entity_id",""))).fetchone()
        if existing and ch.get("version", 0) < existing["version"]:
            conflicts.append({"entity": ch.get("entity_id",""), "server_version": existing["version"], "client_version": ch.get("version",0)})
        else:
            record_change(store, ch.get("entity_type",""), ch.get("entity_id",""), ch.get("action","update"), ch.get("data",{}), client_id)
            applied += 1
    store.conn.execute("UPDATE devices SET last_sync_at=datetime('now'), last_version=last_version+? WHERE client_id=?", (applied, client_id))
    return {"applied": applied, "conflicts": conflicts}


def pull(store: Store, client_id: str, since_version: int = 0) -> dict:
    """客户端拉取服务器变更。"""
    changes = store.conn.execute(
        "SELECT * FROM sync_changes WHERE id > ? ORDER BY id ASC LIMIT 1000",
        (since_version,)).fetchall()
    device = store.conn.execute("SELECT * FROM devices WHERE client_id=?", (client_id,)).fetchone()
    latest_version = device["last_version"] if device else 0
    return {"changes": [dict(c) for c in changes], "latest_version": latest_version}


def status(store: Store) -> dict:
    """同步状态概要。"""
    total = store.conn.execute("SELECT count(*) as c FROM sync_changes").fetchone()["c"]
    devices = store.conn.execute("SELECT client_id, name, last_sync_at FROM devices").fetchall()
    return {"total_changes": total, "devices": [dict(d) for d in devices]}
