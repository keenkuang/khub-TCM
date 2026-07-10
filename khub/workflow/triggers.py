"""Webhook 事件自动触发工作流。"""
from __future__ import annotations
import json
from ..db import Store
from .store import create_instance
from .engine import run as run_engine


def on_event(store: Store, event: str, entity_type: str = "", entity_id: str = "", context: dict | None = None):
    """事件触发：查找匹配的 workflow definitions 并启动实例。"""
    definitions = store.conn.execute(
        "SELECT id, name, steps FROM workflow_definitions WHERE active=1").fetchall()
    for d in definitions:
        steps = json.loads(d["steps"]) if isinstance(d["steps"], str) else d["steps"]
        for step in steps:
            if step.get("type") == "trigger" and step.get("config", {}).get("event") == event:
                iid = create_instance(store, d["id"], entity_type=entity_type, entity_id=entity_id, context=context)
                run_engine(store, iid)
                break
