"""远程医疗平台测试：视频问诊信令 + 电子处方。"""
import pytest
from khub.db import Store
from khub.telemedicine.signaling import create_room, get_room, set_offer, set_answer, end_call
from khub.telemedicine.prescriptions import create_prescription, get_prescription, list_prescriptions


# ── telemedicine_sessions 表（通过 create_room 隐式创建） ──────────────


def test_create_room():
    store = Store(":memory:")
    result = create_room(store)
    assert "room_id" in result
    assert "session_id" in result
    assert len(result["room_id"]) > 0


def test_create_room_with_appointment():
    store = Store(":memory:")
    result = create_room(store, appointment_id=42)
    assert result["session_id"] > 0
    row = store.conn.execute(
        "SELECT appointment_id FROM telemedicine_sessions WHERE id=?",
        (result["session_id"],)).fetchone()
    assert row["appointment_id"] == 42


def test_get_room_found():
    store = Store(":memory:")
    result = create_room(store)
    room = get_room(store, result["room_id"])
    assert room is not None
    assert room["room_id"] == result["room_id"]


def test_get_room_not_found():
    store = Store(":memory:")
    room = get_room(store, "nonexistent")
    assert room is None


def test_set_offer():
    store = Store(":memory:")
    result = create_room(store)
    set_offer(store, result["room_id"], "test_offer_sdp")
    room = get_room(store, result["room_id"])
    assert room["offer"] == "test_offer_sdp"
    assert room["status"] == "waiting"


def test_set_answer():
    store = Store(":memory:")
    result = create_room(store)
    set_answer(store, result["room_id"], "test_answer_sdp")
    room = get_room(store, result["room_id"])
    assert room["answer"] == "test_answer_sdp"
    assert room["status"] == "in_call"
    assert room["started_at"] is not None


def test_end_call():
    store = Store(":memory:")
    result = create_room(store)
    set_answer(store, result["room_id"], "answer")
    end_call(store, result["room_id"])
    room = get_room(store, result["room_id"])
    assert room["status"] == "completed"
    assert room["ended_at"] is not None


def test_full_signaling_flow():
    """完整的信令流程：创建→offer→answer→结束。"""
    store = Store(":memory:")
    # 创建房间
    r = create_room(store, appointment_id=1)
    rid = r["room_id"]
    # 医生发 offer
    set_offer(store, rid, "sdp_offer_v1")
    assert get_room(store, rid)["offer"] == "sdp_offer_v1"
    # 患者接 answer
    set_answer(store, rid, "sdp_answer_v1")
    room = get_room(store, rid)
    assert room["status"] == "in_call"
    assert room["started_at"] is not None
    # 结束通话
    end_call(store, rid)
    room = get_room(store, rid)
    assert room["status"] == "completed"
    assert room["ended_at"] is not None


# ── 电子处方 ─────────────────────────────────────────────────────────


def test_create_prescription():
    store = Store(":memory:")
    items = [{"name": "阿莫西林", "dosage": "0.5g", "frequency": "tid"}]
    pid = create_prescription(store, 1, 2, 3, items)
    assert pid > 0


def test_get_prescription_found():
    store = Store(":memory:")
    items = [{"name": "板蓝根", "dosage": "10g", "frequency": "bid"}]
    pid = create_prescription(store, 1, 2, 3, items)
    presc = get_prescription(store, pid)
    assert presc is not None
    assert presc["id"] == pid
    assert len(presc["items"]) == 1
    assert presc["items"][0]["name"] == "板蓝根"


def test_get_prescription_not_found():
    store = Store(":memory:")
    presc = get_prescription(store, 999)
    assert presc is None


def test_list_prescriptions_all():
    store = Store(":memory:")
    p1 = create_prescription(store, 1, 2, 10,
                             [{"name": "药A", "dosage": "1"}])
    p2 = create_prescription(store, 2, 3, 10,
                             [{"name": "药B", "dosage": "2"}])
    p3 = create_prescription(store, 3, 4, 20,
                             [{"name": "药C", "dosage": "3"}])
    all_p = list_prescriptions(store)
    assert len(all_p) >= 3
    # 按 id DESC，p3 最新
    assert all_p[0]["id"] == p3


def test_list_prescriptions_by_patient():
    store = Store(":memory:")
    create_prescription(store, 1, 2, 10, [{"name": "药A"}])
    create_prescription(store, 2, 3, 10, [{"name": "药B"}])
    create_prescription(store, 3, 4, 20, [{"name": "药C"}])
    patient_p = list_prescriptions(store, patient_id=10)
    assert len(patient_p) == 2
    for p in patient_p:
        assert p["patient_id"] == 10


def test_prescription_default_draft():
    store = Store(":memory:")
    pid = create_prescription(store, 1, 2, 3,
                              [{"name": "测试药"}])
    presc = get_prescription(store, pid)
    assert presc["status"] == "draft"
