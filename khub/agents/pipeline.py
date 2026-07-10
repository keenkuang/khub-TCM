"""多 Agent 协作管线——链式执行。"""
from __future__ import annotations
import json
from ..db import Store
from .store import get_agent
from .engine import run_with_llm


def create_pipeline(store: Store, name: str, agent_ids: list[int], description: str = "") -> int:
    store.conn.execute(
        "INSERT INTO agent_pipelines (name, agent_ids, description) VALUES (?, ?, ?)",
        (name, json.dumps(agent_ids), description))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def list_pipelines(store: Store) -> list[dict]:
    return store.conn.execute("SELECT * FROM agent_pipelines ORDER BY id DESC").fetchall()


def run(store: Store, pipeline_id: int, input_text: str = "",
        current_user: dict | None = None) -> list[dict]:
    pipe = store.conn.execute("SELECT * FROM agent_pipelines WHERE id=?", (pipeline_id,)).fetchone()
    if not pipe: raise ValueError("管线不存在")
    agent_ids = json.loads(pipe["agent_ids"]) if isinstance(pipe["agent_ids"], str) else pipe["agent_ids"]
    results = []
    prev_output = input_text
    for aid in agent_ids:
        agent = get_agent(store, aid)
        if not agent:
            results.append({"agent_id": aid, "error": "not found"})
            continue
        result = run_with_llm(store, aid, user_input=prev_output, current_user=current_user)
        prev_output = result.get("reply", "")
        results.append({"agent_id": aid, "agent_name": agent["name"], "output": prev_output})
    return results
