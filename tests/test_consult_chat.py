import pytest
from khub.db import Store
from khub.clinical.consult_chat import start_session, chat, get_history


def _seed(store):
    store.conn.execute("CREATE TABLE IF NOT EXISTS patients (id INTEGER PRIMARY KEY, name TEXT)")
    store.conn.execute("INSERT INTO patients (id, name) VALUES (1, '测试患者')")
    store.conn.execute(
        "INSERT INTO twin_versions (patient_id, base_record_id, base_consult_id, summary) "
        "VALUES (1, 0, 0, '测试摘要')")


def test_start_session():
    store = Store(":memory:")
    _seed(store)
    sid = start_session(store, 1)
    assert sid > 0


def test_chat_offline():
    store = Store(":memory:")
    _seed(store)
    sid = start_session(store, 1)
    reply = chat(store, sid, "我头痛三天了")
    assert reply != ""
    assert "离线助手" in reply


def test_chat_history():
    store = Store(":memory:")
    _seed(store)
    sid = start_session(store, 1)
    _ = chat(store, sid, "第一条消息")
    history = get_history(store, sid)
    assert "user" in history
    assert "assistant" in history


def test_chat_invalid_session():
    store = Store(":memory:")
    with pytest.raises(ValueError, match="不存在"):
        chat(store, 999, "test")
