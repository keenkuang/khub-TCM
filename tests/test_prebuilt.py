"""Tests for prebuilt reports."""
import pytest
from khub.db import Store
from khub.prebuilt import get_prebuilt_reports, execute_prebuilt
pytestmark = pytest.mark.smoke


def test_get_prebuilt_reports():
    reports = get_prebuilt_reports()
    assert len(reports) >= 4
    ids = [r["id"] for r in reports]
    assert "pb_cohorts" in ids
    assert "pb_efficacy" in ids
    assert "pb_forecast" in ids
    assert "pb_trends" in ids


def test_execute_prebuilt_invalid():
    store = Store(":memory:")
    with pytest.raises(ValueError, match="未知"):
        execute_prebuilt(store, "pb_nonexistent")


def _ensure_tables(store):
    """创建预建报表所需的业务表。"""
    for sql in [
        "CREATE TABLE IF NOT EXISTS patients (id TEXT PRIMARY KEY, name TEXT, gender TEXT, born TEXT, created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS records (patient_id TEXT, diagnosis TEXT, prescription TEXT, visit_date TEXT, note TEXT)",
        "CREATE TABLE IF NOT EXISTS appointments (id INTEGER PRIMARY KEY, doctor TEXT, date TEXT, status TEXT, patient_id TEXT)",
        "CREATE TABLE IF NOT EXISTS record_struct (id INTEGER PRIMARY KEY, source TEXT, source_id INTEGER, differentiation_norm TEXT, formula TEXT)",
        "CREATE TABLE IF NOT EXISTS followup_plans (id INTEGER PRIMARY KEY, patient_id TEXT, due_date TEXT, status TEXT)",
        "CREATE TABLE IF NOT EXISTS followup_adherence (id INTEGER PRIMARY KEY, plan_id INTEGER, attended INTEGER)",
    ]:
        store.conn.execute(sql)
    store.conn.commit()


def test_execute_prebuilt_cohorts():
    store = Store(":memory:")
    _ensure_tables(store)
    from khub.clinical.patients import add_patient
    add_patient(store, "p1", "张三", "男", "1980-01-01")
    result = execute_prebuilt(store, "pb_cohorts")
    assert "columns" in result
    assert "rows" in result
    assert result["row_count"] >= 1
    assert result["chart_type"] == "pie"


def test_execute_prebuilt_forecast():
    store = Store(":memory:")
    _ensure_tables(store)
    result = execute_prebuilt(store, "pb_forecast", days=30)
    assert "columns" in result
    assert result["chart_type"] == "line"
    assert result["row_count"] >= 1


def test_prebuilt_returns_unified_format():
    store = Store(":memory:")
    _ensure_tables(store)
    result = execute_prebuilt(store, "pb_trends")
    for key in ("columns", "rows", "row_count", "chart_type"):
        assert key in result, f"Missing key: {key}"
