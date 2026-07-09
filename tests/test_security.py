"""kHUB 安全加固测试——CSP/限流/MIME/chunked"""

import http.client
import json
import os
import tempfile
import threading
from http.server import HTTPServer

import pytest

from khub.api import App, make_handler
from khub.db import Store
from khub.storage import ManagedLibrary


@pytest.fixture
def server():
    """启动一个临时 HTTP 服务，返回 (base_url, port)。"""
    store = Store(":memory:")
    lib = ManagedLibrary(tempfile.mkdtemp())
    app = App(store, lib)
    handler = make_handler(app)
    srv = HTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_port
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", port
    srv.shutdown()


def _get(port, path):
    """发送 GET 请求，返回 (status, headers_dict, raw_body)。"""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    headers = dict(resp.getheaders())
    body = resp.read()
    conn.close()
    return resp.status, headers, body


def _post_raw(port, path, headers_dict, body=b"{}"):
    """底层 POST：完全控制请求头，不自动修正 Content-Length。"""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.putrequest("POST", path)
    for k, v in headers_dict.items():
        conn.putheader(k, v)
    conn.endheaders(message_body=body)
    resp = conn.getresponse()
    data = resp.read()
    status = resp.status
    conn.close()
    return status, data


class TestSecurityHeaders:
    """安全响应头测试。"""

    def test_security_headers(self, server):
        _, port = server
        status, headers, _ = _get(port, "/")
        assert status == 200
        assert headers.get("Content-Type") == "text/html; charset=utf-8"
        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert headers.get("X-Frame-Options") == "DENY"
        assert headers.get("Strict-Transport-Security") == \
            "max-age=31536000; includeSubDomains"
        assert headers.get("Referrer-Policy") == "no-referrer"
        assert headers.get("Permissions-Policy") == \
            "camera=(), microphone=(), geolocation=(), interest-cohort=()"

    def test_csp_header(self, server):
        _, port = server
        status, headers, _ = _get(port, "/")
        assert status == 200
        csp = headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp


class TestBodySizeLimit:
    """请求体大小限制测试。"""

    def test_body_size_limit(self, server):
        _, port = server
        # Content-Length 略大于 10MB → 应返回 413
        large = str(10 * 1024 * 1024 + 1)
        status, data = _post_raw(port, "/documents", {
            "Content-Length": large,
            "Content-Type": "application/json",
        })
        err = json.loads(data)
        assert status == 413, f"期望 413，得到 {status}: {err}"
        assert "过大" in err.get("error", "")

    def test_body_size_limit_negative(self, server):
        _, port = server
        # Content-Length: -1 不应导致崩溃，应降级为 0 并正常返回
        status, data = _post_raw(port, "/ask", {
            "Content-Length": "-1",
            "Content-Type": "application/json",
        })
        # 只要不是 500 就算通过：-1 → 0 → 空 body → 400（无 question）
        assert status != 500, f"不应崩溃：{data}"


class TestChunkedEncoding:
    """chunked 传输拒绝测试。"""

    def test_chunked_encoding_rejected(self, server):
        _, port = server
        status, data = _post_raw(port, "/documents", {
            "Transfer-Encoding": "chunked",
            "Content-Type": "application/json",
        })
        err = json.loads(data)
        assert status == 411, f"期望 411，得到 {status}: {err}"
        assert "chunked" in err.get("error", "").lower()


class TestMimeTypes:
    """静态文件 MIME 类型测试。"""

    def test_mime_types_css(self, server):
        _, port = server
        status, headers, _ = _get(port, "/web/style.css")
        assert status == 200
        assert headers.get("Content-Type") == "text/css; charset=utf-8"

    def test_mime_types_js(self, server):
        _, port = server
        status, headers, _ = _get(port, "/web/script.js")
        assert status == 200
        assert headers.get("Content-Type") == "application/javascript; charset=utf-8"

    def test_mime_types_html(self, server):
        _, port = server
        status, headers, _ = _get(port, "/web/index.html")
        assert status == 200
        assert headers.get("Content-Type") == "text/html; charset=utf-8"

    def test_mime_types_unknown(self, server):
        _, port = server
        status, headers, body = _get(port, "/web/nonexistent.txt")
        assert status == 404, f"期望 404，得到 {status}"
