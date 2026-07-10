import json
import os
import queue
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse, unquote

# 请求计数器（用于 /metrics）
_REQUESTS: dict[str, int] = {"GET": 0, "POST": 0, "PUT": 0, "DELETE": 0}
# 0.5.1 启动时间戳（用于 /api/info）
_START = time.time()

from . import __version__
from .db import Store
from .ingest import ingest_ebook, register_ebook
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


def _apply_scope(sql: str, clause: str) -> str:
    """将 scope_filter 子句拼接到 SQL 语句中。"""
    if not clause:
        return sql
    if "WHERE" in sql.upper():
        return sql + f" AND {clause}"
    return sql + f" WHERE {clause}"


class App:
    """薄 REST 层：直接复用核心库 API，不重写业务逻辑。"""

    def __init__(self, store: Store, library: Optional[ManagedLibrary] = None):
        self.store = store
        self.library = library
        self._started = time.time()
        self.ratelimit: PersistentTokenBucket | None = make_ratelimit(store)

    def dispatch(self, method: str, raw_path: str, body: Optional[dict] = None,
                 auth_header: str = "", tenant_header: str = ""):
        parsed = urlparse(raw_path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        body = body or {}
        # 0.3.0 auth: /auth/login 允许匿名访问
        if method == "POST" and path == "/auth/login":
            from .auth import authenticate, issue_token
            user = authenticate(self.store, body.get("username", ""), body.get("password", ""))
            if not user:
                return 401, {"error": "用户名或密码错误"}
            token = issue_token(self.store, user["user_id"])
            return 200, {"token": token, "user": user}
        # i18n — 允许匿名访问（登录页也需要翻译）
        if method == "GET" and path == "/api/i18n":
            from .i18n import detect_lang, get_translations
            al = auth_header or qs.get("lang", [""])[0]
            lang = detect_lang(al)
            return 200, {"lang": lang, "translations": get_translations(lang)}

        # 鉴权
        from .auth import get_current_user
        current_user = get_current_user(self.store, auth_header)
        if not current_user:
            return 401, {"error": "unauthorized", "error_code": "AUTH_001", "message": "请提供有效的认证令牌"}
        # 将当前用户存入请求上下文供后续端点使用
        setattr(self, "_current_user", current_user)
        # 租户检测（0.9.1）
        from .tenants import detect_tenant
        current_tenant = detect_tenant(self.store, tenant_header)
        setattr(self, "_current_tenant", current_tenant)
        # RBAC 权限检查
        from .auth import check_permission
        _resource_map = {
            "/twin": "patients", "/patients": "patients", "/records": "records",
            "/consultations": "consultations", "/appointments": "appointments",
            "/api/courses": "courses", "/api/wechat": "wechat",
            "/tags": "tags", "/favorites": "favorites",
            "/stats": "stats", "/sync-status": "stats",
            "/exam": "exam", "/api/users": "users",
            "/documents": "docs", "/search": "docs", "/semantic": "docs",
            "/api/telemedicine": "telemedicine", "/api/prescriptions": "prescriptions",
        }
        _action_map = {"GET": "read", "POST": "create", "PUT": "update", "DELETE": "delete"}
        _public_paths = ("/auth/login", "/web/", "/health", "/api/info",
                         "/api/openapi.json", "/api/docs",
                         "/api/compliance/")
        skip_check = any(path.startswith(p) for p in _public_paths)
        if not skip_check:
            resource = None
            for prefix, rsrc in _resource_map.items():
                if path.startswith(prefix) or path.startswith("/api" + prefix):
                    resource = rsrc
                    break
            if resource:
                action = _action_map.get(method, "read")
                if not check_permission(current_user, resource, action):
                    return 403, {"error": "permission_denied", "error_code": "AUTH_002", "message": "权限不足"}
        # 请求计数器
        _REQUESTS[method] = _REQUESTS.get(method, 0) + 1

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
            checks: dict[str, dict] = {}
            overall = "ok"
            # DB
            try:
                c = self.store.conn.execute("SELECT count(*) FROM documents").fetchone()[0]
                checks["db"] = {"ok": True, "documents": c}
            except Exception as e:
                checks["db"] = {"ok": False, "error": str(e)}
                overall = "degraded"
            # FTS
            try:
                self.store.conn.execute("SELECT count(*) FROM docs_fts").fetchone()
                checks["fts"] = {"ok": True}
            except Exception:
                checks["fts"] = {"ok": False}
                overall = "degraded"
            # 磁盘
            try:
                lib = os.environ.get("KHUB_LIBRARY", os.path.expanduser("~/.khub"))
                st = os.statvfs(lib)
                free_mb = st.f_bavail * st.f_frsize / 1024 / 1024
                checks["disk"] = {"ok": free_mb > 100, "free_mb": round(free_mb, 1)}
                if free_mb <= 100:
                    overall = "degraded"
            except Exception:
                checks["disk"] = {"ok": True, "note": "unavailable"}
            # WAL 堆积
            try:
                pend = self.store.conn.execute(
                    "SELECT count(*) FROM replication_log WHERE applied=0").fetchone()[0]
                checks["wal"] = {"ok": pend < 1000, "pending": pend}
                if pend >= 1000:
                    overall = "degraded"
            except Exception:
                checks["wal"] = {"ok": True, "note": "unavailable"}
            return 200, {"status": overall, "version": __version__,
                         "uptime_sec": int(time.time() - self._started), "checks": checks}

        if method == "GET" and path == "/stats":
            from .cache import get as _cache_get, set as _cache_set
            cached = _cache_get("stats")
            if cached is not None:
                return 200, cached
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
            except Exception:  # nosec B110
                pass

            recent = cur.execute(
                "SELECT canonical_id, title, updated_at FROM documents "
                "ORDER BY updated_at DESC LIMIT 5").fetchall()
            stats = {
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
            # 运营统计（表不存在时容错）
            try:
                from khub.ops.store import book_appointment as _unused_ops
                apts = cur.execute(
                    "SELECT status, count(*) as c FROM appointments GROUP BY status").fetchall()
                slots_total = cur.execute("SELECT count(*) FROM schedules").fetchone()[0] or 0
                slots_booked = cur.execute(
                    "SELECT count(*) FROM appointments WHERE status IN ('booked','checked_in')").fetchone()[0] or 0
                stats["appointments_by_status"] = {r["status"]: r["c"] for r in apts}
                stats["schedules_coverage"] = {
                    "total_slots": slots_total,
                    "booked_slots": slots_booked,
                    "utilization": round(slots_booked / max(slots_total, 1), 4)
                }
            except Exception:  # nosec B110 — ops 表可能未创建
                pass
            # 扩展统计
            try:
                db_path = os.environ.get("KHUB_DB", "")
                if db_path and os.path.isfile(db_path):
                    stats["db_file_size_mb"] = round(os.path.getsize(db_path) / 1024 / 1024, 1)
            except Exception:
                pass
            try:
                pend = self.store.conn.execute(
                    "SELECT count(*) FROM replication_log WHERE applied=0").fetchone()[0]
                stats["wal_pending_count"] = pend
            except Exception:
                pass
            # 业务表行数（容错，表可能不存在）
            for tbl in ("twin_versions", "consult_messages", "followup_plans", "record_struct"):
                try:
                    cnt = self.store.conn.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
                    stats[f"table_rows.{tbl}"] = cnt
                except Exception:
                    pass
            _cache_set("stats", stats, ttl=5)
            return 200, stats

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
            cursor = qs.get("cursor", [None])[0]
            if cursor:
                limit = min(int(qs.get("per", ["20"])[0]), 100)
                rows = self.store.conn.execute(
                    "SELECT d.canonical_id as id, d.title, d.updated_at FROM documents d "
                    "WHERE (d.title LIKE ? OR d.canonical_id LIKE ?) "
                    "AND d.updated_at < ? ORDER BY d.updated_at DESC LIMIT ?",
                    (f"%{q}%", f"%{q}%", cursor, limit)).fetchall()
                next_cursor = rows[-1]["updated_at"] if len(rows) == limit else None
                return 200, {"results": [dict(r) for r in rows], "next_cursor": next_cursor}
            page = _safe_int(qs.get("page", ["0"])[0], 0)
            per = _safe_int(qs.get("per", ["50"])[0], 50)
            source = qs.get("source", [""])[0]
            tag_filter = qs.get("tag", [None])[0]
            if tag_filter:
                tagged_ids = [r["doc_id"] for r in self.store.conn.execute(
                    "SELECT doc_id FROM doc_tags WHERE tag=?", (tag_filter,)).fetchall()]
                if not tagged_ids:
                    return 200, {"hits": [], "total": 0, "page": page, "per_page": per}
                hits, total = self.store.search(q, page=page, per_page=per, source=source)
                id_set = set(tagged_ids)
                hits = [(d, t, s) for d, t, s in hits if d in id_set]
                total = len(hits)
                hits = hits[page * per: (page + 1) * per]
            else:
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

            # GET /documents/{id}/tags
            if len(parts) >= 3 and parts[1] == "tags":
                from .tags import get_doc_tags
                return 200, {"tags": get_doc_tags(self.store, cid)}

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
            # 0.2.9 Markdown 渲染
            if fmt == "markdown" and content:
                try:
                    import markdown as _md
                    content = _md.markdown(content, extensions=["fenced_code", "codehilite"])
                    fmt = "html"
                except ImportError:
                    pass
            from .tags import get_doc_tags
            from .favorites import is_favorite
            result = {
                "canonical_id": doc["canonical_id"],
                "title": doc["title"],
                "content": content[:100000],
                "version_count": len(vers),
                "source_ids": doc["source_ids"],
                "created_at": doc["created_at"],
                "updated_at": doc["updated_at"],
                "format": fmt,
                "tags": get_doc_tags(self.store, cid),
                "favorited": is_favorite(self.store, cid),
            }
            return 200, result

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
            fmt = body.get("format")
            if not fmt:
                doc_row = self.store.conn.execute(
                    "SELECT current_version FROM documents WHERE canonical_id=?", (cid,)).fetchone()
                if doc_row and doc_row["current_version"]:
                    cur_ver = self.store.get_version(cid, doc_row["current_version"])
                    fmt = (cur_ver or {}).get("format", "plain")
                else:
                    fmt = "plain"
            doc = CanonicalDoc(
                canonical_id=cid,
                title=title,
                content=new_content,
                source="webui",
                source_id="",
                origin="webui",
                format=fmt,
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
            source_filter = body.get("source_filter")
            engine = RAGEngine(self.store)
            answer, sources = engine.ask(question, k=k, source_filter=source_filter)
            return 200, {
                "answer": answer,
                "sources": [
                    {"title": s.get("title", ""), "doc_id": s.get("id", ""),
                     "score": s.get("score", 0), "source": s.get("source_ids", "")}
                    for s in sources
                ],
            }

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
            except Exception:  # 向量化失败不影响入库  # nosec B110
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
            cu = getattr(self, "_current_user", None)
            return 200, list_patients(self.store, user=cu)

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

        # 0.4.1 miniapp — consultations list
        if method == "GET" and path == "/clinical/consultations":
            pid = qs.get("patient_id", [None])[0]
            if pid and pid.isdigit():
                rows = self.store.conn.execute(
                    "SELECT id, patient_id, date, chief_complaint, differentiation, plan "
                    "FROM consultations WHERE patient_id=? ORDER BY date DESC",
                    (int(pid),)
                ).fetchall()
            else:
                rows = self.store.conn.execute(
                    "SELECT id, patient_id, date, chief_complaint, differentiation "
                    "FROM consultations ORDER BY date DESC LIMIT 50"
                ).fetchall()
            return 200, {"consultations": rows}

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
            pid_param = qs.get("patient_id", [None])[0]
            patient_id = int(pid_param) if (pid_param and pid_param.isdigit()) else None
            cu = getattr(self, "_current_user", None)
            return 200, list_appointments(self.store, date, user=cu, patient_id=patient_id)

        if method == "GET" and path == "/ops/schedules":
            from .ops.store import list_schedules
            date = qs.get("date", [None])[0]
            return 200, {"schedules": list_schedules(self.store, date)}

        # 0.2.7 clinical 增强 — 孪生摘要
        if method == "GET" and path.startswith("/twin/") and len(path) > len("/twin/"):
            pid_str = path[len("/twin/"):]
            if "/" in pid_str:
                return 404, {"error": "not found"}
            pid = _safe_int(pid_str, 0)
            if not pid:
                return 400, {"error": "invalid patient_id"}
            from .clinical.twin_v2 import get_timeline, get_syndrome_evolution, build_summary_incremental
            summary = build_summary_incremental(store, pid)
            timeline = get_timeline(store, pid)
            evolution = get_syndrome_evolution(store, pid)
            return 200, {"patient_id": pid, "summary": summary,
                         "timeline": timeline, "syndrome_evolution": evolution}

        # 0.2.7 clinical 增强 — 问诊助手
        if method == "POST" and path == "/clinical/consult/chat":
            from .clinical.consult_chat import start_session, chat
            pid = body.get("patient_id", 0)
            if not pid:
                return 400, {"error": "patient_id required"}
            sid = body.get("session_id")
            if not sid:
                sid = start_session(self.store, pid)
            msg = body.get("message", "")
            if not msg:
                return 400, {"error": "message required"}
            reply = chat(self.store, sid, msg)
            return 200, {"session_id": sid, "reply": reply}

        # 0.2.7 clinical 增强 — 随访管理
        if method == "POST" and path == "/clinical/followup":
            from .clinical.followup import add_plan
            pid = body.get("patient_id", 0)
            due = body.get("due_date", "")
            reason = body.get("reason", "")
            if not pid or not due:
                return 400, {"error": "patient_id and due_date required"}
            plan_id = add_plan(store, pid, due, reason)
            return 201, {"plan_id": plan_id}
        if method == "GET" and path == "/clinical/followup/scan":
            from .clinical.followup import scan_due
            as_of = qs.get("as_of", [None])[0]
            due = scan_due(store, as_of=as_of)
            return 200, {"due_plans": due}

        # 0.2.7 clinical 增强 — 结构化抽取
        if method == "POST" and path == "/clinical/extract":
            from .clinical.extract import extract_structured, apply_struct
            source = body.get("source", "")
            source_id = body.get("source_id", 0)
            text = body.get("text", "")
            if not source or not source_id:
                return 400, {"error": "source and source_id required"}
            if not text:
                if source == "record":
                    row = self.store.conn.execute(
                        "SELECT diagnosis, prescription FROM records WHERE id=?", (source_id,)
                    ).fetchone()
                    if row:
                        text = f"{row['diagnosis'] or ''} {row['prescription'] or ''}"
                elif source == "consult":
                    row = self.store.conn.execute(
                        "SELECT chief_complaint, differentiation FROM consultations WHERE id=?", (source_id,)
                    ).fetchone()
                    if row:
                        text = f"{row['chief_complaint'] or ''} {row['differentiation'] or ''}"
            if not text:
                return 404, {"error": "source not found or text empty"}
            struct = extract_structured(store, text)
            apply_struct(store, source, source_id, struct)
            return 200, {"structured": struct}

        # 0.4.0 clinical intelligence
        if method == "GET" and path.startswith("/clinical/analysis/") and path.endswith("/matrix"):
            from .clinical.analysis import build_syndrome_formula_matrix_for_patient
            _segments = path.strip("/").split("/")
            pid = _safe_int(_segments[2:3] if len(_segments) >= 3 else [0], 0)
            return 200, {"matrix": build_syndrome_formula_matrix_for_patient(self.store, pid)}
        if method == "GET" and path.startswith("/clinical/analysis/") and path.endswith("/evolution"):
            from .clinical.analysis import analyze_constitution_evolution
            _segments = path.strip("/").split("/")
            pid = _safe_int(_segments[2:3] if len(_segments) >= 3 else [0], 0)
            return 200, {"evolution": analyze_constitution_evolution(self.store, pid)}
        if method == "GET" and path.startswith("/clinical/tracking/") and len(path.strip("/").split("/")) == 3:
            from .clinical.tracking import evaluate_efficacy
            _segments = path.strip("/").split("/")
            pid = _safe_int(_segments[2:3] if len(_segments) >= 3 else [0], 0)
            return 200, {"efficacy": evaluate_efficacy(self.store, pid)}
        if method == "GET" and path.startswith("/clinical/trends/") and len(path.strip("/").split("/")) == 3:
            from .clinical.visualize import get_health_trends
            _segments = path.strip("/").split("/")
            pid = _safe_int(_segments[2:3] if len(_segments) >= 3 else [0], 0)
            return 200, {"trends": get_health_trends(self.store, pid)}
        if method == "POST" and path == "/clinical/diagnosis/suggest":
            from .clinical.diagnosis import suggest_formula, check_incompatibility
            from .llm import get_provider
            syndrome = body.get("syndrome", "")
            formulas = body.get("formulas", [])
            suggestions = suggest_formula(syndrome, provider=get_provider())
            warnings = check_incompatibility(formulas) if formulas else []
            return 200, {"suggestions": suggestions, "incompatibility_warnings": warnings}

        # 0.2.9 knowledge base — tags
        parts = path.strip("/").split("/")
        if method == "POST" and path.startswith("/documents/") and path.endswith("/tags") and len(parts) >= 3:
            from .tags import add_tag
            doc_id = parts[1]
            tag = body.get("tag", "")
            if not tag:
                return 400, {"error": "tag required"}
            add_tag(store, doc_id, tag)
            return 200, {"status": "ok", "tag": tag}
        if method == "DELETE" and path.startswith("/documents/") and path.endswith("/tags"):
            from .tags import remove_tag
            doc_id = parts[1]
            tag = qs.get("tag", [""])[0]
            if not tag:
                return 400, {"error": "tag query param required"}
            remove_tag(store, doc_id, tag)
            return 200, {"status": "ok"}
        if method == "GET" and path == "/tags":
            from .tags import list_tags
            return 200, {"tags": list_tags(store)}

        # 0.2.9 knowledge base — favorites
        if method == "POST" and path.startswith("/documents/") and path.endswith("/favorite"):
            from .favorites import toggle_favorite
            doc_id = parts[1]
            is_fav = toggle_favorite(store, doc_id)
            return 200, {"favorited": is_fav}
        if method == "GET" and path == "/favorites":
            from .favorites import list_favorites
            return 200, {"favorites": list_favorites(store)}

        # /metrics — Prometheus 格式指标
        if method == "GET" and path == "/metrics":
            if not os.environ.get("KHUB_METRICS_ENABLED"):
                return 404, {"error": "metrics disabled"}
            doc_count = self.store.conn.execute("SELECT count(*) FROM documents").fetchone()[0]
            pend = 0
            try:
                pend = self.store.conn.execute(
                    "SELECT count(*) FROM replication_log WHERE applied=0").fetchone()[0]
            except Exception:
                pass
            db_size = 0
            db_path = os.environ.get("KHUB_DB", "")
            if db_path and os.path.isfile(db_path):
                db_size = os.path.getsize(db_path)
            metrics_data = (
                "# HELP khub_requests_total Total HTTP requests\n"
                "# TYPE khub_requests_total counter\n"
                f'khub_requests_total{{method="GET"}} {_REQUESTS["GET"]}\n'
                f'khub_requests_total{{method="POST"}} {_REQUESTS["POST"]}\n'
                f'khub_requests_total{{method="PUT"}} {_REQUESTS["PUT"]}\n'
                "# HELP khub_db_documents Total documents\n"
                "# TYPE khub_db_documents gauge\n"
                f"khub_db_documents {doc_count}\n"
                "# HELP khub_db_size_bytes Database file size\n"
                "# TYPE khub_db_size_bytes gauge\n"
                f"khub_db_size_bytes {db_size}\n"
                "# HELP khub_wal_pending Pending WAL entries\n"
                "# TYPE khub_wal_pending gauge\n"
                f"khub_wal_pending {pend}\n"
            )
            return 200, metrics_data

        # 0.2.10 course management
        if method == "POST" and path == "/api/courses":
            from .course.store import add_course
            cid = add_course(store, name=body.get("name",""), teacher=body.get("teacher",""),
                             description=body.get("description",""),
                             start_date=body.get("start_date",""), end_date=body.get("end_date",""),
                             capacity=int(body.get("capacity", 0)),
                             price=float(body.get("price", 0)))
            return 201, {"course_id": cid}
        if method == "GET" and path == "/api/courses":
            from .course.store import list_courses
            return 200, {"courses": list_courses(store, status=qs.get("status", [None])[0])}
        if method == "GET" and path.startswith("/api/courses/") and len(parts) == 3:
            from .course.store import get_course
            cid = _safe_int([parts[2]], 0)
            if not cid: return 400, {"error": "invalid id"}
            course = get_course(store, cid)
            if not course: return 404, {"error": "not found"}
            return 200, {"course": dict(course)}
        if method == "POST" and path.startswith("/api/courses/") and len(parts) == 4 and parts[3] == "lessons":
            from .course.store import add_lesson
            cid = _safe_int([parts[2]], 0)
            lid = add_lesson(store, cid, title=body.get("title",""), lesson_date=body.get("lesson_date",""),
                             start_time=body.get("start_time",""), end_time=body.get("end_time",""),
                             location=body.get("location",""), content=body.get("content",""))
            return 201, {"lesson_id": lid}
        if method == "GET" and path.startswith("/api/courses/") and len(parts) == 4 and parts[3] == "lessons":
            from .course.store import list_lessons
            cid = _safe_int([parts[2]], 0)
            return 200, {"lessons": list_lessons(store, cid)}
        if method == "POST" and path.startswith("/api/courses/") and len(parts) == 4 and parts[3] == "enroll":
            from .course.store import enroll_student
            cid = _safe_int([parts[2]], 0)
            try:
                eid = enroll_student(store, cid, student_name=body.get("student_name",""),
                                     student_phone=body.get("student_phone",""))
                return 201, {"enrollment_id": eid}
            except ValueError as e:
                return 400, {"error": str(e)}
        if method == "GET" and path.startswith("/api/courses/") and len(parts) == 4 and parts[3] == "enrollments":
            from .course.store import list_enrollments
            cid = _safe_int([parts[2]], 0)
            return 200, {"enrollments": list_enrollments(store, cid)}
        if method == "POST" and path == "/api/grades":
            from .course.store import record_grade
            gid = record_grade(store, int(body.get("enrollment_id", 0)),
                               float(body.get("score", 0)),
                               lesson_id=int(body.get("lesson_id", 0)),
                               comment=body.get("comment", ""))
            return 201, {"grade_id": gid}
        if method == "GET" and path.startswith("/api/enrollments/") and len(parts) == 4 and parts[3] == "grades":
            from .course.store import list_grades
            eid = _safe_int([parts[2]], 0)
            return 200, {"grades": list_grades(store, eid)}

        # 0.2.11 wechat
        if method == "POST" and path == "/api/wechat/articles":
            from .wechat.store import add_article
            aid = add_article(store, title=body.get("title",""), content=body.get("content",""),
                              author=body.get("author",""), digest=body.get("digest",""),
                              content_source_url=body.get("content_source_url",""))
            return 201, {"article_id": aid}
        if method == "GET" and path == "/api/wechat/articles":
            from .wechat.store import list_articles
            return 200, {"articles": list_articles(store, status=qs.get("status", [None])[0])}
        if method == "POST" and path == "/api/wechat/schedules":
            from .wechat.store import add_schedule
            sid = add_schedule(store, int(body.get("article_id",0)),
                               body.get("publish_at",""), int(body.get("tag_id",0)))
            return 201, {"schedule_id": sid}
        if method == "GET" and path == "/api/wechat/followers":
            rows = self.store.conn.execute("SELECT openid, nickname, city, province, subscribe FROM wechat_followers ORDER BY last_sync_at DESC LIMIT 100").fetchall()
            return 200, {"followers": rows}

        # 0.3.0 auth
        if method == "POST" and path == "/auth/logout":
            from .auth import revoke_token
            token = (auth_header or "").removeprefix("Bearer ")
            if token:
                revoke_token(self.store, token)
            return 200, {"status": "ok"}
        if method == "GET" and path == "/auth/me":
            cu = getattr(self, "_current_user", None)
            return 200, {"user": cu}

        # 0.3.1 用户管理（admin 专用）
        if method == "GET" and path == "/api/users":
            if not check_permission(current_user, "users", "read"):
                return 403, {"error": "permission_denied", "error_code": "AUTH_002", "message": "权限不足"}
            from .auth import list_users
            return 200, {"users": list_users(self.store)}
        if method == "POST" and path == "/api/users":
            if not check_permission(current_user, "users", "create"):
                return 403, {"error": "permission_denied", "error_code": "AUTH_002", "message": "权限不足"}
            from .auth import create_user
            try:
                uid = create_user(self.store, body.get("username", ""), body.get("password", ""),
                                  display_name=body.get("display_name", ""),
                                  role=body.get("role", "user"))
                return 201, {"user_id": uid}
            except Exception as e:
                return 400, {"error": str(e)}
        if method == "PUT" and path.startswith("/api/users/") and path.endswith("/role"):
            if not check_permission(current_user, "users", "update"):
                return 403, {"error": "permission_denied", "error_code": "AUTH_002", "message": "权限不足"}
            from .auth import update_user_role
            uid = _safe_int([parts[2]], 0)
            try:
                update_user_role(self.store, uid, body.get("role", ""))
                return 200, {"status": "ok"}
            except ValueError as e:
                return 400, {"error": str(e)}

        # 0.5.0 knowledge graph
        if method == "GET" and path == "/api/kg/infer":
            from .knowledge.inference import infer
            syd = qs.get("syndrome", [""])[0]
            if not syd: return 400, {"error": "syndrome param required"}
            return 200, {"result": infer(store, syd)}
        if method == "GET" and path == "/api/kg/herbs":
            from .knowledge.herbs import search_herbs
            return 200, {"herbs": search_herbs(store, channel=qs.get("channel", [""])[0], nature=qs.get("nature", [""])[0])}
        if method == "GET" and path == "/api/kg/formulas":
            from .knowledge.formulas import list_formulas
            return 200, {"formulas": list_formulas(store, category=qs.get("category", [""])[0])}
        if method == "GET" and path == "/api/kg/syndromes":
            from .knowledge.syndromes import list_syndromes
            return 200, {"syndromes": list_syndromes(store, category=qs.get("category", [""])[0])}
        if method == "GET" and path.startswith("/api/kg/similarity"):
            from .knowledge.formulas import formula_similarity
            f1 = qs.get("f1", [""])[0]; f2 = qs.get("f2", [""])[0]
            if not f1 or not f2: return 400, {"error": "f1 and f2 required"}
            return 200, {"formula1": f1, "formula2": f2, "similarity": formula_similarity(store, f1, f2)}

        # 0.5.1 deployment info
        if method == "GET" and path == "/api/info":
            from .cache import get as _cache_get, set as _cache_set
            cached = _cache_get("api_info")
            if cached is not None:
                return 200, cached
            info = {
                "name": os.environ.get("KHUB_BRAND_NAME", "kHUB"),
                "version": __version__,
                "logo_url": os.environ.get("KHUB_BRAND_LOGO", ""),
                "uptime_sec": int(time.time() - _START),
                "api_version": "0.5.1",
            }
            _cache_set("api_info", info, ttl=5)
            return 200, info

        # 0.6.0 开放平台
        if method == "GET" and path == "/api/openapi.json":
            from .openapi import get_spec
            return 200, get_spec()
        if method == "GET" and path == "/api/docs":
            html = ("<!DOCTYPE html><html><head><title>kHUB API</title>"
                    "<link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css'>"
                    "</head><body><div id='swagger-ui'></div>"
                    "<script src='https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js'></script>"
                    "<script>SwaggerUIBundle({url:'/api/openapi.json',dom_id:'#swagger-ui'})</script>"
                    "</body></html>")
            return 200, html
        if method == "GET" and path == "/api/plugins":
            from .plugins.registry import list_plugins
            return 200, {"plugins": list_plugins()}
        if method == "POST" and path == "/api/webhooks":
            from .webhook import subscribe
            try:
                sid = subscribe(store, body.get("event", ""), body.get("url", ""),
                                secret=body.get("secret", ""))
                return 201, {"subscription_id": sid}
            except ValueError as e:
                return 400, {"error": str(e)}
        if method == "GET" and path == "/api/webhooks":
            from .webhook import list_subscriptions
            return 200, {"subscriptions": list_subscriptions(store)}
        parts = path.strip("/").split("/")
        if method == "DELETE" and path.startswith("/api/webhooks/") and len(parts) == 3:
            from .webhook import unsubscribe
            try:
                unsubscribe(store, int(parts[2]))
                return 200, {"status": "deleted"}
            except Exception as e:
                return 400, {"error": str(e)}

        # 0.6.1 notifications
        if method == "GET" and path == "/api/notifications":
            from .notifications import list_recent, unread_count
            uid = getattr(self, "_current_user", {}).get("user_id", 0)
            return 200, {"notifications": list_recent(store, uid),
                         "unread": unread_count(store, uid)}
        if method == "POST" and path.startswith("/api/notifications/") and path.endswith("/read"):
            from .notifications import mark_read
            nid = _safe_int([parts[2]], 0)
            uid = getattr(self, "_current_user", {}).get("user_id", 0)
            mark_read(store, nid, uid)
            return 200, {"status": "ok"}
        if method == "POST" and path == "/api/notifications/read-all":
            from .notifications import mark_all_read
            uid = getattr(self, "_current_user", {}).get("user_id", 0)
            mark_all_read(store, uid)
            return 200, {"status": "ok"}

        # 0.6.2 reports
        if method == "POST" and path == "/api/reports":
            from .reports import create_template
            tid = create_template(store, body.get("name", ""), body.get("query", ""),
                                  description=body.get("description", ""),
                                  chart_type=body.get("chart_type", "table"))
            return 201, {"template_id": tid}
        if method == "GET" and path == "/api/reports":
            from .reports import list_templates
            return 200, {"templates": list_templates(store)}
        if method == "POST" and path.startswith("/api/reports/") and path.endswith("/run"):
            from .reports import execute
            tid = _safe_int([parts[2]], 0)
            if not tid:
                return 400, {"error": "invalid id"}
            try:
                result = execute(store, tid)
                return 200, result
            except ValueError as e:
                return 404, {"error": str(e)}
            except Exception as e:
                return 500, {"error": str(e)}
        if method == "GET" and path.startswith("/api/reports/") and path.endswith("/csv"):
            from .reports import export_csv
            tid = _safe_int([parts[2]], 0)
            if not tid:
                return 400, {"error": "invalid id"}
            csv_data = export_csv(store, tid)
            return 200, csv_data, "text/csv; charset=utf-8"

        # 0.7.0 copilot
        if method == "POST" and path == "/api/copilot/chat":
            from .copilot.engine import process
            text = body.get("text", "")
            if not text: return 400, {"error": "text required"}
            result = process(store, text, current_user=getattr(self, "_current_user", None))
            return 200, result
        if method == "GET" and path == "/api/copilot/tools":
            from .copilot.tools import list_tools
            return 200, {"tools": list_tools()}

        # 0.7.1 workflow
        if method == "POST" and path == "/api/workflow/definitions":
            from .workflow.store import create_definition
            did = create_definition(store, body.get("name",""), body.get("steps",[]), description=body.get("description",""))
            return 201, {"definition_id": did}
        if method == "GET" and path == "/api/workflow/definitions":
            from .workflow.store import list_definitions
            return 200, {"definitions": list_definitions(store)}
        if method == "POST" and path.startswith("/api/workflow/definitions/") and path.endswith("/run"):
            from .workflow.store import create_instance
            from .workflow.engine import run
            did = _safe_int([parts[2]], 0)
            iid = create_instance(store, did, entity_type=body.get("entity_type",""), entity_id=body.get("entity_id",""), context=body.get("context"))
            result = run(store, iid)
            return 200, {"instance_id": iid, "result": result}
        if method == "GET" and path == "/api/workflow/instances":
            from .workflow.store import list_instances
            return 200, {"instances": list_instances(store, status=qs.get("status",[""])[0])}

        # 0.7.2 unified search
        if method == "GET" and path == "/api/search":
            from .search2 import unified_search
            q = qs.get("q", [""])[0]
            if not q: return 200, {"results": []}
            stype = qs.get("type", ["all"])[0]
            limit = int(qs.get("limit", [20])[0])
            results = unified_search(store, q, type=stype, limit=limit)
            return 200, {"query": q, "type": stype, "count": len(results), "results": results}

        # 0.7.3 sync
        if method == "POST" and path == "/api/sync/push":
            from .sync2 import push
            client_id = body.get("client_id", "unknown")
            result = push(store, client_id, body.get("changes", []))
            return 200, result
        if method == "GET" and path == "/api/sync/pull":
            from .sync2 import pull
            client_id = qs.get("client_id", ["unknown"])[0]
            since = int(qs.get("since", ["0"])[0])
            result = pull(store, client_id, since)
            return 200, result
        if method == "GET" and path == "/api/sync/status":
            from .sync2 import status
            return 200, status(store)

        # 0.8.1 安全合规——审计日志查询
        if method == "GET" and path == "/api/admin/audit":
            from .audit import search_audit
            event = qs.get("event", [None])[0]
            actor = qs.get("actor", [None])[0]
            since = qs.get("since", [None])[0]
            limit = int(qs.get("limit", [100])[0])
            results = search_audit(store, event=event, actor=actor, since=since, limit=limit)
            return 200, {"audit_logs": results}

        # 0.8.2 analytics
        if method == "GET" and path == "/api/analytics/cohorts":
            from .analytics import patient_cohorts
            return 200, patient_cohorts(store)
        if method == "GET" and path == "/api/analytics/efficacy":
            from .analytics import syndrome_efficacy
            return 200, {"efficacy": syndrome_efficacy(store)}
        if method == "GET" and path == "/api/analytics/forecast":
            from .analytics import visit_forecast
            return 200, visit_forecast(store)
        if method == "GET" and path == "/api/analytics/trends":
            from .analytics import appointment_trends
            return 200, {"trends": appointment_trends(store)}

        # 0.8.3 integrations
        if method == "GET" and path == "/api/integrations/status":
            from .integrations.status import check_all
            return 200, {"integrations": check_all()}

        # 0.9.0 agents
        if method == "POST" and path == "/api/agents":
            from .agents.store import create_agent
            aid = create_agent(store, body.get("name",""), system_prompt=body.get("system_prompt",""),
                               tools=body.get("tools",[]), description=body.get("description",""))
            return 201, {"agent_id": aid}
        if method == "GET" and path == "/api/agents":
            from .agents.store import list_agents
            return 200, {"agents": list_agents(store)}
        if method == "POST" and path.startswith("/api/agents/") and path.endswith("/run"):
            from .agents.engine import run_with_llm
            aid = _safe_int([parts[2]], 0)
            result = run_with_llm(store, aid, user_input=body.get("input",""), current_user=getattr(self,"_current_user",None))
            return 200, result

        # 1.1.0 agents v2 — 模板市场 + 记忆系统 + 多 Agent 协作
        if method == "GET" and path == "/api/agents/templates":
            from .agents.templates import list_templates, seed
            seed(store)
            cat = qs.get("category", [""])[0]
            return 200, {"templates": list_templates(store, category=cat)}
        if method == "POST" and path == "/api/agents/create-from-template":
            from .agents.templates import create_from_template
            aid = create_from_template(store, body.get("template_id", 0), name=body.get("name", ""))
            return 201, {"agent_id": aid}
        if method == "POST" and path == "/api/agents/memory":
            from .agents.memory import store as mem_store
            mem_store(store, body.get("agent_id", 0), body.get("key", ""), body.get("value", ""), type=body.get("type", "string"))
            return 200, {"status": "stored"}
        if method == "GET" and path.startswith("/api/agents/") and path.endswith("/memory"):
            from .agents.memory import list_memory
            aid = _safe_int([parts[2]], 0)
            return 200, {"memory": list_memory(store, aid)}
        if method == "POST" and path == "/api/agents/pipelines":
            from .agents.pipeline import create_pipeline
            pid = create_pipeline(store, body.get("name",""), body.get("agent_ids",[]), description=body.get("description",""))
            return 201, {"pipeline_id": pid}
        if method == "GET" and path == "/api/agents/pipelines":
            from .agents.pipeline import list_pipelines
            return 200, {"pipelines": list_pipelines(store)}
        if method == "POST" and path.startswith("/api/agents/pipelines/") and path.endswith("/run"):
            from .agents.pipeline import run as run_pipeline
            pid = _safe_int([parts[3]], 0)
            results = run_pipeline(store, pid, input_text=body.get("input",""), current_user=getattr(self,"_current_user",None))
            return 200, {"results": results}

        # 0.9.1 多租户管理（仅 admin）
        cu = getattr(self, "_current_user", None) or current_user
        if not check_permission(cu, "users", "create"):
            return 403, {"error": "permission_denied", "error_code": "AUTH_002", "message": "仅管理员可管理租户"}
        if method == "POST" and path == "/api/tenants":
            from .tenants import create_tenant
            tid = create_tenant(store, body.get("name", ""), body.get("slug", ""),
                                plan=body.get("plan", "free"))
            return 201, {"tenant_id": tid}
        if method == "GET" and path == "/api/tenants":
            from .tenants import list_tenants
            return 200, {"tenants": list_tenants(store)}
        if method == "POST" and path == "/api/tenants/members":
            from .tenants import add_member
            add_member(store, body.get("tenant_id", 0), body.get("user_id", 0),
                       role=body.get("role", "member"))
            return 200, {"status": "added"}
        if method == "GET" and path.startswith("/api/tenants/") and path.endswith("/members"):
            from .tenants import list_members
            tid = _safe_int([parts[2]], 0)
            return 200, {"members": list_members(store, tid)}

        # 0.9.2 远程医疗 —— 视频问诊信令
        if method == "POST" and path == "/api/telemedicine/rooms":
            from .telemedicine import create_room
            result = create_room(store, body.get("appointment_id", 0))
            return 201, result
        if method == "GET" and path.startswith("/api/telemedicine/rooms/"):
            from .telemedicine import get_room
            room_id = path[len("/api/telemedicine/rooms/"):]
            room = get_room(store, room_id)
            if not room:
                return 404, {"error": "room not found"}
            return 200, room
        if method == "POST" and path.startswith("/api/telemedicine/rooms/") and path.endswith("/offer"):
            from .telemedicine import set_offer
            room_id = path[len("/api/telemedicine/rooms/"):-len("/offer")]
            set_offer(store, room_id, body.get("offer", ""))
            return 200, {"status": "ok"}
        if method == "POST" and path.startswith("/api/telemedicine/rooms/") and path.endswith("/answer"):
            from .telemedicine import set_answer
            room_id = path[len("/api/telemedicine/rooms/"):-len("/answer")]
            set_answer(store, room_id, body.get("answer", ""))
            return 200, {"status": "ok"}
        if method == "POST" and path.startswith("/api/telemedicine/rooms/") and path.endswith("/end"):
            from .telemedicine import end_call
            room_id = path[len("/api/telemedicine/rooms/"):-len("/end")]
            end_call(store, room_id)
            return 200, {"status": "ok"}

        # 0.9.2 远程医疗 —— 电子处方
        if method == "POST" and path == "/api/prescriptions":
            from .telemedicine import create_prescription
            pid = create_prescription(
                store,
                body.get("consultation_id", 0),
                body.get("doctor_id", 0),
                body.get("patient_id", 0),
                body.get("items", []))
            return 201, {"prescription_id": pid}
        if method == "GET" and path == "/api/prescriptions":
            from .telemedicine import list_prescriptions
            pid = qs.get("patient_id", [None])[0]
            patient_id = int(pid) if (pid and pid.isdigit()) else 0
            return 200, {"prescriptions": list_prescriptions(store, patient_id)}
        if method == "GET" and path.startswith("/api/prescriptions/") and len(parts) == 3:
            from .telemedicine import get_prescription
            pid = _safe_int([parts[2]], 0)
            if not pid:
                return 400, {"error": "invalid id"}
            presc = get_prescription(store, pid)
            if not presc:
                return 404, {"error": "not found"}
            return 200, presc

        # 0.9.3 community — 文章
        if method == "POST" and path == "/api/community/articles":
            from .community.articles import create_article
            aid = create_article(store, body.get("title", ""), body.get("content", ""),
                                 author_id=0, tags=body.get("tags", []),
                                 is_public=body.get("is_public", True))
            return 201, {"article_id": aid}
        if method == "GET" and path == "/api/community/articles":
            from .community.articles import list_articles
            return 200, {"articles": list_articles(store, tag=qs.get("tag", [""])[0])}
        if method == "GET" and path.startswith("/api/community/articles/") and len(parts) == 4 and parts[3]:
            from .community.articles import get_article
            aid = _safe_int([parts[3]], 0)
            article = get_article(store, aid)
            if not article:
                return 404, {"error": "not found"}
            from .community.comments import list_comments
            return 200, {"article": dict(article), "comments": list_comments(store, aid)}
        if method == "GET" and path == "/api/community/tags":
            from .community.articles import list_tags
            return 200, {"tags": list_tags(store)}
        # 0.9.3 community — 评论
        if method == "POST" and path == "/api/community/comments":
            from .community.comments import add_comment
            cid = add_comment(store, body.get("article_id", 0), body.get("content", ""),
                              author_id=0)
            return 201, {"comment_id": cid}

        # 0.9.4 合规认证
        if method == "GET" and path == "/api/compliance/checklist":
            from .compliance import run_checklist
            return 200, run_checklist(store)
        if method == "GET" and path == "/api/compliance/report":
            from .compliance import generate_report
            return 200, {"report": generate_report(store)}

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
            from .auth import get_current_user
            cu = get_current_user(app.store, self.headers.get("Authorization", ""))
            if not cu:
                return self._send(401, {"error": "unauthorized", "error_code": "AUTH_001", "message": "请提供有效的认证令牌"})

            question = (body or {}).get("question", "").strip()
            if not question:
                return self._send(400, {"error": "question 必填"})
            if len(question) > 2000:
                return self._send(400, {"error": "question 超过 2000 字符上限"})
            k = body.get("k", 5)
            if not isinstance(k, (int, float)):
                k = 5
            k = max(1, min(int(k), 20))
            source_filter = body.get("source_filter")

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
                for event in engine.ask_stream(question, k=k, source_filter=source_filter):
                    ev = event["event"]
                    data = json.dumps(event["data"], ensure_ascii=False)
                    line = f"event: {ev}\ndata: {data}\n\n"
                    self.wfile.write(line.encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass  # 客户端断开，静默结束

        def do_GET(self):
            # 0.6.1 SSE 事件流端点（需要在标准 dispatch 前拦截，直接写 wfile）
            if self.path == "/events":
                from .auth import get_current_user
                cu = get_current_user(app.store, self.headers.get("Authorization", ""))
                if not cu:
                    return self._send(401, {"error": "unauthorized", "error_code": "AUTH_001", "message": "请提供有效的认证令牌"})
                from .events import subscribe, unsubscribe
                sub_id, q = subscribe()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(b"event: connected\ndata: {}\n\n")
                self.wfile.flush()
                try:
                    while True:
                        try:
                            msg = q.get(timeout=30)
                            self.wfile.write(f"data: {msg}\n\n".encode())
                            self.wfile.flush()
                        except queue.Empty:
                            self.wfile.write(b": heartbeat\n\n")
                            self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    unsubscribe(sub_id)
                return
            if app.ratelimit is not None:
                client_ip = self.client_address[0]
                if not app.ratelimit.allow(client_ip):
                    return self._send(429, {"error": "too many requests"},
                                      retry_after=1)
            try:
                res = app.dispatch("GET", self.path,
                                   auth_header=self.headers.get("Authorization", ""),
                                   tenant_header=self.headers.get("X-Tenant-ID", ""))
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
                                   auth_header=self.headers.get("Authorization", ""),
                                   tenant_header=self.headers.get("X-Tenant-ID", ""))
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
                             "Content-Type, Authorization, X-Tenant-ID")
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
                                   auth_header=self.headers.get("Authorization", ""),
                                   tenant_header=self.headers.get("X-Tenant-ID", ""))
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
                                   auth_header=self.headers.get("Authorization", ""),
                                   tenant_header=self.headers.get("X-Tenant-ID", ""))
                if len(res) == 3:
                    code, obj, ctype = res
                else:
                    code, obj, ctype = res[0], res[1], "application/json; charset=utf-8"
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": str(e)})
            self._send(code, obj, ctype)

        def log_message(self, format, *args):
            import logging
            logging.getLogger("khub.api").info(
                "%s %s %s", self.command, self.path, args[0] if args else "-")

    return Handler


def serve(store: Store, library: ManagedLibrary, host: str = "127.0.0.1", port: int = 8000):
    # 0.6.0 插件系统初始化
    from .plugins.registry import discover, load_plugins, shutdown_plugins
    discover()
    load_plugins(store)
    app = App(store, library)
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    import signal

    def _stop(*a):
        print("\n收到停止信号，正在关闭...")
        shutdown_plugins(store)
        httpd.shutdown()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    print(f"kHUB API → http://{host}:{port}  (pid={os.getpid()})")
    httpd.serve_forever()
