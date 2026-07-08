import sqlite3
import threading
import time
import json
import urllib.request
import tempfile
import os
from http.server import HTTPServer

from khub.api import App, make_handler
from khub.db import Store
from khub.storage import ManagedLibrary

# 使 SQLite 连接可在线程间共享（仅用于 :memory: 测试 server）
_orig_connect = sqlite3.connect
sqlite3.connect = lambda *a, **kw: _orig_connect(*a, **kw, check_same_thread=False)


def test_serve_health_endpoint():
    """实际 HTTP 服务应返回健康检查。"""
    d = tempfile.mkdtemp()
    store = Store(":memory:")
    lib = ManagedLibrary(os.path.join(d, "lib"))
    app = App(store, lib)
    httpd = HTTPServer(("127.0.0.1", 19876), make_handler(app))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(1)
    with urllib.request.urlopen("http://127.0.0.1:19876/health", timeout=5) as resp:
        data = json.loads(resp.read().decode())
    assert data["status"] == "ok"
    assert "version" in data
    httpd.shutdown()
