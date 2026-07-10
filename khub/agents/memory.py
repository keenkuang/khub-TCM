"""Agent 记忆系统——键值存储 + 检索。"""
from __future__ import annotations
from ..db import Store


def store(store: Store, agent_id: int, key: str, value: str, type: str = "string"):
    store.conn.execute(
        "INSERT OR REPLACE INTO agent_memory (agent_id, key, value, type) VALUES (?, ?, ?, ?)",
        (agent_id, key, value, type))


def recall(store: Store, agent_id: int, key: str) -> str | None:
    row = store.conn.execute(
        "SELECT value FROM agent_memory WHERE agent_id=? AND key=?", (agent_id, key)).fetchone()
    return row["value"] if row else None


def list_memory(store: Store, agent_id: int) -> list[dict]:
    return store.conn.execute(
        "SELECT key, value, type, created_at FROM agent_memory WHERE agent_id=? ORDER BY created_at DESC",
        (agent_id,)).fetchall()


def delete(store: Store, agent_id: int, key: str):
    store.conn.execute("DELETE FROM agent_memory WHERE agent_id=? AND key=?", (agent_id, key))
