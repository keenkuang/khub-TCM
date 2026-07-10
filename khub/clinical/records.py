import time
from ..db import Store
from ..crypto import enc, dec
from ..audit import record

_PII_FIELDS = frozenset({"diagnosis", "prescription", "note"})

def init(store: Store):
    store.conn.execute("""CREATE TABLE IF NOT EXISTS records(
        id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT, visit_date TEXT,
        diagnosis TEXT, prescription TEXT, note TEXT, created_at TEXT)""")
    from ..replication import install_triggers
    install_triggers(store.conn, "records", pk="id")
    store.conn.commit()

def add_record(store, patient_id, diagnosis="", prescription="", note="", visit_date=None) -> int:
    init(store)
    vd = visit_date or time.strftime("%Y-%m-%d", time.gmtime())
    cdiag, cprsc, cnote = enc(diagnosis), enc(prescription), enc(note)
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    cur = store.conn.execute(
        "INSERT INTO records(patient_id, visit_date, diagnosis, prescription, note, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (patient_id, vd, cdiag, cprsc, cnote, now))
    rid = cur.lastrowid
    # WAL 触发器已自动记账
    store.conn.commit()
    return rid

def apply_change(store, op, row_id, payload):
    """备机回放：直写主表、绕过 record_change。"""
    if op == "delete":
        store.conn.execute("DELETE FROM records WHERE id=?", (row_id,))
        return
    store.conn.execute(
        "INSERT OR REPLACE INTO records(id, patient_id, visit_date, diagnosis, "
        "prescription, note, created_at) VALUES(?,?,?,?,?,?,?)",
        (payload.get("id", row_id), payload.get("patient_id", ""), payload.get("visit_date", ""),
         payload.get("diagnosis", ""), payload.get("prescription", ""),
         payload.get("note", ""), payload.get("created_at", "")))

def list_records(store, patient_id=None, user=None):
    from ..auth import scope_filter
    clause, params = scope_filter(user, "records")
    sql = "SELECT * FROM records"
    conditions = []
    if patient_id:
        conditions.append("patient_id=?")
        params = [patient_id] + (params or [])
    if clause:
        conditions.append(clause)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY id"
    rows = store.conn.execute(sql, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        for field in _PII_FIELDS:
            d[field] = dec(d.get(field, ""))
        result.append(d)
    record(store, "read_records", scope="record", patient_id=patient_id or "")
    return result
