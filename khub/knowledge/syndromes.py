"""证型 CRUD + 八纲分类。"""
from ..db import Store

def add_syndrome(store, name: str, category: str = "", parent_id: int = 0, symptoms: list | None = None, **kw) -> int:
    import json
    store.conn.execute("INSERT INTO kg_syndromes (name, parent_id, category, symptoms, tongue, tongue_pulse, treatment_principle) VALUES (?,?,?,?,?,?,?)",
                       (name, parent_id or None, category, json.dumps(symptoms or [], ensure_ascii=False), kw.get("tongue",""), kw.get("tongue_pulse",""), kw.get("treatment_principle","")))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

def get_syndrome(store, name: str) -> dict | None:
    return store.conn.execute("SELECT * FROM kg_syndromes WHERE name=?", (name,)).fetchone()

def list_syndromes(store, category: str = "") -> list[dict]:
    if category: return store.conn.execute("SELECT * FROM kg_syndromes WHERE category=? ORDER BY name", (category,)).fetchall()
    return store.conn.execute("SELECT * FROM kg_syndromes ORDER BY name").fetchall()
