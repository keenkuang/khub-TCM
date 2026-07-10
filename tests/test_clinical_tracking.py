from khub.db import Store


def _ensure_tables(store):
    store.conn.execute("""CREATE TABLE IF NOT EXISTS patients(
        id TEXT PRIMARY KEY, name TEXT, gender TEXT, born TEXT, created_at TEXT)""")
    store.conn.execute("""CREATE TABLE IF NOT EXISTS records(
        id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT, visit_date TEXT,
        diagnosis TEXT, prescription TEXT, note TEXT, created_at TEXT)""")
    store.conn.commit()


def test_evaluate_efficacy():
    from khub.clinical.tracking import evaluate_efficacy
    store = Store(":memory:")
    _ensure_tables(store)
    store.conn.execute("INSERT INTO patients (id, name) VALUES (1, '测试')")
    store.conn.execute("INSERT INTO records (id, patient_id, visit_date) VALUES (1, 1, '2026-07-01')")
    store.conn.execute("INSERT INTO records (id, patient_id, visit_date) VALUES (2, 1, '2026-07-08')")
    store.conn.execute("INSERT INTO records (id, patient_id, visit_date) VALUES (3, 1, '2026-07-15')")
    store.conn.execute("INSERT INTO followup_plans (id, patient_id, due_date) VALUES (1, 1, '2026-07-20')")
    store.conn.execute("INSERT INTO followup_adherence (plan_id, attended) VALUES (1, 1)")
    result = evaluate_efficacy(store, 1)
    assert result["visit_count"] == 3
    assert result["adherence_rate"] == 1.0
    assert result["followup_compliance"] == "good"
    assert result["treatment_continuity"] == "consistent"


def test_evaluate_efficacy_no_data():
    from khub.clinical.tracking import evaluate_efficacy
    store = Store(":memory:")
    _ensure_tables(store)
    result = evaluate_efficacy(store, 999)
    assert result["visit_count"] == 0
    assert result["adherence_rate"] == 0
