import pytest
pytestmark = pytest.mark.smoke

"""0.9.0 AI Agent 平台测试。"""
import json
import pytest
from khub.db import Store
from khub.agents.store import create_agent, list_agents, get_agent, update_agent
from khub.agents.engine import run


def test_create_agent():
    store = Store(":memory:")
    aid = create_agent(store, "健康助手", system_prompt="你是一个健康助手",
                       tools=["search_docs", "help"])
    assert aid > 0


def test_list_agents():
    store = Store(":memory:")
    create_agent(store, "AgentA")
    create_agent(store, "AgentB")
    assert len(list_agents(store)) == 2


def test_get_agent():
    store = Store(":memory:")
    aid = create_agent(store, "测试Agent", tools=["help"])
    agent = get_agent(store, aid)
    assert agent["name"] == "测试Agent"


def test_run_agent():
    store = Store(":memory:")
    aid = create_agent(store, "测试", tools=["help"])
    result = run(store, aid, "测试输入")
    assert result["agent_id"] == aid
    assert len(result["results"]) >= 1


def test_agent_not_found():
    store = Store(":memory:")
    with pytest.raises(ValueError, match="不存在"):
        run(store, 999, "")
