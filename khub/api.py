import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse, unquote

from . import __version__
from .db import Store
from .ingest import ingest_ebook, register_ebook
from .log import get_logger
from .models import CanonicalDoc
from .ratelimit import make_ratelimit, PersistentTokenBucket
from .storage import ManagedLibrary

# 请求体大小限制（10MB）
_MAX_BODY_SIZE = 10 * 1024 * 1024

# 静态文件 MIME 类型映射
_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".json": "application/json",
}


def _safe_int(value, default: int) -> int:
    """把查询参数安全转 int，失败回退默认，避免非法输入抛 500。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class App:
    """薄 REST 层：直接复用核心库 API，不重写业务逻辑。"""

    def __init__(self, store: Store, library: ManagedLibrary):
        self.store = store
        self.library = library
        self._started = time.time()
        self.ratelimit: PersistentTokenBucket | None = make_ratelimit(store)

    def dispatch(self, method: str, raw_path: str, body: Optional[dict] = None,
                 auth_header: str = ""):
        # 鉴权（可选，由 KHUB_API_TOKEN 环境变量控制）：一旦配置，所有方法（含读）均需 Bearer 令牌，
        # 避免本地任意进程裸读病历/问诊等 PII。未配置则不鉴权（仅本地使用）。
        token = os.environ.get("KHUB_API_TOKEN")
        if token and auth_header != f"Bearer {token}":
            return 401, {"error": "unauthorized"}
        parsed = urlparse(raw_path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        body = body or {}

        # ---- Static file serving (web/ directory, path traversal protected) ----
        if method == "GET" and path.startswith("/web/"):
            filename = path[len("/web/"):]
            web_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "web"))
            filepath = os.path.realpath(os.path.join(web_dir, filename))
            if not filepath.startswith(web_dir + os.sep):
                return 404, {"error": "bad path"}
            if not os.path.isfile(filepath):
                return 404, {"error": "not found"}
            with open(filepath, "rb") as f:
                ctype = _MIME.get(os.path.splitext(filename)[1].lower(), "application/octet-stream")
                return 200, f.read(), ctype

        if method == "GET" and path == "/health":
            uptime = round(time.time() - self._started, 1) if self._started else 0
            return 200, {"status": "ok", "version": __version__,
                         "documents": self.store.conn.execute(
                             "SELECT count(*) FROM documents").fetchone()[0],
                         "uptime_sec": uptime}

        if method == "GET" and path == "/stats":
            cur = self.store.conn
            total = cur.execute("SELECT count(*) FROM documents").fetchone()[0]
            source_counts: dict[str, int] = {}
            for row in cur.execute("SELECT source_ids FROM documents").fetchall():
                ids = row["source_ids"] or "[]"
                try:
                    parsed = json.loads(ids)
                    first = parsed[0] if isinstance(parsed, list) and parsed else None
                except (json.JSONDecodeError, IndexError, TypeError):
                    first = None
                if first in ("obsidian", "ima", "imanote", "quip", "kzocr", "library", "feishu", "webui"):
                    source_counts[first] = source_counts.get(first, 0) + 1
            today = time.strftime("%Y-%m-%d")
            today_count = cur.execute(
                "SELECT count(*) FROM documents WHERE updated_at >= ?",
                (today,)).fetchone()[0]

            # 近 7 天每日入库趋势 + 额外统计（表不存在时容错）
            weekly = []
            version_count = 0
            embed_count = 0
            conflict_count = 0
            try:
                import datetime as _dt
                for i in range(6, -1, -1):
                    day = (_dt.date.today() - _dt.timedelta(days=i)).isoformat()
                    cnt = cur.execute(
                        "SELECT count(*) FROM documents WHERE updated_at >= ? AND updated_at < ?",
                        (day, (_dt.date.today() - _dt.timedelta(days=i - 1)).isoformat())
                    ).fetchone()[0]
                    weekly.append({"date": day, "count": cnt})
                version_count = cur.execute(
                    "SELECT count(*) FROM document_versions").fetchone()[0]
                embed_count = cur.execute(
                    "SELECT count(*) FROM embeddings").fetchone()[0]
                conflict_count = cur.execute(
                    "SELECT count(*) FROM documents WHERE conflict=1").fetchone()[0]
            except Exception:
                pass

            recent = cur.execute(
                "SELECT canonical_id, title, updated_at FROM documents "
                "ORDER BY updated_at DESC LIMIT 5").fetchall()
            return 200, {
                "total": total,
                "sources": source_counts,
                "today": today_count,
                "weekly": weekly,
                "versions": version_count,
                "embeddings": embed_count,
                "conflicts": conflict_count,
                "recent": [{"id": r["canonical_id"], "title": r["title"], "at": r["updated_at"]}
                           for r in recent],
            }

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
            page = _safe_int(qs.get("page", ["0"])[0], 0)
            per = _safe_int(qs.get("per", ["50"])[0], 50)
            source = qs.get("source", [""])[0]
            hits, total = self.store.search(q, page=page, per_page=per, source=source)
            return 200, {"hits": [{"doc_id": d, "title": t, "snippet": s}
                                   for d, t, s in hits],
                         "total": total, "page": page, "per_page": per}

        if method == "GET" and path == "/documents":
            rows = self.store.conn.execute(
                "SELECT canonical_id, title, updated_at, source_ids FROM documents "
                "ORDER BY updated_at DESC").fetchall()
            return 200, [dict(r) for r in rows]

        if method == "GET" and path.startswith("/documents/") and len(path) > len("/documents/"):
            rest = path[len("/documents/"):]
            parts = rest.split("/", 2)
            cid = unquote(parts[0])

            # GET /documents/{id}/versions/{vid}
            if len(parts) >= 3 and parts[1] == "versions" and parts[2]:
                vid = _safe_int(parts[2], 0)
                if not vid:
                    return 400, {"error": "invalid version_id"}
                ver = self.store.get_version(cid, vid)
                if not ver:
                    return 404, {"error": "version not found"}
                return 200, {
                    "version_id": ver["version_id"],
                    "content": ver["content"][:100000],
                    "format": ver.get("format", "plain"),
                    "updated_at": ver["updated_at"],
                }

            # GET /documents/{id}/versions
            if len(parts) >= 2 and parts[1] == "versions":
                vers = self.store.get_versions(cid)
                return 200, [{
                    "version_id": v["version_id"],
                    "updated_at": v["updated_at"],
                    "format": v.get("format", "plain"),
                } for v in vers]

            # GET /documents/{id}/diff?v1=X&v2=Y — 版本差异对比
            if len(parts) >= 2 and parts[1] == "diff":
                from .diff import diff_lines, diff_to_html
                v1 = _safe_int(qs.get("v1", [0])[0], 0)
                v2 = _safe_int(qs.get("v2", [0])[0], 0)
                if not v1 or not v2 or v1 < 0 or v2 < 0:
                    return 400, {"error": "请指定有效的 v1 和 v2（版本 ID）"}
                ver1 = self.store.get_version(cid, v1)
                ver2 = self.store.get_version(cid, v2)
                if not ver1 or not ver2:
                    return 404, {"error": "版本不存在"}
                # 限 5000 行，防大文档 OOM
                c1_lines = (ver1["content"] or "").splitlines()
                c2_lines = (ver2["content"] or "").splitlines()
                if len(c1_lines) > 5000 or len(c2_lines) > 5000:
                    return 413, {"error": "文档过大，无法比较（超过 5000 行上限）"}
                c1 = "\n".join(c1_lines)
                c2 = "\n".join(c2_lines)
                diff = diff_lines(c1, c2)
                return 200, {
                    "canonical_id": cid,
                    "v1": v1, "v2": v2,
                    "v1_updated": ver1["updated_at"],
                    "v2_updated": ver2["updated_at"],
                    "diff": diff,
                    "diff_html": diff_to_html(diff),
                    "changes": sum(1 for d in diff if d["type"] != "equal"),
                }

            # GET /documents/{id}
            doc = self.store.get_document(cid)
            if doc is None:
                return 404, {"error": "not found"}
            vers = self.store.get_versions(cid)
            content = vers[-1]["content"] if vers else ""
            fmt = vers[-1]["format"] if (vers and "format" in vers[-1]) else "plain"
            # 安全：format=html 时剥离危险标签，仅保留安全富文本子集
            if fmt == "html":
                import re as _re
                safe_tags = r"p|br|b|i|u|em|strong|h[1-6]|ul|ol|li|div|span|pre|code|blockquote|table|tr|td|th|a"
                content = _re.sub(r"(?s)<(?!\/?(?:" + safe_tags + r")(?:\s[^>]*)?>)[^>]*>", "", content)
                content = _re.sub(r"(?s)<(script|style|iframe|object|embed|form|input|select|textarea|button|svg|math)[^>]*>.*?</\1>", "", content)
                content = _re.sub(r'\s+on\w+\s*=\s*["\'][^"\']*["\']', "", content)
                content = _re.sub(r'\s+on\w+\s*=\S+', "", content)
                content = _re.sub(r'href\s*=\s*["\']javascript:', "href='#'", content, flags=_re.I)
            return 200, {
                "canonical_id": doc["canonical_id"],
                "title": doc["title"],
                "content": content[:100000],
                "version_count": len(vers),
                "source_ids": doc["source_ids"],
                "created_at": doc["created_at"],
                "updated_at": doc["updated_at"],
                "format": fmt,
            }

        # PUT /documents/{id} — 更新文档
        if method == "PUT" and path.startswith("/documents/") and len(path) > len("/documents/"):
            rest = path[len("/documents/"):]
            if "/" in rest:
                return 400, {"error": "invalid document id (path too deep)"}
            cid = unquote(rest)
            title = (body or {}).get("title", "").strip()
            new_content = (body or {}).get("content", "").strip()
            if not title or not new_content:
                return 400, {"error": "title 与 content 必填"}
            doc = CanonicalDoc(
                canonical_id=cid,
                title=title,
                content=new_content,
                source="webui",
                source_id="",
                origin="webui",
                format=body.get("format", "plain"),
                updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            )
            version_id = self.store.store_document(doc)
            # 编辑文档时自动清除冲突标记（如有）
            self.store.conn.execute(
                "UPDATE documents SET conflict=0 WHERE canonical_id=? AND conflict=1",
                (cid,))
            self.store.conn.commit()
            return 200, {"status": "ok", "version_id": version_id}

        # POST /documents/{id}/resolve — 解决冲突
        if method == "POST" and path.endswith("/resolve"):
            cid = unquote(path[len("/documents/"):-len("/resolve")])
            keep_id = (body or {}).get("keep_version")
            if not keep_id:
                return 400, {"error": "keep_version 必填"}
            try:
                keep_id = int(keep_id)
            except (TypeError, ValueError):
                return 400, {"error": "keep_version 必须是有效整数"}
            try:
                self.store.resolve_conflict(cid, keep_id)
            except ValueError as exc:
                return 400, {"error": str(exc)}
            return 200, {"status": "ok"}

        if method == "GET" and path == "/conflicts":
            rows = self.store.conn.execute(
                "SELECT canonical_id, title FROM documents WHERE conflict=1").fetchall()
            return 200, [dict(r) for r in rows]

        if method == "GET" and path == "/semantic":
            from .retrieval import Retriever
            q = qs.get("q", [""])[0]
            k = _safe_int(qs.get("k", ["5"])[0], 5)
            hits = Retriever(self.store).search_similar(q, k=k)
            return 200, [{"doc_id": d, "score": round(s, 4)} for d, s in hits]

        # ---- 数据源同步状态 ----
        if method == "GET" and path == "/sync-status":
            rows = self.store.conn.execute(
                "SELECT source_id, MAX(last_sync_at) AS last_sync_at, direction "
                "FROM sync_states GROUP BY source_id ORDER BY source_id"
            ).fetchall()
            import datetime as _dt
            now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
            results = []
            for r in rows:
                last_sync = r["last_sync_at"]
                recent = False
                if last_sync:
                    try:
                        sync_time = _dt.datetime.fromisoformat(last_sync)
                        recent = (now - sync_time).total_seconds() < 86400  # 24h
                    except (ValueError, TypeError):
                        pass
                results.append({
                    "source_id": r["source_id"],
                    "last_sync_at": last_sync,
                    "direction": r["direction"],
                    "recent": recent,
                })
            return 200, results

        # ---- RAG 问答 ----
        if method == "POST" and path == "/ask":
            from .llm.rag import RAGEngine
            question = (body or {}).get("question", "").strip()
            if not question:
                return 400, {"error": "question 必填"}
            if len(question) > 2000:
                return 400, {"error": "question 超过 2000 字符上限"}
            if body.get("stream"):
                # 流式请求由 Handler 的 _send_sse 处理，此处不处理
                return 400, {"error": "流式请求请通过 SSE 端点（stream=true）"}
            k = _safe_int(body.get("k", 5), 5)
            k = max(1, min(k, 20))  # 范围 1–20
            engine = RAGEngine(self.store)
            answer, sources = engine.ask(question, k=k)
            return 200, {"answer": answer, "sources": sources}

        if method == "GET" and path == "/":
            return 200, self._html_page(), "text/html; charset=utf-8"

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
            try:
                from .retrieval import Retriever
                Retriever(self.store).index_ebook(doc.canonical_id)
            except Exception:  # 向量化失败不影响入库
                pass
            return 201, {"status": "ok", "doc_id": doc.canonical_id,
                         "version_id": version_id, "message": "document ingested"}

        # ---- Exam subsystem ----
        if method == "POST" and path == "/exam/questions":
            from .exam.models import Question
            from .exam.store import add_question
            exam_q = Question(kind=body.get("kind", "mcq"), stem=body.get("stem", ""),
                         options=body.get("options", []), answer=body.get("answer", ""),
                         explanation=body.get("explanation", ""),
                         source_doc=body.get("source_doc", ""))
            qid = add_question(self.store, exam_q)
            return 201, {"id": qid}

        if method == "GET" and path == "/exam/questions":
            from .exam.store import list_questions
            kind = qs.get("kind", [None])[0]
            return 200, [vars(q) for q in list_questions(self.store, kind)]

        if method == "POST" and path == "/exam/generate":
            from .exam.generator import generate
            topic = body.get("topic", "")
            source_doc = body.get("source_doc", "")
            exam_q = generate(topic, source_doc=source_doc)
            return 200, vars(exam_q)

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

    @staticmethod
    def _html_page():
        """加载外部化的 Web UI 页面（khub/web/index.html）。"""
        page_path = os.path.join(os.path.dirname(__file__), "web", "index.html")
        try:
            with open(page_path, encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return "<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>" \
                   "<title>kHUB</title></head><body><p>Web UI not found.</p></body></html>"





def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, obj, ctype="application/json; charset=utf-8",
                  retry_after=None):
            if ctype.startswith("application/json"):
                data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            else:
                data = obj.encode("utf-8") if isinstance(obj, str) else obj
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            # 安全响应头
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy",
                "camera=(), microphone=(), geolocation=(), interest-cohort=()")
            self.send_header("Strict-Transport-Security",
                "max-age=31536000; includeSubDomains")
            if ctype == "text/html; charset=utf-8":
                self.send_header("Content-Security-Policy",
                    "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                    "style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data:; form-action 'none'; "
                    "frame-ancestors 'none'; base-uri 'self'; object-src 'none'")
            if retry_after is not None:
                self.send_header("Retry-After", str(int(retry_after)))
            self.end_headers()
            self.wfile.write(data)

        def _send_sse(self, body):
            """处理 SSE 流式问答请求。body: dict"""
            token = os.environ.get("KHUB_API_TOKEN")
            if token and self.headers.get("Authorization", "") != f"Bearer {token}":
                return self._send(401, {"error": "unauthorized"})

            question = (body or {}).get("question", "").strip()
            if not question:
                return self._send(400, {"error": "question 必填"})
            if len(question) > 2000:
                return self._send(400, {"error": "question 超过 2000 字符上限"})
            k = body.get("k", 5)
            if not isinstance(k, (int, float)):
                k = 5
            k = max(1, min(int(k), 20))

            from .llm.rag import RAGEngine
            engine = RAGEngine(app.store)

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            try:
                for event in engine.ask_stream(question, k=k):
                    ev = event["event"]
                    data = json.dumps(event["data"], ensure_ascii=False)
                    line = f"event: {ev}\ndata: {data}\n\n"
                    self.wfile.write(line.encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass  # 客户端断开，静默结束

        def do_GET(self):
            if app.ratelimit is not None:
                client_ip = self.client_address[0]
                if not app.ratelimit.allow(client_ip):
                    return self._send(429, {"error": "too many requests"},
                                      retry_after=1)
            try:
                res = app.dispatch("GET", self.path,
                                   auth_header=self.headers.get("Authorization", ""))
                if len(res) == 3:
                    code, obj, ctype = res
                else:
                    code, obj, ctype = res[0], res[1], "application/json; charset=utf-8"
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": str(e)})
            self._send(code, obj, ctype)

        def do_POST(self):
            if app.ratelimit is not None:
                client_ip = self.client_address[0]
                if not app.ratelimit.allow(client_ip):
                    return self._send(429, {"error": "too many requests"},
                                      retry_after=1)
            if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
                return self._send(411, {"error": "请使用 Content-Length，不接受 Transfer-Encoding: chunked"})
            length = self.headers.get("Content-Length", "0")
            try:
                length = int(length)
            except (TypeError, ValueError):
                length = 0
            if length < 0:
                length = 0
            if length > _MAX_BODY_SIZE:
                return self._send(413, {"error": "请求体过大（上限 10MB）"})
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return self._send(400, {"error": "bad json"})

            # 流式 RAG 问答：不走 dispatch（SSE 需直接写 wfile）
            if body and body.get("stream") and self.path == "/ask":
                return self._send_sse(body)

            try:
                res = app.dispatch("POST", self.path, body,
                                   auth_header=self.headers.get("Authorization", ""))
                if len(res) == 3:
                    code, obj, ctype = res
                else:
                    code, obj, ctype = res[0], res[1], "application/json; charset=utf-8"
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": str(e)})
            self._send(code, obj, ctype)

        def do_OPTIONS(self):
            """CORS preflight 处理。"""
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods",
                             "GET, POST, PUT, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers",
                             "Content-Type, Authorization")
            self.end_headers()

        def do_PUT(self):
            if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
                return self._send(411, {"error": "请使用 Content-Length，不接受 Transfer-Encoding: chunked"})
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except (TypeError, ValueError):
                length = 0
            if length < 0:
                length = 0
            if length > _MAX_BODY_SIZE:
                return self._send(413, {"error": "请求体过大（上限 10MB）"})
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return self._send(400, {"error": "bad json"})
            try:
                res = app.dispatch("PUT", self.path, body,
                                   auth_header=self.headers.get("Authorization", ""))
                if len(res) == 3:
                    code, obj, ctype = res
                else:
                    code, obj, ctype = res[0], res[1], "application/json; charset=utf-8"
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": str(e)})
            self._send(code, obj, ctype)

        def do_DELETE(self):
            if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
                return self._send(411, {"error": "请使用 Content-Length，不接受 Transfer-Encoding: chunked"})
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except (TypeError, ValueError):
                length = 0
            if length < 0:
                length = 0
            if length > _MAX_BODY_SIZE:
                return self._send(413, {"error": "请求体过大（上限 10MB）"})
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return self._send(400, {"error": "bad json"})
            try:
                res = app.dispatch("DELETE", self.path, body,
                                   auth_header=self.headers.get("Authorization", ""))
                if len(res) == 3:
                    code, obj, ctype = res
                else:
                    code, obj, ctype = res[0], res[1], "application/json; charset=utf-8"
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": str(e)})
            self._send(code, obj, ctype)

        def log_message(self, *args):
            pass

    return Handler


def serve(store: Store, library: ManagedLibrary, host: str = "127.0.0.1", port: int = 8000):
    app = App(store, library)
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    import signal

    def _stop(*a):
        print("\n收到停止信号，正在关闭...")
        httpd.shutdown()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    print(f"kHUB API → http://{host}:{port}  (pid={os.getpid()})")
    httpd.serve_forever()
