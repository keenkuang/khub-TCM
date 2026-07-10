import pytest
from khub.db import Store
from khub.clinical.extract import extract_structured, apply_struct


def test_extract_offline_keyword():
    store = Store(":memory:")
    text = "患者风寒表证，处方：桂枝汤，治法：解表散寒"
    result = extract_structured(store, text)
    assert "differentiation_norm" in result
    assert "风寒表证" in result["differentiation_norm"]
    assert "桂枝汤" in result.get("formula", "")


def test_extract_offline_no_match():
    store = Store(":memory:")
    result = extract_structured(store, "正常体检")
    assert result == {} or not any(v for v in result.values())


def test_apply_struct():
    store = Store(":memory:")
    # 确保表存在
    store.conn.execute(
        "CREATE TABLE IF NOT EXISTS record_struct ("
        "id INTEGER PRIMARY KEY, source TEXT, source_id INTEGER, "
        "differentiation_norm TEXT, syndrome TEXT, formula TEXT, method TEXT)"
    )
    apply_struct(store, "record", 1, {"differentiation_norm": "风寒表证", "formula": "桂枝汤"})
    row = store.conn.execute("SELECT * FROM record_struct WHERE source_id=1").fetchone()
    assert row is not None
    assert row["source"] == "record"
    assert row["differentiation_norm"] == "风寒表证"


def test_apply_struct_empty():
    store = Store(":memory:")
    # 确保表存在
    store.conn.execute(
        "CREATE TABLE IF NOT EXISTS record_struct ("
        "id INTEGER PRIMARY KEY, source TEXT, source_id INTEGER, "
        "differentiation_norm TEXT, syndrome TEXT, formula TEXT, method TEXT)"
    )
    apply_struct(store, "consult", 1, {})
    row = store.conn.execute("SELECT * FROM record_struct WHERE source_id=1").fetchone()
    assert row is not None
