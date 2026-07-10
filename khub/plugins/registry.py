"""插件发现与生命周期管理。"""
from __future__ import annotations
import importlib
import logging
import os
from typing import Any

from .base import PluginBase

logger = logging.getLogger("khub.plugins")
_plugins: list[PluginBase] = []


def _discover_module(mod_name: str):
    """尝试从指定模块加载插件类。"""
    try:
        mod = importlib.import_module(mod_name)
        for attr in dir(mod):
            obj = getattr(mod, attr)
            if isinstance(obj, type) and issubclass(obj, PluginBase) and obj is not PluginBase:
                instance = obj()
                _plugins.append(instance)
                logger.info("插件已加载: %s v%s", instance.name, instance.version)
    except Exception as e:
        logger.warning("插件加载失败 %s: %s", mod_name, e)


def discover():
    """扫描 khub/plugins/ 目录发现插件。"""
    global _plugins
    _plugins = []
    path = os.path.dirname(__file__)
    seen_entries = set()
    for entry in os.listdir(path):
        entry_path = os.path.join(path, entry)
        # 顶层 .py 文件（排除基础设施文件）
        if entry.endswith(".py") and not entry.startswith("_") and entry != "base.py" and entry != "registry.py":
            mod_name = f"khub.plugins.{entry[:-3]}"
            _discover_module(mod_name)
            seen_entries.add(entry)
        # 扫描子目录中的 .py 文件（一层深度）
        elif os.path.isdir(entry_path) and not entry.startswith("_") and not entry.startswith("."):
            for sub in os.listdir(entry_path):
                if sub.endswith(".py") and not sub.startswith("_") and sub not in seen_entries:
                    mod_name = f"khub.plugins.{entry}.{sub[:-3]}"
                    _discover_module(mod_name)
                    seen_entries.add(sub)


def load_plugins(store):
    for p in _plugins:
        try:
            p.on_startup(store)
        except Exception as e:
            logger.warning("插件 on_startup 失败 %s: %s", p.name, e)


def shutdown_plugins(store):
    for p in _plugins:
        try:
            p.on_shutdown(store)
        except Exception as e:
            pass


def intercept_request(method: str, path: str, body: dict,
                      current_user: dict | None) -> dict | None:
    for p in _plugins:
        try:
            result = p.on_request(method, path, body, current_user)
            if result is not None:
                return result
        except Exception as e:
            logger.warning("插件 on_request 异常 %s: %s", p.name, e)
    return None


def list_plugins() -> list[dict]:
    return [{"name": p.name, "version": p.version, "description": p.description} for p in _plugins]
