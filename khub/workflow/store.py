"""工作流定义与实例的 CRUD。"""
from __future__ import annotations
import json
from ..db import Store


def create_definition(store: Store, name: str, steps: list[dict],
                      description: str = "") -> int:
    store.conn.execute("INSERT INTO workflow_definitions (name, description, steps) VALUES (?, ?, ?)",
                       (name, description, json.dumps(steps, ensure_ascii=False)))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def list_definitions(store: Store) -> list[dict]:
    return [dict(r) for r in store.conn.execute("SELECT * FROM workflow_definitions ORDER BY id DESC").fetchall()]


def get_definition(store: Store, did: int) -> dict | None:
    row = store.conn.execute("SELECT * FROM workflow_definitions WHERE id=?", (did,)).fetchone()
    if not row:
        return None
    row = dict(row)
    if isinstance(row.get("steps"), str):
        row["steps"] = json.loads(row["steps"])
    return row


def create_instance(store: Store, definition_id: int, entity_type: str = "",
                    entity_id: str = "", context: dict | None = None) -> int:
    definition = get_definition(store, definition_id)
    if not definition: raise ValueError("定义不存在")
    steps = definition["steps"]
    first_step = steps[0]["name"] if steps else ""
    store.conn.execute(
        "INSERT INTO workflow_instances (definition_id, entity_type, entity_id, current_step, context) "
        "VALUES (?, ?, ?, ?, ?)",
        (definition_id, entity_type, entity_id,
         first_step, json.dumps(context or {}, ensure_ascii=False)))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def get_instance(store: Store, iid: int) -> dict | None:
    row = store.conn.execute("SELECT * FROM workflow_instances WHERE id=?", (iid,)).fetchone()
    return dict(row) if row else None


def list_instances(store: Store, status: str = "") -> list[dict]:
    if status:
        return [dict(r) for r in store.conn.execute("SELECT * FROM workflow_instances WHERE status=? ORDER BY id DESC", (status,)).fetchall()]
    return [dict(r) for r in store.conn.execute("SELECT * FROM workflow_instances ORDER BY id DESC").fetchall()]
