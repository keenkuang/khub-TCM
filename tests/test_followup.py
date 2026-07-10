import pytest
from khub.db import Store
from khub.clinical.followup import add_plan, scan_due, record_adherence


def _seed(store):
    store.conn.execute("CREATE TABLE IF NOT EXISTS patients (id INTEGER PRIMARY KEY, name TEXT)")
    store.conn.execute("INSERT INTO patients (id, name) VALUES (1, '测试患者')")


def test_add_plan():
    store = Store(":memory:")
    _seed(store)
    pid = add_plan(store, 1, "2026-08-01", "术后复查")
    assert pid > 0


def test_scan_due():
    store = Store(":memory:")
    _seed(store)
    add_plan(store, 1, "2026-07-01", "术后复查")
    due = scan_due(store, as_of="2026-07-10")
    assert len(due) == 1
    assert due[0]["status"] == "due"


def test_scan_due_no_matches():
    store = Store(":memory:")
    _seed(store)
    add_plan(store, 1, "2099-01-01", "远期")
    due = scan_due(store, as_of="2026-07-10")
    assert len(due) == 0


def test_record_adherence():
    store = Store(":memory:")
    _seed(store)
    plan_id = add_plan(store, 1, "2026-07-01", "复查")
    scan_due(store, as_of="2026-07-10")
    record_adherence(store, plan_id, True)
    row = store.conn.execute(
        "SELECT status FROM followup_plans WHERE id=?", (plan_id,)
    ).fetchone()
    assert row["status"] == "done"


def test_auto_book_default_off():
    store = Store(":memory:")
    _seed(store)
    add_plan(store, 1, "2026-07-01", "复查")
    due = scan_due(store, as_of="2026-07-10")
    assert "appointment_booked" not in due[0]
