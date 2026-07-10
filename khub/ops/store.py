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
    from ..replication import install_triggers
    install_triggers(store.conn, "schedules", pk="id")
    install_triggers(store.conn, "appointments", pk="id")
    install_triggers(store.conn, "visits", pk="id")
    store.conn.commit()

def add_schedule(store, date, doctor, slot) -> int:
    init(store)
    existing = store.conn.execute(
        "SELECT id FROM schedules WHERE date=? AND doctor=? AND slot=?",
        (date, doctor, slot)).fetchone()
    if existing:
        raise ValueError(f"排班冲突：{date} {doctor} {slot}")
    cur = store.conn.execute(
        "INSERT INTO schedules(date, doctor, slot) VALUES(?,?,?)", (date, doctor, slot))
    sid = cur.lastrowid
    # WAL 触发器已自动记账
    store.conn.commit()
    return sid

def book_appointment(store, patient_id, date, doctor) -> int:
    init(store)
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    cur = store.conn.execute(
        "INSERT INTO appointments(patient_id, date, doctor, status, created_at) "
        "VALUES(?,?,?, 'booked', ?)", (patient_id, date, doctor, now))
    aid = cur.lastrowid
    # WAL 触发器已自动记账
    store.conn.commit()
    return aid

def checkin_visit(store, appointment_id, patient_id, note="") -> int:
    init(store)
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    cur = store.conn.execute(
        "INSERT INTO visits(appointment_id, patient_id, checkin_at, note) VALUES(?,?,?,?)",
        (appointment_id, patient_id, now, note))
    vid = cur.lastrowid
    store.conn.execute("UPDATE appointments SET status='checked_in' WHERE id=?", (appointment_id,))
    # WAL 触发器已自动记账（visits 的 INSERT 与 appointments 的 UPDATE 各触发一次）
    store.conn.commit()
    return vid

# ---- 备机回放（直写主表、绕过 record_change） ----
def apply_schedule(store, op, row_id, payload):
    if op == "delete":
        store.conn.execute("DELETE FROM schedules WHERE id=?", (row_id,)); return
    store.conn.execute(
        "INSERT OR REPLACE INTO schedules(id, date, doctor, slot) VALUES(?,?,?,?)",
        (payload.get("id", row_id), payload.get("date", ""), payload.get("doctor", ""),
         payload.get("slot", "")))

def apply_appointment(store, op, row_id, payload):
    if op == "delete":
        store.conn.execute("DELETE FROM appointments WHERE id=?", (row_id,)); return
    store.conn.execute(
        "INSERT OR REPLACE INTO appointments(id, patient_id, date, doctor, status, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (payload.get("id", row_id), payload.get("patient_id", ""), payload.get("date", ""),
         payload.get("doctor", ""), payload.get("status", "booked"), payload.get("created_at", "")))

def apply_visit(store, op, row_id, payload):
    if op == "delete":
        store.conn.execute("DELETE FROM visits WHERE id=?", (row_id,)); return
    store.conn.execute(
        "INSERT OR REPLACE INTO visits(id, appointment_id, patient_id, checkin_at, note) "
        "VALUES(?,?,?,?,?)",
        (payload.get("id", row_id), payload.get("appointment_id", ""), payload.get("patient_id", ""),
         payload.get("checkin_at", ""), payload.get("note", "")))

def list_appointments(store, date=None):
    if date:
        rows = store.conn.execute(
            "SELECT * FROM appointments WHERE date=? ORDER BY id", (date,)).fetchall()
    else:
        rows = store.conn.execute("SELECT * FROM appointments ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def list_schedules(store, date=None):
    if date:
        rows = store.conn.execute(
            "SELECT * FROM schedules WHERE date=? ORDER BY id", (date,)).fetchall()
    else:
        rows = store.conn.execute("SELECT * FROM schedules ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def cancel_appointment(store, id):
    store.conn.execute(
        "UPDATE appointments SET status='cancelled' WHERE id=?", (id,))
    store.conn.commit()


def mark_no_show(store, appointment_id):
    store.conn.execute(
        "UPDATE appointments SET status='no_show' WHERE id=?", (appointment_id,))
    store.conn.commit()


def complete_visit(store, appointment_id):
    store.conn.execute(
        "UPDATE appointments SET status='completed' WHERE id=?", (appointment_id,))
    store.conn.commit()


def reschedule_appointment(store, id, new_date):
    row = store.conn.execute(
        "SELECT patient_id, doctor FROM appointments WHERE id=?", (id,)).fetchone()
    if not row:
        raise ValueError("预约不存在")
    store.conn.execute(
        "UPDATE appointments SET status='cancelled' WHERE id=?", (id,))
    new_id = book_appointment(store, row["patient_id"], new_date, row["doctor"])
    return new_id
