import pytest
from khub.db import Store
from khub.agents.ensemble import run_parallel, vote, cascade
from khub.agents.store import create_agent


def test_run_parallel():
    store = Store(":memory:")
    aid = create_agent(store, "测试Agent", tools=["help"])
    results = run_parallel(store, [aid], "test")
    assert len(results) == 1
    assert results[0]["agent_id"] == aid


def test_vote():
    store = Store(":memory:")
    aid = create_agent(store, "投票Agent", tools=["help"])
    result = vote(store, [aid], "测试投票")
    assert "consensus" in result
    assert result["total_agents"] == 1


def test_cascade_single():
    store = Store(":memory:")
    aid = create_agent(store, "级联Agent", tools=["help"])
    pipeline = [{"agent_id": aid, "mode": "single"}]
    results = cascade(store, pipeline, "输入")
    assert len(results) == 1
    assert results[0]["mode"] == "single"


def test_cascade_vote():
    store = Store(":memory:")
    aid = create_agent(store, "AgentA", tools=["help"])
    pipeline = [{"agent_id": [aid], "mode": "vote"}]
    results = cascade(store, pipeline, "测试")
    assert len(results) >= 1
