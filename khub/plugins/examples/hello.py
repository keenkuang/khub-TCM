"""示例插件：在请求日志中打印问候。"""
import logging

from ..base import PluginBase


class HelloPlugin(PluginBase):
    name = "hello"
    version = "0.1.0"
    description = "示例插件：打印请求路径"

    def on_startup(self, store):
        logging.getLogger("khub.plugins.hello").info("HelloPlugin 已启动")

    def on_request(self, method, path, body, current_user):
        logging.getLogger("khub.plugins.hello").info("请求: %s %s", method, path)
        return None  # 不拦截请求

    def on_shutdown(self, store):
        logging.getLogger("khub.plugins.hello").info("HelloPlugin 已关闭")
