import pytest
from khub.db import Store


def _ensure_tables(store):
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


def _seed(store):
    store.conn.execute("INSERT INTO patients (id, name) VALUES (1, '测试')")
    store.conn.execute("INSERT INTO records (id, patient_id, visit_date) VALUES (1, 1, '2026-07-01')")
    store.conn.execute("INSERT INTO record_struct (source, source_id, differentiation_norm, formula) VALUES ('record', 1, '风寒表证', '桂枝汤')")
    store.conn.execute("INSERT INTO record_struct (source, source_id, differentiation_norm, formula) VALUES ('record', 1, '风寒表证', '桂枝汤')")
    store.conn.execute("INSERT INTO consultations (id, patient_id, date, differentiation) VALUES (1, 1, '2026-07-02', '风寒束表')")


def test_build_matrix():
    from khub.clinical.analysis import build_syndrome_formula_matrix
    store = Store(":memory:")
    _ensure_tables(store)
    _seed(store)
    matrix = build_syndrome_formula_matrix(store)
    assert len(matrix) >= 1
    assert "风寒表证" in matrix
    assert matrix["风寒表证"]["桂枝汤"] >= 2


def test_analyze_evolution():
    from khub.clinical.analysis import analyze_constitution_evolution
    store = Store(":memory:")
    _ensure_tables(store)
    _seed(store)
    result = analyze_constitution_evolution(store, 1)
    assert result["direction"] == "stable"
    assert result["count"] >= 1
