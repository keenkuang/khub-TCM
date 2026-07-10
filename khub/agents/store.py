"""Agent 定义 CRUD。"""
from __future__ import annotations
import json
from ..db import Store


def create_agent(store: Store, name: str, system_prompt: str = "",
                 tools: list[str] | None = None, description: str = "",
                 schedule: str = "") -> int:
    store.conn.execute(
        "INSERT INTO agent_definitions (name, description, system_prompt, tools, schedule) VALUES (?, ?, ?, ?, ?)",
        (name, description, system_prompt, json.dumps(tools or []), schedule))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def list_agents(store: Store) -> list[dict]:
    return store.conn.execute("SELECT * FROM agent_definitions ORDER BY id DESC").fetchall()


def get_agent(store: Store, aid: int) -> dict | None:
    return store.conn.execute("SELECT * FROM agent_definitions WHERE id=?", (aid,)).fetchone()


def update_agent(store: Store, aid: int, **kw):
    updates = {k: v for k, v in kw.items() if v is not None}
    if not updates:
        return
    if "tools" in updates and isinstance(updates["tools"], list):
        updates["tools"] = json.dumps(updates["tools"])
    set_clause = ", ".join(f"{k}=?" for k in updates)
    store.conn.execute(f"UPDATE agent_definitions SET {set_clause} WHERE id=?", (*updates.values(), aid))
