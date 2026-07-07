import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .db import Store
from .ingest import ingest_ebook, register_ebook
from .models import CanonicalDoc
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

        # ---- OCR / KZOCR 文档入库（直接收内容，不依赖原始文件） ----
        if method == "POST" and path == "/documents":
            if not body.get("title") or not body.get("content"):
                return 400, {"error": "title 与 content 必填"}
            doc = CanonicalDoc(
                canonical_id=body.get("source_id") or f"kzocr-{int(time.time()*1000)}",
                title=body["title"],
                content=body["content"],
                source=body.get("source", "KZOCR"),
                source_id=body.get("source_id") or "",
                origin="kzocr",
                format=body.get("format", "markdown"),
                updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                note=json.dumps(body.get("metadata") or {}, ensure_ascii=False),
                doc_type=body.get("doc_type", "raw"),
            )
            version_id = self.store.store_document(doc)
            return 201, {"status": "ok", "doc_id": doc.canonical_id,
                         "version_id": version_id, "message": "document ingested"}

        # ---- Exam subsystem ----
        if method == "POST" and path == "/exam/questions":
            from .exam.models import Question
            from .exam.store import add_question
            q = Question(kind=body.get("kind", "mcq"), stem=body.get("stem", ""),
                         options=body.get("options", []), answer=body.get("answer", ""),
                         explanation=body.get("explanation", ""),
                         source_doc=body.get("source_doc", ""))
            qid = add_question(self.store, q)
            return 201, {"id": qid}

        if method == "GET" and path == "/exam/questions":
            from .exam.store import list_questions
            kind = qs.get("kind", [None])[0]
            return 200, [vars(q) for q in list_questions(self.store, kind)]

        if method == "POST" and path == "/exam/generate":
            from .exam.generator import generate
            topic = body.get("topic", "")
            source_doc = body.get("source_doc", "")
            q = generate(topic, source_doc=source_doc)
            return 200, vars(q)

        # ---- Clinical subsystem ----
        if method == "POST" and path == "/clinical/patients":
            from .clinical.patients import add_patient
            pid = add_patient(self.store, body["id"], body["name"],
                              gender=body.get("gender", ""), born=body.get("born", ""))
            return 201, {"id": pid}

        if method == "GET" and path == "/clinical/patients":
            from .clinical.patients import list_patients
            return 200, list_patients(self.store)

        if method == "POST" and path == "/clinical/records":
            from .clinical.records import add_record
            rid = add_record(self.store, body["patient_id"],
                             diagnosis=body.get("diagnosis", ""),
                             prescription=body.get("prescription", ""),
                             note=body.get("note", ""))
            return 201, {"id": rid}

        if method == "POST" and path == "/clinical/consultations":
            from .clinical.consultations import add_consultation
            cid = add_consultation(self.store, body["patient_id"],
                                   chief_complaint=body.get("chief_complaint", ""),
                                   tongue_pulse=body.get("tongue_pulse", ""),
                                   differentiation=body.get("differentiation", ""),
                                   plan=body.get("plan", ""))
            return 201, {"id": cid}

        if method == "POST" and path.startswith("/clinical/twin/") and path.endswith("/summarize"):
            pid = path[len("/clinical/twin/"):-len("/summarize")]
            from .clinical.records import init as init_records
            from .clinical.consultations import init as init_consultations
            from .clinical.twin import build_summary
            init_records(self.store)
            init_consultations(self.store)
            text = build_summary(self.store, pid)
            return 200, {"patient_id": pid, "summary": text}

        # ---- Ops subsystem ----
        if method == "POST" and path == "/ops/schedules":
            from .ops.store import add_schedule
            sid = add_schedule(self.store, body["date"], body["doctor"], body["slot"])
            return 201, {"id": sid}

        if method == "POST" and path == "/ops/appointments":
            from .ops.store import book_appointment
            aid = book_appointment(self.store, body["patient_id"], body["date"], body["doctor"])
            return 201, {"id": aid}

        if method == "POST" and path == "/ops/visits":
            from .ops.store import checkin_visit
            vid = checkin_visit(self.store, body["appointment_id"], body["patient_id"],
                                note=body.get("note", ""))
            return 201, {"id": vid}

        if method == "GET" and path == "/ops/appointments":
            from .ops.store import list_appointments
            date = qs.get("date", [None])[0]
            return 200, list_appointments(self.store, date)

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
