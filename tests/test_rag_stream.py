"""SSE 流式问答端点测试。mock LLM 流式响应，验证 HTTP Handler SSE 输出格式。"""

import json
import pytest
from unittest.mock import MagicMock, patch
from http.server import HTTPServer
import threading
import time
import urllib.request
import tempfile
import os


@pytest.fixture
def app_and_server():
    """启动 khub serve 用于集成测试。"""
    from khub.api import serve, App
    from khub.db import Store
    from khub.storage import ManagedLibrary

    store = Store()
    lib = ManagedLibrary(tempfile.mkdtemp())
    app = App(store, lib)

    # 写入测试文档
    from khub.models import CanonicalDoc
    store.store_document(CanonicalDoc(
        canonical_id="rag-test", title="测试方剂",
        content="小青龙汤：麻黄、芍药、细辛、干姜、甘草、桂枝、五味子、半夏。",
        source="test", source_id="t/r"))
    from khub.retrieval import Retriever
    Retriever(store).index_ebook("rag-test")

    from khub.api import make_handler
    handler = make_handler(app)
    server = HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", store, app
    server.shutdown()


class TestSSEAskEndpoint:
    def test_sse_response_content_type(self, app_and_server):
        """SSE 响应的 Content-Type 应为 text/event-stream。"""
        url, _, _ = app_and_server
        req = urllib.request.Request(
            url + "/ask",
            data=json.dumps({"question": "什么汤？", "k": 3, "stream": True}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req) as resp:
            assert resp.headers.get("Content-Type", "").startswith("text/event-stream")

    def test_sse_event_sequence(self, app_and_server):
        """SSE 事件顺序：sources → token(s) → done。"""
        url, _, _ = app_and_server
        req = urllib.request.Request(
            url + "/ask",
            data=json.dumps({"question": "什么汤？", "k": 3, "stream": True}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST")
        events = _read_sse(urlopen_timeout(req))
        assert len(events) >= 2  # sources + done（无 LLM 时不产生 token）
        assert events[0]["event"] == "sources"
        assert "sources" in events[0]["data"]
        assert events[-1]["event"] == "done"

    def test_sse_sources_contains_docs(self, app_and_server):
        """sources 事件应包含检索到的文档。"""
        url, _, _ = app_and_server
        req = urllib.request.Request(
            url + "/ask",
            data=json.dumps({"question": "什么汤？", "k": 3, "stream": True}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST")
        events = _read_sse(urlopen_timeout(req))
        sources_event = next(e for e in events if e["event"] == "sources")
        assert len(sources_event["data"]["sources"]) > 0
        src = sources_event["data"]["sources"][0]
        assert "id" in src
        assert "title" in src
        assert "score" in src

    def test_sse_validation_missing_question(self, app_and_server):
        """question 为空时应返回 400。"""
        url, _, _ = app_and_server
        req = urllib.request.Request(
            url + "/ask",
            data=json.dumps({"stream": True}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as e:
            assert e.code == 400
            body = json.loads(e.read())
            assert "必填" in body["error"]

    def test_sse_validation_question_too_long(self, app_and_server):
        """question 超过 2000 字符应返回 400。"""
        url, _, _ = app_and_server
        req = urllib.request.Request(
            url + "/ask",
            data=json.dumps({"question": "字" * 2001, "stream": True}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as e:
            assert e.code == 400
            body = json.loads(e.read())
            assert "2000" in body["error"]


def _parse_sse(raw: str) -> list[dict]:
    """将原始 SSE 文本解析为 [{event, data}]。"""
    blocks = raw.strip().split("\n\n")
    events = []
    for block in blocks:
        lines = block.strip().split("\n")
        event = ""
        data = {}
        for line in lines:
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if event or data:
            events.append({"event": event, "data": data})
    return events


def urlopen_timeout(req, timeout=10):
    """urllib.request.urlopen 的便捷封装。"""
    return urllib.request.urlopen(req, timeout=timeout)


def _read_sse(resp):
    """从 SSE 响应中逐行读取直到 done 事件，返回事件列表。"""
    import http.client
    events = []
    buf = ""
    while True:
        line = resp.fp.readline().decode("utf-8", errors="replace")
        if not line:
            break
        buf += line
        if line.strip() == "" and buf.strip():
            # 遇到空行 = 事件结束
            events.append(_parse_single_sse_event(buf.strip()))
            buf = ""
        if events and events[-1]["event"] == "done":
            break
    resp.close()
    return events


def _parse_single_sse_event(block: str) -> dict:
    """解析单个 SSE 事件块。"""
    lines = block.split("\n")
    event = ""
    data = {}
    for line in lines:
        if line.startswith("event: "):
            event = line[7:].strip()
        elif line.startswith("data: "):
            data = json.loads(line[6:])
    return {"event": event, "data": data}


# 单元测试：Handler._send_sse
class TestHandlerSSEUnit:
    def test_send_sse_writes_mock_stream(self):
        """验证 _send_sse 在 mock 流上写出正确的 SSE 事件。"""
        from khub.api import make_handler, App
        from khub.db import Store
        from khub.storage import ManagedLibrary
        from unittest.mock import MagicMock, patch
        import io

        store = Store()
        lib = ManagedLibrary(tempfile.mkdtemp())
        app = App(store, lib)

        # Mock handler with wfile
        handler_cls = make_handler(app)
        handler = handler_cls.__new__(handler_cls)
        handler.headers = {}
        handler.wfile = io.BytesIO()
        handler.requestline = "POST"
        handler.command = "POST"
        handler.path = "/ask"
        handler.send_response = lambda c: None
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None

        # Mock RAGEngine.ask_stream 使用 patch.object
        from khub.llm.rag import RAGEngine
        mock_stream = [
            {"event": "sources", "data": {"sources": [{"id": "d1", "title": "Doc", "score": 0.9, "snippet": "..."}]}},
            {"event": "token", "data": {"token": "答"}},
            {"event": "token", "data": {"token": "案"}},
            {"event": "done", "data": {"finish_reason": "stop"}},
        ]

        with patch.object(RAGEngine, 'ask_stream', return_value=iter(mock_stream)):
            handler._send_sse({"question": "什么？", "k": 3, "stream": True})
            output = handler.wfile.getvalue().decode("utf-8")
            events = _parse_sse(output)
            assert len(events) == 4
            assert events[0]["event"] == "sources"
            assert events[-1]["event"] == "done"
