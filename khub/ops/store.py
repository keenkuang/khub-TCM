import time
from ..db import Store

def init(store: Store):
    store.conn.executescript("""
    CREATE TABLE IF NOT EXISTS schedules(
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, doctor TEXT, slot TEXT);
    CREATE TABLE IF NOT EXISTS appointments(
        id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT, date TEXT,
        doctor TEXT, status TEXT DEFAULT 'booked', created_at TEXT);
    CREATE TABLE IF NOT EXISTS visits(
        id INTEGER PRIMARY KEY AUTOINCREMENT, appointment_id INTEGER,
        patient_id TEXT, checkin_at TEXT, note TEXT);
    """)
    store.conn.commit()

def add_schedule(store, date, doctor, slot) -> int:
    init(store)
    cur = store.conn.execute(
        "INSERT INTO schedules(date, doctor, slot) VALUES(?,?,?)", (date, doctor, slot))
    store.conn.commit()
    return cur.lastrowid

def book_appointment(store, patient_id, date, doctor) -> int:
    init(store)
    cur = store.conn.execute(
        "INSERT INTO appointments(patient_id, date, doctor, status, created_at) "
        "VALUES(?,?,?, 'booked', ?)",
        (patient_id, date, doctor, time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())))
    store.conn.commit()
    return cur.lastrowid

def checkin_visit(store, appointment_id, patient_id, note="") -> int:
    init(store)
    cur = store.conn.execute(
        "INSERT INTO visits(appointment_id, patient_id, checkin_at, note) VALUES(?,?,?,?)",
        (appointment_id, patient_id, time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()), note))
    store.conn.execute("UPDATE appointments SET status='checked_in' WHERE id=?", (appointment_id,))
    store.conn.commit()
    return cur.lastrowid

def list_appointments(store, date=None):
    if date:
        rows = store.conn.execute(
            "SELECT * FROM appointments WHERE date=? ORDER BY id", (date,)).fetchall()
    else:
        rows = store.conn.execute("SELECT * FROM appointments ORDER BY id").fetchall()
    return [dict(r) for r in rows]
