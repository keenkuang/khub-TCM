from khub.db import Store
from khub.ops.store import add_schedule, book_appointment, checkin_visit, list_appointments

def test_ops_flow():
    s = Store(":memory:")
    add_schedule(s, "2026-07-10", "王医生", "09:00")
    aid = book_appointment(s, "p1", "2026-07-10", "王医生")
    assert aid >= 1
    vid = checkin_visit(s, aid, "p1")
    assert vid >= 1
    appts = list_appointments(s, "2026-07-10")
    assert len(appts) == 1 and appts[0]["status"] == "checked_in"
