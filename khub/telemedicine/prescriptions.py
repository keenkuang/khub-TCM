"""电子处方 CRUD。"""
from __future__ import annotations
import json
from ..db import Store


def create_prescription(
    store: Store, consultation_id: int, doctor_id: int,
    patient_id: int, items: list[dict]
) -> int:
    store.conn.execute(
        "INSERT INTO prescriptions (consultation_id, doctor_id, patient_id, items) "
        "VALUES (?, ?, ?, ?)",
        (consultation_id, doctor_id, patient_id,
         json.dumps(items, ensure_ascii=False)))
    return store.conn.execute(
        "SELECT last_insert_rowid()").fetchone()[0]


def get_prescription(store: Store, pid: int) -> dict | None:
    row = store.conn.execute(
        "SELECT * FROM prescriptions WHERE id=?", (pid,)).fetchone()
    if row is None:
        return None
    result = dict(row)
    if result.get("items"):
        result["items"] = json.loads(result["items"])
    return result


def list_prescriptions(store: Store, patient_id: int = 0) -> list[dict]:
    if patient_id:
        rows = store.conn.execute(
            "SELECT * FROM prescriptions WHERE patient_id=? ORDER BY id DESC",
            (patient_id,)).fetchall()
    else:
        rows = store.conn.execute(
            "SELECT * FROM prescriptions ORDER BY id DESC LIMIT 50").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("items"):
            d["items"] = json.loads(d["items"])
        result.append(d)
    return result
