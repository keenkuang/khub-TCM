import pytest
pytestmark = pytest.mark.smoke

"""AI Copilot 测试。"""
import pytest
from khub.db import Store
from khub.copilot.intents import parse
from khub.copilot.tools import list_tools, call_tool


def test_parse_help():
    result = parse("你能做什么")
    assert result["intent"] == "help"


def test_parse_search():
    result = parse("搜索关于感冒的文档")
    assert result["intent"] == "search_docs"


def test_parse_appointment():
    result = parse("帮我预约明天李医生的号")
    assert result["intent"] == "book_appointment"


def test_parse_patient():
    result = parse("查询患者张三的信息")
    assert result["intent"] == "get_patient"


def test_parse_knowledge():
    result = parse("风寒表证推荐什么方剂")
    assert result["intent"] == "query_knowledge_graph"


def test_list_tools():
    tools = list_tools()
    assert len(tools) >= 8
    names = [t["name"] for t in tools]
    assert "search_docs" in names
    assert "book_appointment" in names
    assert "help" in names


def test_call_help():
    store = Store(":memory:")
    result = call_tool("help", {}, store)
    assert "search_docs" in result
    assert "book_appointment" in result


def test_call_search_docs():
    store = Store(":memory:")
    result = call_tool("search_docs", {"q": "test"}, store)
    assert result is not None  # 无数据时返回"未找到"而非报错
