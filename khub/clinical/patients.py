import time
from ..db import Store
from ..crypto import enc, dec
from ..audit import record

_PII_FIELDS = frozenset({"name", "gender", "born"})

def init(store: Store):
    store.conn.execute("""CREATE TABLE IF NOT EXISTS patients(
        id TEXT PRIMARY KEY, name TEXT, gender TEXT, born TEXT, created_at TEXT)""")
    store.conn.commit()

def add_patient(store, pid, name, gender="", born="") -> str:
    init(store)
    store.conn.execute(
        "INSERT OR REPLACE INTO patients(id, name, gender, born, created_at) VALUES(?,?,?,?,?)",
        (pid, enc(name), enc(gender), enc(born),
         time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())))
    store.conn.commit()
    return pid

def get_patient(store, pid):
    row = store.conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    for field in _PII_FIELDS:
        d[field] = dec(d.get(field, ""))
    record(store, "read_patient", scope="patient", patient_id=pid)
    return d

def list_patients(store):
    rows = store.conn.execute("SELECT * FROM patients ORDER BY id").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        for field in _PII_FIELDS:
            d[field] = dec(d.get(field, ""))
        result.append(d)
    record(store, "list_patients", scope="patient")
    return result
