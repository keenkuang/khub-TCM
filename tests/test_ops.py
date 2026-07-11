from khub.db import Store
from khub.ops.store import (add_schedule, book_appointment, checkin_visit,
                            list_appointments, cancel_appointment,
                            reschedule_appointment, list_schedules, init)
import pytest
pytestmark = pytest.mark.smoke

_ADMIN_USER = {"user_id": 1, "username": "admin", "role": "admin"}


def test_ops_flow():
    s = Store(":memory:")
    add_schedule(s, "2026-07-10", "王医生", "09:00")
    aid = book_appointment(s, "p1", "2026-07-10", "王医生")
    assert aid >= 1
    vid = checkin_visit(s, aid, "p1")
    assert vid >= 1
    appts = list_appointments(s, "2026-07-10", user=_ADMIN_USER)
    assert len(appts) == 1 and appts[0]["status"] == "checked_in"


def test_cancel_appointment():
    s = Store(":memory:")
    add_schedule(s, "2026-07-15", "张医生", "上午")
    aid = book_appointment(s, 1, "2026-07-15", "张医生")
    cancel_appointment(s, aid)
    row = s.conn.execute("SELECT status FROM appointments WHERE id=?", (aid,)).fetchone()
    assert row["status"] == "cancelled"


def test_schedule_conflict():
    s = Store(":memory:")
    add_schedule(s, "2026-07-15", "张医生", "上午")
    with pytest.raises(ValueError, match="排班冲突"):
        add_schedule(s, "2026-07-15", "张医生", "上午")


def test_reschedule():
    s = Store(":memory:")
    add_schedule(s, "2026-07-15", "张医生", "上午")
    add_schedule(s, "2026-07-16", "张医生", "上午")
    aid = book_appointment(s, 1, "2026-07-15", "张医生")
    new_id = reschedule_appointment(s, aid, "2026-07-16")
    row_old = s.conn.execute("SELECT status FROM appointments WHERE id=?", (aid,)).fetchone()
    row_new = s.conn.execute("SELECT status FROM appointments WHERE id=?", (new_id,)).fetchone()
    assert row_old["status"] == "cancelled"
    assert row_new["status"] == "booked"


def test_list_appointments_by_patient():
    from khub.ops.store import add_schedule, book_appointment
    store = Store(":memory:")
    init(store)
    add_schedule(store, "2026-08-01", "李医生", "上午")
    book_appointment(store, 1, "2026-08-01", "李医生")
    book_appointment(store, 2, "2026-08-01", "李医生")
    # 验证仅返回 patient_id=1 的预约
    rows = store.conn.execute(
        "SELECT * FROM appointments WHERE patient_id=?", (1,)).fetchall()
    assert len(rows) == 1
