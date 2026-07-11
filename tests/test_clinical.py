from khub.db import Store
from khub.clinical.patients import add_patient, get_patient, list_patients
from khub.clinical.records import add_record, list_records
from khub.clinical.consultations import add_consultation, list_consultations
from khub.clinical.twin import build_summary, persist_summary
import pytest
pytestmark = pytest.mark.smoke

_ADMIN_USER = {"user_id": 1, "username": "admin", "role": "admin"}


def test_patient_and_records_and_consultations():
    s = Store(":memory:")
    add_patient(s, "p1", "张三", "男", "1980-01-01")
    assert get_patient(s, "p1")["name"] == "张三"
    assert len(list_patients(s, user=_ADMIN_USER)) == 1
    add_record(s, "p1", diagnosis="太阳病", prescription="桂枝汤")
    add_consultation(s, "p1", chief_complaint="发热", differentiation="表虚")
    assert len(list_records(s, "p1", user=_ADMIN_USER)) == 1
    assert len(list_consultations(s, "p1", user=_ADMIN_USER)) == 1

def test_twin_summary_and_persist():
    s = Store(":memory:")
    add_patient(s, "p2", "李四")
    add_record(s, "p2", diagnosis="少阴病")
    add_consultation(s, "p2", chief_complaint="脉微细")
    summary = build_summary(s, "p2", user=_ADMIN_USER)
    assert isinstance(summary, str) and summary  # non-empty even with NoOp
    persist_summary(s, "p2")
    assert s.get_document("twin:p2") is not None
