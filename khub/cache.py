"""简单 TTL 内存缓存。"""
from __future__ import annotations
import time

_cache: dict[str, tuple[float, object]] = {}
_default_ttl = 5  # 默认 5 秒


def get(key: str) -> object | None:
    entry = _cache.get(key)
    if entry and entry[0] > time.time():
        return entry[1]
    if entry:
        del _cache[key]
    return None


def set(key: str, value: object, ttl: int = 0):
    _cache[key] = (time.time() + (ttl or _default_ttl), value)


def clear():
    _cache.clear()


def invalidate(prefix: str = ""):
    if not prefix:
        _cache.clear()
        return
    for k in list(_cache.keys()):
        if k.startswith(prefix):
            del _cache[k]
