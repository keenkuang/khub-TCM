import time
from ..db import Store
from ..crypto import enc, dec
from ..audit import record

_PII_FIELDS = frozenset({"diagnosis", "prescription", "note"})

def init(store: Store):
    store.conn.execute("""CREATE TABLE IF NOT EXISTS records(
        id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT, visit_date TEXT,
        diagnosis TEXT, prescription TEXT, note TEXT, created_at TEXT)""")
    store.conn.commit()

def add_record(store, patient_id, diagnosis="", prescription="", note="", visit_date=None) -> int:
    init(store)
    vd = visit_date or time.strftime("%Y-%m-%d", time.gmtime())
    cur = store.conn.execute(
        "INSERT INTO records(patient_id, visit_date, diagnosis, prescription, note, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (patient_id, vd, enc(diagnosis), enc(prescription), enc(note),
         time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())))
    store.conn.commit()
    return cur.lastrowid

def list_records(store, patient_id):
    rows = store.conn.execute(
        "SELECT * FROM records WHERE patient_id=? ORDER BY id", (patient_id,)).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        for field in _PII_FIELDS:
            d[field] = dec(d.get(field, ""))
        result.append(d)
    record(store, "read_records", scope="record", patient_id=patient_id)
    return result
