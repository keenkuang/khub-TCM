import time
from ..db import Store

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
        (patient_id, vd, diagnosis, prescription, note,
         time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())))
    store.conn.commit()
    return cur.lastrowid

def list_records(store, patient_id):
    rows = store.conn.execute(
        "SELECT * FROM records WHERE patient_id=? ORDER BY id", (patient_id,)).fetchall()
    return [dict(r) for r in rows]
