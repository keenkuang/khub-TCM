"""诊所计费——费用项 + 收费 + 发票。"""
from __future__ import annotations
import json
from ..db import Store


def create_billing(store: Store, appointment_id: int, patient_id: int,
                   items: list[dict], method: str = "") -> int:
    total = sum(item.get("price", 0) * item.get("qty", 1) for item in items)
    store.conn.execute(
        "INSERT INTO billings (appointment_id, patient_id, items, total, method) VALUES (?, ?, ?, ?, ?)",
        (appointment_id, patient_id, json.dumps(items), total, method))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def list_billings(store: Store, patient_id: int = 0) -> list[dict]:
    if patient_id:
        return store.conn.execute("SELECT * FROM billings WHERE patient_id=? ORDER BY id DESC", (patient_id,)).fetchall()
    return store.conn.execute("SELECT * FROM billings ORDER BY id DESC LIMIT 50").fetchall()


def pay(store: Store, billing_id: int, amount: float, method: str = "cash"):
    store.conn.execute("UPDATE billings SET paid=?, method=?, status='paid' WHERE id=?", (amount, method, billing_id))
