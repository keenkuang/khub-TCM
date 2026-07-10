import json, pytest
from khub.db import Store
from khub.workflow.store import create_definition, list_definitions, create_instance, get_instance
from khub.workflow.engine import run


def test_create_definition():
    store = Store(":memory:")
    steps = [{"name": "start", "type": "auto", "config": {"action": "create_notification", "params": {"title": "工作流启动", "user_id": "1"}}, "next": "__end__"}]
    did = create_definition(store, "测试流程", steps, description="test")
    assert did > 0


def test_list_definitions():
    store = Store(":memory:")
    create_definition(store, "流程A", [{"name":"s1","type":"auto","next":"__end__"}])
    assert len(list_definitions(store)) >= 1


def test_run_simple():
    store = Store(":memory:")
    steps = [{"name": "start", "type": "auto", "config": {"action": "create_notification", "params": {"title": "Hello", "user_id": "1"}}, "next": "__end__"}]
    did = create_definition(store, "简单流程", steps)
    iid = create_instance(store, did, entity_type="test", entity_id="1")
    assert iid > 0
    result = run(store, iid)
    assert result["status"] == "completed"


def test_condition_workflow():
    store = Store(":memory:")
    steps = [
        {"name": "check", "type": "condition", "config": {"expression": "${value}", "branches": {"True": "notify_ok", "False": "notify_fail", "_default": "__end__"}}},
        {"name": "notify_ok", "type": "notify", "config": {"title": "成功", "user_id": "1"}, "next": "__end__"},
        {"name": "notify_fail", "type": "notify", "config": {"title": "失败", "user_id": "1"}, "next": "__end__"},
    ]
    did = create_definition(store, "条件流程", steps)
    iid = create_instance(store, did, context={"value": "True"})
    result = run(store, iid)
    assert result["status"] == "completed"


def test_trigger_workflow():
    from khub.workflow.triggers import on_event
    store = Store(":memory:")
    steps = [{"name": "trigger_start", "type": "trigger", "config": {"event": "appointment.created"}, "next": "action"},
             {"name": "action", "type": "auto", "config": {"action": "create_notification"}, "next": "__end__"}]
    create_definition(store, "触发流程", steps)
    on_event(store, "appointment.created", entity_type="appointment", entity_id="42")
    instances = store.conn.execute("SELECT * FROM workflow_instances").fetchall()
    assert len(instances) >= 1
