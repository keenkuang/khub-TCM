"""插件基类。"""
from __future__ import annotations
from typing import Any, Optional


class PluginBase:
    name: str = "unnamed"
    version: str = "0.1.0"
    description: str = ""

    def on_startup(self, store) -> None:
        """服务启动时调用。"""

    def on_request(self, method: str, path: str, body: dict,
                   current_user: Optional[dict]) -> Optional[dict]:
        """请求预处理。返回 dict 则直接作为响应返回（拦截请求）。"""

    def on_shutdown(self, store) -> None:
        """服务关闭时调用。"""
