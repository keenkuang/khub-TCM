import time
from ..db import Store

def init(store: Store):
    store.conn.execute("""CREATE TABLE IF NOT EXISTS patients(
        id TEXT PRIMARY KEY, name TEXT, gender TEXT, born TEXT, created_at TEXT)""")
    store.conn.commit()

def add_patient(store, pid, name, gender="", born="") -> str:
    init(store)
    store.conn.execute(
        "INSERT OR REPLACE INTO patients(id, name, gender, born, created_at) VALUES(?,?,?,?,?)",
        (pid, name, gender, born, time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())))
    store.conn.commit()
    return pid

def get_patient(store, pid):
    return store.conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()

def list_patients(store):
    return [dict(r) for r in store.conn.execute("SELECT * FROM patients ORDER BY id").fetchall()]
