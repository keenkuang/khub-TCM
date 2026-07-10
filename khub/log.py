"""统一日志配置。生产环境写文件，开发环境打 stderr。"""
import logging
import os
import sys

_LOG = None


def get_logger(name: str = "khub") -> logging.Logger:
    global _LOG
    if _LOG is not None:
        return _LOG.getChild(name)

    level = getattr(logging, os.environ.get("KHUB_LOG_LEVEL", "INFO").upper(), logging.INFO)
    target = os.environ.get("KHUB_LOG_FILE", "")

    root = logging.getLogger("khub")
    root.setLevel(level)
    root.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                            datefmt="%Y-%m-%dT%H:%M:%S")

    if target:
        h: logging.Handler = logging.FileHandler(os.path.expanduser(target), encoding="utf-8")
    else:
        h = logging.StreamHandler(sys.stderr)
    h.setFormatter(fmt)
    root.addHandler(h)

    _LOG = root
    return root.getChild(name)
