import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .db import Store
from .ingest import ingest_ebook, register_ebook
from .storage import ManagedLibrary


class App:
    """薄 REST 层：直接复用核心库 API，不重写业务逻辑。"""

    def __init__(self, store: Store, library: ManagedLibrary):
        self.store = store
        self.library = library

    def dispatch(self, method: str, raw_path: str, body: Optional[dict] = None):
        parsed = urlparse(raw_path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        body = body or {}

        if method == "GET" and path == "/ebooks":
            return 200, self.store.list_ebooks()

        if method == "POST" and path == "/ebooks/register":
            cid = register_ebook(self.store, self.library, body["path"],
                                 move=bool(body.get("move")))
            return 201, {"canonical_id": cid}

        if method == "POST" and path.endswith("/ingest"):
            prefix = "/ebooks/"
            if path.startswith(prefix) and path.endswith("/ingest"):
                cid = path[len(prefix):-len("/ingest")]
                vid = ingest_ebook(self.store, cid)
                return 200, {"canonical_id": cid, "version_id": vid}
            return 404, {"error": "not found"}

        if method == "GET" and path == "/search":
            q = qs.get("q", [""])[0]
            return 200, [{"doc_id": d, "title": t, "snippet": s}
                         for d, t, s in self.store.search(q)]

        return 404, {"error": "not found"}


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            try:
                code, obj = app.dispatch("GET", self.path)
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": str(e)})
            self._send(code, obj)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return self._send(400, {"error": "bad json"})
            try:
                code, obj = app.dispatch("POST", self.path, body)
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": str(e)})
            self._send(code, obj)

        def log_message(self, *args):
            pass

    return Handler


def serve(store: Store, library: ManagedLibrary, host: str = "127.0.0.1", port: int = 8000):
    app = App(store, library)
    httpd = HTTPServer((host, port), make_handler(app))
    httpd.serve_forever()
