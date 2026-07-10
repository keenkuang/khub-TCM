"""0.6.0 插件系统测试。"""
import os
import sys
import pytest
from khub.plugins.base import PluginBase
from khub.plugins.registry import list_plugins, discover, _plugins


def test_base_class():
    """PluginBase 抽象类可正常实例化。"""
    class TestPlugin(PluginBase):
        name = "test"
        version = "0.1.0"

    p = TestPlugin()
    assert p.name == "test"
    assert p.version == "0.1.0"
    assert p.on_startup(None) is None
    assert p.on_request("GET", "/", {}, None) is None
    assert p.on_shutdown(None) is None


def test_discover():
    """discover() 能发现示例 hello 插件。"""
    _plugins.clear()
    discover()
    names = [p["name"] for p in list_plugins()]
    assert "hello" in names, f"未发现 hello 插件，已发现: {names}"


def test_list_plugins_format():
    """list_plugins() 返回正确格式的列表。"""
    _plugins.clear()
    discover()
    plugins = list_plugins()
    for p in plugins:
        assert "name" in p
        assert "version" in p
        assert "description" in p


def test_hello_plugin_metadata():
    """hello 插件的元数据正确。"""
    _plugins.clear()
    discover()
    for p in list_plugins():
        if p["name"] == "hello":
            assert p["version"] == "0.1.0"
            assert "示例" in p["description"]
            return
    pytest.fail("未找到 hello 插件")


def test_intercept_request_no_intercept():
    """intercept_request 默认返回 None（不拦截）。"""
    from khub.plugins.registry import intercept_request
    result = intercept_request("GET", "/health", {}, None)
    assert result is None
