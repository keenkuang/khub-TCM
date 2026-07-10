import time
from ..db import Store
from ..crypto import enc, dec
from ..audit import record

_PII_FIELDS = frozenset({"name", "gender", "born"})

def init(store: Store):
    store.conn.execute("""CREATE TABLE IF NOT EXISTS patients(
        id TEXT PRIMARY KEY, name TEXT, gender TEXT, born TEXT, created_at TEXT)""")
    # WAL 记账改由 DB 触发器自动完成（仅 Primary 安装）
    from ..replication import install_triggers
    install_triggers(store.conn, "patients", pk="id")
    store.conn.commit()

def add_patient(store, pid, name, gender="", born="") -> str:
    init(store)
    cname, cgender, cborn = enc(name), enc(gender), enc(born)
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    store.conn.execute(
        "INSERT OR REPLACE INTO patients(id, name, gender, born, created_at) VALUES(?,?,?,?,?)",
        (pid, cname, cgender, cborn, now))
    # WAL 触发器已自动记账，无需手动 _replicate
    store.conn.commit()
    return pid

def apply_change(store, op, row_id, payload):
    """备机回放：直写主表、绕过 record_change（不污染 WAL）。"""
    if op == "delete":
        store.conn.execute("DELETE FROM patients WHERE id=?", (row_id,))
        return
    store.conn.execute(
        "INSERT OR REPLACE INTO patients(id, name, gender, born, created_at) "
        "VALUES(?,?,?,?,?)",
        (payload.get("id", row_id), payload.get("name", ""), payload.get("gender", ""),
         payload.get("born", ""), payload.get("created_at", "")))

def get_patient(store, pid):
    row = store.conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    for field in _PII_FIELDS:
        d[field] = dec(d.get(field, ""))
    record(store, "read_patient", scope="patient", patient_id=pid)
    return d

def list_patients(store, user=None):
    from ..auth import scope_filter
    clause, params = scope_filter(user, "patients", alias="")
    sql = "SELECT * FROM patients ORDER BY id"
    if clause:
        sql = f"SELECT * FROM patients WHERE {clause} ORDER BY id"
    rows = store.conn.execute(sql, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        for field in _PII_FIELDS:
            d[field] = dec(d.get(field, ""))
        result.append(d)
    record(store, "list_patients", scope="patient")
    return result
