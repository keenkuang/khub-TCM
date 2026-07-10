import pytest
from khub.db import Store
from khub.clinical.twin_v2 import (
    build_summary_incremental, get_timeline, get_syndrome_evolution
)

def _ensure_clinical_tables(store):
    """创建 clinical 子系统需要的表（lazy init 模拟）。"""
    store.conn.execute("""CREATE TABLE IF NOT EXISTS patients(
        id TEXT PRIMARY KEY, name TEXT, gender TEXT, born TEXT, created_at TEXT)""")
    store.conn.execute("""CREATE TABLE IF NOT EXISTS records(
        id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT, visit_date TEXT,
        diagnosis TEXT, prescription TEXT, note TEXT, created_at TEXT)""")
    store.conn.execute("""CREATE TABLE IF NOT EXISTS consultations(
        id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT, date TEXT,
        chief_complaint TEXT, tongue_pulse TEXT, differentiation TEXT, plan TEXT,
        created_at TEXT)""")
    store.conn.commit()

def _seed_patient(store):
    _ensure_clinical_tables(store)
    store.conn.execute("INSERT INTO patients (id, name) VALUES (1, '测试患者')")
    store.conn.execute("INSERT INTO records (id, patient_id, visit_date, diagnosis, prescription) "
                       "VALUES (1, 1, '2026-07-01', '感冒', '桂枝汤')")
    store.conn.execute("INSERT INTO consultations (id, patient_id, date, chief_complaint, differentiation) "
                       "VALUES (1, 1, '2026-07-02', '头痛', '风寒束表')")


def test_timeline_basic():
    store = Store(":memory:")
    _seed_patient(store)
    tl = get_timeline(store, 1)
    assert len(tl) == 2
    assert tl[0]["type"] == "record"
    assert tl[1]["type"] == "consultation"


def test_timeline_empty():
    store = Store(":memory:")
    assert get_timeline(store, 999) == []


def test_summary_no_new_data():
    store = Store(":memory:")
    _seed_patient(store)
    store.conn.execute(
        "INSERT INTO twin_versions (patient_id, base_record_id, base_consult_id, summary) "
        "VALUES (1, 1, 1, '既有摘要')")
    result = build_summary_incremental(store, 1)
    assert result == "既有摘要"


def test_summary_incremental_with_new_data():
    store = Store(":memory:")
    _seed_patient(store)
    result = build_summary_incremental(store, 1)
    assert result != ""
    assert "离线模式" in result


def test_syndrome_evolution():
    store = Store(":memory:")
    _seed_patient(store)
    ev = get_syndrome_evolution(store, 1)
    assert len(ev) == 1
    assert "风寒束表" in ev[0]["differentiation"]


def test_syndrome_evolution_empty():
    store = Store(":memory:")
    assert get_syndrome_evolution(store, 999) == []
