"""0.2.7 随访与复诊管理——计划/扫描 due/依从性记录。"""
from __future__ import annotations

from datetime import date

from ..audit import record as _record
from ..db import Store


def add_plan(store: Store, pid: int, due_date: str, reason: str = "") -> int:
    store.conn.execute(
        "INSERT INTO followup_plans (patient_id, due_date, reason) VALUES (?, ?, ?)",
        (pid, due_date, reason),
    )
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def list_plans(store: Store, patient_id: int = 0) -> list[dict]:
    """按患者列出随访计划。"""
    sql = "SELECT id, patient_id, due_date, reason, status FROM followup_plans"
    params: list = []
    if patient_id:
        sql += " WHERE patient_id=?"
        params.append(patient_id)
    return [dict(r) for r in store.conn.execute(sql + " ORDER BY due_date", params).fetchall()]


def scan_due(store: Store, as_of: str | None = None, auto_book: bool = False) -> list[dict]:
    if as_of is None:
        as_of = str(date.today())
    rows = store.conn.execute(
        "SELECT id, patient_id, due_date, reason, status FROM followup_plans "
        "WHERE due_date <= ? AND status = 'active'",
        (as_of,),
    ).fetchall()
    due = []
    for r in rows:
        entry = dict(r)
        store.conn.execute(
            "UPDATE followup_plans SET status='due' WHERE id=?", (r["id"],),
        )
        entry["status"] = "due"
        if auto_book:
            try:
                from ..ops.store import book_appointment

                book_appointment(
                    store, r["patient_id"], r["due_date"], doctor="随访",
                )
                entry["appointment_booked"] = True
            except Exception:
                entry["appointment_booked"] = False
        due.append(entry)
    return due


def record_adherence(store: Store, plan_id: int, attended: bool, note: str = ""):
    store.conn.execute(
        "INSERT INTO followup_adherence (plan_id, attended, note) VALUES (?, ?, ?)",
        (plan_id, 1 if attended else 0, note),
    )
    store.conn.execute(
        "UPDATE followup_plans SET status='done' WHERE id=?", (plan_id,),
    )
    _record(store, "followup", scope=f"plan={plan_id}")
