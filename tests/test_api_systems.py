import os
import tempfile

from khub.api import App
from khub.db import Store
from khub.storage import ManagedLibrary
import pytest
pytestmark = pytest.mark.smoke



def _app():
    d = tempfile.mkdtemp()
    store = Store(":memory:")
    lib = ManagedLibrary(os.path.join(d, "lib"))
    return App(store, lib)


def test_exam_questions_post_then_list():
    app = _app()
    code, obj = app.dispatch("POST", "/exam/questions", {
        "kind": "mcq", "stem": "下列哪项是太阳病的主症？",
        "options": ["发热汗出", "腹满而吐"], "answer": "发热汗出",
        "explanation": "太阳病中风证。", "source_doc": "伤寒论"})
    assert code == 201 and obj["id"]
    qid = obj["id"]

    code, obj = app.dispatch("GET", "/exam/questions")
    assert code == 200
    assert any(q["id"] == qid and q["stem"] == "下列哪项是太阳病的主症？" for q in obj)

    code, obj = app.dispatch("GET", "/exam/questions?kind=mcq")
    assert code == 200 and obj and obj[0]["id"] == qid


def test_exam_generate_returns_question_like():
    app = _app()
    code, obj = app.dispatch("POST", "/exam/generate", {"topic": "方剂学", "source_doc": ""})
    assert code == 200
    assert isinstance(obj, dict)
    assert obj.get("stem")  # non-empty stem


def test_clinical_patient_record_flow():
    app = _app()
    code, obj = app.dispatch("POST", "/clinical/patients",
                             {"id": "p1", "name": "张三", "gender": "男", "born": "1990"})
    assert code == 201 and obj["id"] == "p1"

    code, obj = app.dispatch("POST", "/clinical/records",
                             {"patient_id": "p1", "diagnosis": "感冒",
                              "prescription": "桂枝汤", "note": "复诊"})
    assert code == 201 and obj["id"]

    code, obj = app.dispatch("GET", "/clinical/patients")
    assert code == 200
    assert any(p["id"] == "p1" and p["name"] == "张三" for p in obj)


def test_ops_full_flow():
    app = _app()
    code, obj = app.dispatch("POST", "/ops/schedules",
                             {"date": "2026-01-01", "doctor": "李医生", "slot": "09:00"})
    assert code == 201 and obj["id"]

    code, obj = app.dispatch("POST", "/ops/appointments",
                             {"patient_id": "p1", "date": "2026-01-01", "doctor": "李医生"})
    assert code == 201 and obj["id"]
    aid = obj["id"]

    code, obj = app.dispatch("POST", "/ops/visits",
                             {"appointment_id": aid, "patient_id": "p1", "note": "已到"})
    assert code == 201 and obj["id"]

    code, obj = app.dispatch("GET", "/ops/appointments?date=2026-01-01")
    assert code == 200
    assert any(a["id"] == aid and a["status"] == "checked_in" for a in obj)


def test_clinical_twin_summary():
    app = _app()
    app.dispatch("POST", "/clinical/patients", {"id": "p2", "name": "李四"})
    app.dispatch("POST", "/clinical/records", {"patient_id": "p2", "diagnosis": "失眠"})
    code, obj = app.dispatch("POST", "/clinical/twin/p2/summarize")
    assert code == 200
    assert obj["patient_id"] == "p2"
    assert obj["summary"]  # non-empty summary
