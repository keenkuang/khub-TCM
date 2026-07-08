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
    from ..replication import install_triggers
    install_triggers(store.conn, "consultations", pk="id")
    store.conn.commit()

def add_consultation(store, patient_id, chief_complaint="", tongue_pulse="",
                     differentiation="", plan="", date=None) -> int:
    init(store)
    d = date or time.strftime("%Y-%m-%d", time.gmtime())
    ccc, ctp, cdiff, cplan = (enc(chief_complaint), enc(tongue_pulse),
                               enc(differentiation), enc(plan))
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    cur = store.conn.execute(
        "INSERT INTO consultations(patient_id, date, chief_complaint, tongue_pulse, "
        "differentiation, plan, created_at) VALUES(?,?,?,?,?,?,?)",
        (patient_id, d, ccc, ctp, cdiff, cplan, now))
    cid = cur.lastrowid
    # WAL 触发器已自动记账
    store.conn.commit()
    return cid

def apply_change(store, op, row_id, payload):
    """备机回放：直写主表、绕过 record_change。"""
    if op == "delete":
        store.conn.execute("DELETE FROM consultations WHERE id=?", (row_id,))
        return
    store.conn.execute(
        "INSERT OR REPLACE INTO consultations(id, patient_id, date, chief_complaint, "
        "tongue_pulse, differentiation, plan, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (payload.get("id", row_id), payload.get("patient_id", ""),
         payload.get("date", ""), payload.get("chief_complaint", ""),
         payload.get("tongue_pulse", ""), payload.get("differentiation", ""),
         payload.get("plan", ""), payload.get("created_at", "")))

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
