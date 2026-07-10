"""SSE 事件推送管理。"""
from __future__ import annotations
import json
import queue
import threading

_subs: dict[int, queue.Queue] = {}
_lock = threading.Lock()
_next_id = 0


def subscribe() -> tuple[int, queue.Queue]:
    """新客户端订阅事件流。返回 (sub_id, queue)。"""
    global _next_id
    with _lock:
        _next_id += 1
        q: queue.Queue = queue.Queue()
        _subs[_next_id] = q
        return _next_id, q


def unsubscribe(sub_id: int):
    with _lock:
        _subs.pop(sub_id, None)


def broadcast(event: str, data: dict):
    """向所有订阅者广播事件。"""
    msg = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    with _lock:
        dead = []
        for sid, q in _subs.items():
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(sid)
        for sid in dead:
            _subs.pop(sid, None)
