"""Tests for PII encryption and audit logging on clinical data.

Covers:
- Encryption enabled: raw DB rows are ciphertext (not equal to plaintext)
- Encryption enabled: get/list return decrypted plaintext matching input
- Encryption disabled: raw DB rows are plaintext (passthrough)
- Audit: read operations produce matching audit_log entries
"""
from cryptography.fernet import Fernet
from khub.db import Store
from khub.clinical.patients import add_patient, get_patient, list_patients
from khub.clinical.records import add_record, list_records
from khub.clinical.consultations import add_consultation, list_consultations
from khub.audit import recent, init_audit
import pytest
pytestmark = pytest.mark.smoke



# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _raw_patient(store, pid):
    """Direct SQL access — bypasses decryption so we see what's on disk."""
    return store.conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()


def _raw_record(store, rid):
    return store.conn.execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone()


def _raw_consultation(store, cid):
    return store.conn.execute("SELECT * FROM consultations WHERE id=?", (cid,)).fetchone()


# ---------------------------------------------------------------------------
# encryption disabled — passthrough
# ---------------------------------------------------------------------------

def test_passthrough_patient(monkeypatch):
    """Without KHUB_PII_ENCRYPT, plaintext is stored as-is."""
    monkeypatch.delenv("KHUB_PII_ENCRYPT", raising=False)
    store = Store(":memory:")
    add_patient(store, "p1", "张三", "男", "1980-01-01")
    raw = _raw_patient(store, "p1")
    assert raw["name"] == "张三"
    assert raw["gender"] == "男"
    assert raw["born"] == "1980-01-01"
    # get_patient also returns plaintext
    p = get_patient(store, "p1")
    assert p["name"] == "张三"


def test_passthrough_record(monkeypatch):
    monkeypatch.delenv("KHUB_PII_ENCRYPT", raising=False)
    store = Store(":memory:")
    add_patient(store, "p1", "张三")
    add_record(store, "p1", diagnosis="太阳病", prescription="桂枝汤", note="忌生冷")
    rows = list_records(store, "p1")
    assert len(rows) == 1
    assert rows[0]["diagnosis"] == "太阳病"
    assert rows[0]["prescription"] == "桂枝汤"
    assert rows[0]["note"] == "忌生冷"


def test_passthrough_consultation(monkeypatch):
    monkeypatch.delenv("KHUB_PII_ENCRYPT", raising=False)
    store = Store(":memory:")
    add_patient(store, "p1", "张三")
    add_consultation(store, "p1", chief_complaint="发热", tongue_pulse="弦数",
                     differentiation="表虚", plan="桂枝汤")
    rows = list_consultations(store, "p1")
    assert len(rows) == 1
    assert rows[0]["chief_complaint"] == "发热"
    assert rows[0]["tongue_pulse"] == "弦数"
    assert rows[0]["differentiation"] == "表虚"
    assert rows[0]["plan"] == "桂枝汤"


# ---------------------------------------------------------------------------
# encryption enabled — stored as ciphertext, retrieved as plaintext
# ---------------------------------------------------------------------------

def test_encrypt_patient(monkeypatch):
    """With encryption on, raw DB holds ciphertext; get_patient returns original."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("KHUB_PII_ENCRYPT", "1")
    monkeypatch.setenv("KHUB_PII_KEY", key)

    store = Store(":memory:")
    add_patient(store, "p1", "张三", "男", "1980-01-01")

    # raw row is encrypted
    raw = _raw_patient(store, "p1")
    assert raw["name"] != "张三"
    assert raw["name"] != ""
    assert "张三" not in raw["name"]
    assert raw["gender"] != "男"
    assert "男" not in raw["gender"]
    assert raw["born"] != "1980-01-01"
    assert "1980-01-01" not in raw["born"]

    # get_patient decrypts
    p = get_patient(store, "p1")
    assert p["name"] == "张三"
    assert p["gender"] == "男"
    assert p["born"] == "1980-01-01"


def test_encrypt_patient_list(monkeypatch):
    """list_patients also decrypts fields correctly."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("KHUB_PII_ENCRYPT", "1")
    monkeypatch.setenv("KHUB_PII_KEY", key)

    store = Store(":memory:")
    add_patient(store, "p1", "张三", "男", "1980-01-01")
    add_patient(store, "p2", "李四", "女", "1990-06-15")

    patients = list_patients(store)
    assert len(patients) == 2
    names = {p["name"] for p in patients}
    assert names == {"张三", "李四"}


def test_encrypt_record(monkeypatch):
    """With encryption on, raw record is ciphertext; list_records returns original."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("KHUB_PII_ENCRYPT", "1")
    monkeypatch.setenv("KHUB_PII_KEY", key)

    store = Store(":memory:")
    add_patient(store, "p1", "张三")
    rid = add_record(store, "p1", diagnosis="太阳病", prescription="桂枝汤", note="忌生冷")

    # raw row is encrypted
    raw = _raw_record(store, rid)
    assert raw["diagnosis"] != "太阳病"
    assert "太阳病" not in raw["diagnosis"]
    assert raw["prescription"] != "桂枝汤"
    assert "桂枝汤" not in raw["prescription"]
    assert raw["note"] != "忌生冷"
    assert "忌生冷" not in raw["note"]

    # list_records decrypts
    rows = list_records(store, "p1")
    assert len(rows) == 1
    assert rows[0]["diagnosis"] == "太阳病"
    assert rows[0]["prescription"] == "桂枝汤"
    assert rows[0]["note"] == "忌生冷"


def test_encrypt_consultation(monkeypatch):
    """With encryption on, raw consultation is ciphertext; list_consultations returns original."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("KHUB_PII_ENCRYPT", "1")
    monkeypatch.setenv("KHUB_PII_KEY", key)

    store = Store(":memory:")
    add_patient(store, "p1", "张三")
    cid = add_consultation(store, "p1", chief_complaint="发热", tongue_pulse="弦数",
                           differentiation="表虚", plan="桂枝汤")

    # raw row is encrypted
    raw = _raw_consultation(store, cid)
    assert raw["chief_complaint"] != "发热"
    assert "发热" not in raw["chief_complaint"]
    assert raw["tongue_pulse"] != "弦数"
    assert "弦数" not in raw["tongue_pulse"]
    assert raw["differentiation"] != "表虚"
    assert "表虚" not in raw["differentiation"]
    assert raw["plan"] != "桂枝汤"
    assert "桂枝汤" not in raw["plan"]

    # list_consultations decrypts
    rows = list_consultations(store, "p1")
    assert len(rows) == 1
    assert rows[0]["chief_complaint"] == "发热"
    assert rows[0]["tongue_pulse"] == "弦数"
    assert rows[0]["differentiation"] == "表虚"
    assert rows[0]["plan"] == "桂枝汤"


# ---------------------------------------------------------------------------
# audit logging
# ---------------------------------------------------------------------------

def test_audit_patient_read(monkeypatch):
    """get_patient produces an audit_log entry."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("KHUB_PII_ENCRYPT", "1")
    monkeypatch.setenv("KHUB_PII_KEY", key)

    store = Store(":memory:")
    init_audit(store)
    add_patient(store, "p1", "张三")
    get_patient(store, "p1")

    entries = recent(store)
    events = [(e["event"], e["scope"], e["patient_id"]) for e in entries]
    assert ("read_patient", "patient", "p1") in events


def test_audit_patient_list(monkeypatch):
    """list_patients produces an audit_log entry."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("KHUB_PII_ENCRYPT", "1")
    monkeypatch.setenv("KHUB_PII_KEY", key)

    store = Store(":memory:")
    init_audit(store)
    add_patient(store, "p1", "张三")
    list_patients(store)

    entries = recent(store)
    events = [e["event"] for e in entries]
    assert "list_patients" in events


def test_audit_record_read(monkeypatch):
    """list_records produces an audit_log entry."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("KHUB_PII_ENCRYPT", "1")
    monkeypatch.setenv("KHUB_PII_KEY", key)

    store = Store(":memory:")
    init_audit(store)
    add_patient(store, "p1", "张三")
    add_record(store, "p1", diagnosis="太阳病")
    list_records(store, "p1")

    entries = recent(store)
    events = [(e["event"], e["scope"], e["patient_id"]) for e in entries]
    assert ("read_records", "record", "p1") in events


def test_audit_consultation_read(monkeypatch):
    """list_consultations produces an audit_log entry."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("KHUB_PII_ENCRYPT", "1")
    monkeypatch.setenv("KHUB_PII_KEY", key)

    store = Store(":memory:")
    init_audit(store)
    add_patient(store, "p1", "张三")
    add_consultation(store, "p1", chief_complaint="发热")
    list_consultations(store, "p1")

    entries = recent(store)
    events = [(e["event"], e["scope"], e["patient_id"]) for e in entries]
    assert ("read_consultations", "consultation", "p1") in events


# ---------------------------------------------------------------------------
# empty / None fields
# ---------------------------------------------------------------------------

def test_encrypt_empty_fields(monkeypatch):
    """Empty fields should remain empty after encrypt/decrypt round-trip."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("KHUB_PII_ENCRYPT", "1")
    monkeypatch.setenv("KHUB_PII_KEY", key)

    store = Store(":memory:")
    add_patient(store, "p1", "", "", "")
    p = get_patient(store, "p1")
    assert p["name"] == ""
    assert p["gender"] == ""
    assert p["born"] == ""
