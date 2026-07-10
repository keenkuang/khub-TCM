import pytest
pytestmark = pytest.mark.smoke

import json
from khub.db import Store
from khub.analytics import patient_cohorts, visit_forecast


def test_cohorts_empty():
    store = Store(":memory:")
    from khub.clinical.patients import init as init_patients
    from khub.clinical.records import init as init_records
    init_patients(store)
    init_records(store)
    result = patient_cohorts(store)
    assert result["total_patients"] == 0


def test_cohorts_with_data():
    store = Store(":memory:")
    from khub.clinical.patients import init as init_patients
    from khub.clinical.records import init as init_records
    init_patients(store)
    init_records(store)
    store.conn.execute("INSERT INTO patients (id, name, gender, born) VALUES (1,'张三','male','1990-01-01')")
    store.conn.execute("INSERT INTO patients (id, name, gender, born) VALUES (2,'李四','female','2000-05-01')")
    store.conn.execute("INSERT INTO patients (id, name, gender, born) VALUES (3,'王五','male','1960-10-01')")
    store.conn.execute("INSERT INTO records (id, patient_id, visit_date) VALUES (1,1,'2026-07-01')")
    store.conn.execute("INSERT INTO records (id, patient_id, visit_date) VALUES (2,1,'2026-07-08')")
    store.conn.execute("INSERT INTO records (id, patient_id, visit_date) VALUES (3,3,'2026-07-01')")
    result = patient_cohorts(store)
    assert result["total_patients"] == 3
    assert result["gender_distribution"].get("male", 0) == 2
    assert result["visit_frequency"]["1次"] == 1
    assert result["visit_frequency"]["2-3次"] == 1


def test_forecast_low_data():
    store = Store(":memory:")
    from khub.clinical.records import init as init_records
    init_records(store)
    result = visit_forecast(store, days=30)
    assert result["confidence"] == "low"
    assert result["predicted_visits"] == 0
