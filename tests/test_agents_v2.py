import pytest, json
from khub.db import Store
from khub.agents.templates import seed, list_templates, create_from_template
from khub.agents.memory import store, recall, list_memory
from khub.agents.pipeline import create_pipeline, list_pipelines, run as run_pipeline


def test_seed_templates():
    db = Store(":memory:")
    seed(db)
    templates = list_templates(db)
    assert len(templates) == 5


def test_list_by_category():
    db = Store(":memory:")
    seed(db)
    t = list_templates(db, category="中医")
    assert len(t) >= 1


def test_create_from_template():
    db = Store(":memory:")
    seed(db)
    t = list_templates(db)
    aid = create_from_template(db, t[0]["id"])
    assert aid > 0


def test_memory_store_and_recall():
    db = Store(":memory:")
    store(db, 1, "last_patient", "张三")
    assert recall(db, 1, "last_patient") == "张三"
    assert recall(db, 1, "nonexistent") is None


def test_memory_list():
    db = Store(":memory:")
    store(db, 1, "k1", "v1"); store(db, 1, "k2", "v2")
    assert len(list_memory(db, 1)) == 2


def test_pipeline():
    db = Store(":memory:")
    from khub.agents.store import create_agent
    aid = create_agent(db, "测试Agent", tools=["help"])
    pid = create_pipeline(db, "测试管线", [aid])
    assert pid > 0
    pipelines = list_pipelines(db)
    assert len(pipelines) == 1
