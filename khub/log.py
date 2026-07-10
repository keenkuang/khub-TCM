"""结构化日志。支持 JSON 和纯文本两种格式。"""
from __future__ import annotations
import json
import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler


def setup_logging():
    """配置全局日志（在应用入口处调用一次）。"""
    level = os.environ.get("KHUB_LOG_LEVEL", "INFO").upper()
    fmt = os.environ.get("KHUB_LOG_FORMAT", "json")
    target = os.environ.get("KHUB_LOG_FILE", "")
    root = logging.getLogger()
    root.setLevel(level)
    # 清除已有 handler 避免重复
    for h in root.handlers[:]:
        root.removeHandler(h)
    if target:
        if fmt == "json":
            handler: logging.Handler = TimedRotatingFileHandler(
                target, when="midnight",
                backupCount=int(os.environ.get("KHUB_LOG_ROTATION", "30")))
            handler.setFormatter(JsonFormatter())
        else:
            handler = logging.FileHandler(target)
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    else:
        handler = logging.StreamHandler(sys.stderr)
        if fmt == "json":
            handler.setFormatter(JsonFormatter())
        else:
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(handler)


class JsonFormatter(logging.Formatter):
    """JSON 格式日志格式化器。"""
    def format(self, record):
        return json.dumps({
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }, ensure_ascii=False)
