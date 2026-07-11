"""Tests for BI dashboard queries."""
import pytest
from khub.db import Store
from khub.dashboard import (
    visit_trend, patient_demographics, diagnosis_distribution,
    appointment_stats, dashboard_summary,
    create_tile, list_tiles, get_tile, update_tile, delete_tile, reorder_tiles,
)
pytestmark = pytest.mark.smoke


def _seed_patient(store, pid="p1", name="张三", gender="男", born="1980"):
    store.conn.execute("CREATE TABLE IF NOT EXISTS patients (id TEXT PRIMARY KEY, name TEXT, gender TEXT, born TEXT)")
    store.conn.execute(
        "INSERT OR IGNORE INTO patients (id, name, gender, born) VALUES (?,?,?,?)",
        (pid, name, gender, born))
    store.conn.commit()


def _seed_record(store, pid="p1", diagnosis="太阳病", visit_date="2026-07-01"):
    store.conn.execute("CREATE TABLE IF NOT EXISTS records (patient_id TEXT, diagnosis TEXT, prescription TEXT, visit_date TEXT)")
    store.conn.execute(
        "INSERT INTO records (patient_id, diagnosis, visit_date) "
        "VALUES (?,?,?)", (pid, diagnosis, visit_date))
    store.conn.commit()


def _seed_appointment(store, doctor="王医生", date="2026-07-15", status="booked"):
    store.conn.execute("CREATE TABLE IF NOT EXISTS appointments (doctor TEXT, date TEXT, status TEXT)")
    store.conn.execute(
        "INSERT INTO appointments (doctor, date, status) VALUES (?,?,?)",
        (doctor, date, status))
    store.conn.commit()


def test_visit_trend():
    store = Store(":memory:")
    _seed_record(store)
    result = visit_trend(store, period="daily", days=30)
    assert len(result) >= 1


def test_patient_demographics():
    store = Store(":memory:")
    _seed_patient(store)
    _seed_patient(store, pid="p2", name="李四", gender="女", born="1995")
    result = patient_demographics(store)
    assert len(result) >= 1


def test_diagnosis_distribution():
    store = Store(":memory:")
    _seed_record(store)
    _seed_record(store, pid="p1", diagnosis="少阴病", visit_date="2026-07-02")
    result = diagnosis_distribution(store, top_n=5)
    assert len(result) >= 1


def test_appointment_stats():
    store = Store(":memory:")
    _seed_appointment(store)
    _seed_appointment(store, status="checked_in")
    result = appointment_stats(store)
    assert len(result) >= 1


def test_dashboard_summary():
    store = Store(":memory:")
    _seed_patient(store)
    _seed_record(store)
    _seed_appointment(store)
    summary = dashboard_summary(store)
    assert "visit_trend" in summary
    assert "demographics" in summary
    assert "appointment_stats" in summary


# ── 看板瓦片 CRUD ──

def test_create_tile():
    store = Store(":memory:")
    tid = create_tile(store, "测试瓦片", tile_type="stat", chart_type="table")
    assert tid > 0


def test_list_tiles():
    store = Store(":memory:")
    create_tile(store, "瓦片A")
    create_tile(store, "瓦片B")
    tiles = list_tiles(store)
    assert len(tiles) == 2


def test_get_tile():
    store = Store(":memory:")
    tid = create_tile(store, "可见")
    t = get_tile(store, tid)
    assert t is not None
    assert t["name"] == "可见"
    assert get_tile(store, 999) is None


def test_update_tile():
    store = Store(":memory:")
    tid = create_tile(store, "原名")
    ok = update_tile(store, tid, name="新名")
    assert ok is True
    t = get_tile(store, tid)
    assert t["name"] == "新名"


def test_delete_tile():
    store = Store(":memory:")
    tid = create_tile(store, "待删")
    ok = delete_tile(store, tid)
    assert ok is True
    assert get_tile(store, tid) is None


def test_reorder_tiles():
    store = Store(":memory:")
    t1 = create_tile(store, "A")
    t2 = create_tile(store, "B")
    reorder_tiles(store, [t2, t1])
    tiles = list_tiles(store)
    assert tiles[0]["id"] == t2  # B should be first after reorder
