import time
from ..db import Store
from ..crypto import enc, dec
from ..audit import record

_PII_FIELDS = frozenset({"chief_complaint", "tongue_pulse", "differentiation", "plan"})

def init(store: Store):
    store.conn.execute("""CREATE TABLE IF NOT EXISTS consultations(
        id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT, date TEXT,
        chief_complaint TEXT, tongue_pulse TEXT, differentiation TEXT, plan TEXT,
        created_at TEXT)""")
    store.conn.commit()

def add_consultation(store, patient_id, chief_complaint="", tongue_pulse="",
                     differentiation="", plan="", date=None) -> int:
    init(store)
    d = date or time.strftime("%Y-%m-%d", time.gmtime())
    cur = store.conn.execute(
        "INSERT INTO consultations(patient_id, date, chief_complaint, tongue_pulse, "
        "differentiation, plan, created_at) VALUES(?,?,?,?,?,?,?)",
        (patient_id, d, enc(chief_complaint), enc(tongue_pulse),
         enc(differentiation), enc(plan),
         time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())))
    store.conn.commit()
    return cur.lastrowid

def list_consultations(store, patient_id):
    rows = store.conn.execute(
        "SELECT * FROM consultations WHERE patient_id=? ORDER BY id", (patient_id,)).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        for field in _PII_FIELDS:
            d[field] = dec(d.get(field, ""))
        result.append(d)
    record(store, "read_consultations", scope="consultation", patient_id=patient_id)
    return result
