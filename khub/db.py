import sqlite3
import hashlib
import json
import os
import time
from typing import Optional
from .models import CanonicalDoc


def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


class Store:
    def __init__(self, path=":memory:"):
        self.path = os.path.expanduser(path)
        if self.path != ":memory:":
            parent = os.path.dirname(os.path.abspath(self.path))
            if parent:
                os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.init_schema()

    def init_schema(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS sources(
            name TEXT PRIMARY KEY, type TEXT, direction TEXT, config_ref TEXT);
        CREATE TABLE IF NOT EXISTS documents(
            canonical_id TEXT PRIMARY KEY, title TEXT, current_version INTEGER,
            source_ids TEXT, created_at TEXT, updated_at TEXT,
            doc_type TEXT DEFAULT 'raw', conflict INTEGER DEFAULT 0,
            format TEXT DEFAULT 'raw', ingested INTEGER DEFAULT 0, file_hash TEXT);
        CREATE TABLE IF NOT EXISTS document_versions(
            version_id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT,
            content TEXT, format TEXT, origin TEXT, author TEXT,
            updated_at TEXT, hash TEXT, parent_version INTEGER, note TEXT);
        CREATE TABLE IF NOT EXISTS attachments(
            id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, version_id INTEGER,
            kind TEXT, path TEXT, hash TEXT);
        CREATE TABLE IF NOT EXISTS sync_states(
            source_id TEXT, doc_id TEXT, last_sync_at TEXT, etag TEXT, hash TEXT,
            PRIMARY KEY(source_id, doc_id));
        CREATE TABLE IF NOT EXISTS embeddings(
            doc_id TEXT, version_id INTEGER, model TEXT, vector BLOB);
        CREATE TABLE IF NOT EXISTS files(
            sha256 TEXT PRIMARY KEY, path TEXT, size INTEGER,
            format TEXT, stored_at TEXT);
        CREATE TABLE IF NOT EXISTS ebook_meta(
            canonical_id TEXT PRIMARY KEY, author TEXT, isbn TEXT, lang TEXT,
            page_count INTEGER, publisher TEXT, published_date TEXT,
            cover_path TEXT, toc_json TEXT);
        CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
            doc_id, title, content, tokenize='trigram');
        """)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(documents)")}
        for col, ddl in [("format", "TEXT DEFAULT 'raw'"),
                         ("ingested", "INTEGER DEFAULT 0"),
                         ("file_hash", "TEXT")]:
            if col not in cols:
                self.conn.execute(f"ALTER TABLE documents ADD COLUMN {col} {ddl}")
        # 迁移：追加 direction 列到 sync_states（安全幂等）
        try:
            sc = {r["name"] for r in
                  self.conn.execute("PRAGMA table_info(sync_states)")}
            if "direction" not in sc:
                self.conn.execute(
                    "ALTER TABLE sync_states ADD COLUMN direction TEXT DEFAULT 'pull'")
        except Exception:
            pass  # 列已存在

    def store_document(self, doc: CanonicalDoc, parent_version: Optional[int] = None) -> int:
        cur = self.conn
        existing = cur.execute(
            "SELECT canonical_id, current_version FROM documents WHERE canonical_id=?",
            (doc.canonical_id,)).fetchone()
        if existing is None:
            cur.execute(
                "INSERT INTO documents(canonical_id, title, current_version, source_ids, "
                "created_at, updated_at, doc_type, conflict) VALUES(?,?,?,?,?,?,?,0)",
                (doc.canonical_id, doc.title, 1, json.dumps([doc.source]),
                 _now(), doc.updated_at or _now(), doc.doc_type))
            parent = parent_version
        else:
            parent = existing["current_version"]
        c = cur.execute(
            "INSERT INTO document_versions(doc_id, content, format, origin, author, "
            "updated_at, hash, parent_version, note) VALUES(?,?,?,?,?,?,?,?,?)",
            (doc.canonical_id, doc.content, doc.format, doc.origin, "",
             doc.updated_at or _now(), doc.hash or compute_hash(doc.content),
             parent, doc.note))
        version_id = c.lastrowid
        cur.execute("UPDATE documents SET current_version=?, title=?, updated_at=? "
                    "WHERE canonical_id=?", (version_id, doc.title,
                     doc.updated_at or _now(), doc.canonical_id))
        if doc.content and doc.content.strip():
            cur.execute("DELETE FROM docs_fts WHERE doc_id=?", (doc.canonical_id,))
            cur.execute("INSERT INTO docs_fts(doc_id, title, content) VALUES(?,?,?)",
                        (doc.canonical_id, doc.title, doc.content))
        for a in doc.attachments:
            cur.execute("INSERT INTO attachments(doc_id, version_id, kind, path, hash) "
                        "VALUES(?,?,?,?,?)", (doc.canonical_id, version_id, a.kind, a.path, a.hash))
        self.conn.commit()
        return version_id

    def get_document(self, canonical_id: str):
        return self.conn.execute("SELECT * FROM documents WHERE canonical_id=?",
                                 (canonical_id,)).fetchone()

    def get_versions(self, doc_id: str):
        return self.conn.execute(
            "SELECT * FROM document_versions WHERE doc_id=? ORDER BY version_id",
            (doc_id,)).fetchall()

    def set_sync_state(self, source_id: str, doc_id: str, etag: str, h: str):
        self.conn.execute(
            "INSERT INTO sync_states(source_id, doc_id, last_sync_at, etag, hash) "
            "VALUES(?,?,?,?,?) ON CONFLICT(source_id, doc_id) DO UPDATE SET "
            "last_sync_at=excluded.last_sync_at, etag=excluded.etag, hash=excluded.hash",
            (source_id, doc_id, _now(), etag, h))
        self.conn.commit()

    def get_sync_state(self, source_id: str, doc_id: str):
        return self.conn.execute(
            "SELECT * FROM sync_states WHERE source_id=? AND doc_id=?",
            (source_id, doc_id)).fetchone()

    def upsert_sync_state(self, source_id, doc_id, etag="", hash="", direction="pull"):
        """插入或更新同步状态。direction: pull/push/both。"""
        self.conn.execute("""
            INSERT INTO sync_states(source_id, doc_id, last_sync_at, etag, hash, direction)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(source_id, doc_id) DO UPDATE SET
            last_sync_at=excluded.last_sync_at, etag=excluded.etag,
            hash=excluded.hash, direction=excluded.direction
        """, (source_id, doc_id, time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
              etag, hash, direction))
        self.conn.commit()

    def list_pending_push(self, source_name, limit=200):
        """列出从 kHUB 推送到远端源的上次 pull 后 hash 变了的文档。"""
        rows = self.conn.execute("""
            SELECT d.canonical_id, d.title, v.content, v.hash
            FROM documents d
            JOIN document_versions v ON v.version_id = d.current_version
            WHERE d.source_ids LIKE ?
        """, (f'%{source_name}%',)).fetchall()
        out = []
        for r in rows:
            st = self.get_sync_state(source_name, r["canonical_id"])
            if st is None or st["hash"] != r["hash"]:
                out.append(dict(r))
        return out[:limit]

    def list_pending_pull(self):
        """列出所有已记录 sync_states 的源（用于 CLI）。"""
        rows = self.conn.execute(
            "SELECT DISTINCT source_id FROM sync_states").fetchall()
        return [r["source_id"] for r in rows]

    def mark_conflict(self, doc_id: str, flag: bool = True):
        self.conn.execute("UPDATE documents SET conflict=? WHERE canonical_id=?",
                          (1 if flag else 0, doc_id))
        self.conn.commit()

    def search(self, text: str):
        q = (text or "").strip()
        if not q:
            return []
        tokens = [t for t in q.split() if t]
        if len(tokens) > 1:
            # 多词联合搜索：每个词独立匹配，求交集（AND 语义）
            return self._search_multitoken(tokens, q)
        return self._search_single(tokens[0] if tokens else q)

    def _search_single(self, q: str):
        """单关键词搜索：>=3 字符走 trigram MATCH，短词走 LIKE。"""
        if len(q) < 3:
            return self._search_like(q)
        try:
            rows = self.conn.execute(
                "SELECT doc_id, title, snippet(docs_fts, 2, '[', ']', '...', 10) AS snip "
                "FROM docs_fts WHERE docs_fts MATCH ? "
                "ORDER BY rank", (q,)).fetchall()
        except sqlite3.OperationalError:
            return self._search_like(q)
        return [(r["doc_id"], r["title"], r["snip"]) for r in rows]

    def _search_multitoken(self, tokens: list[str], raw_query: str):
        """多词联合搜索（AND）：对每个 token 搜 LIKE，取交集。"""
        conditions = []
        params = []
        for t in tokens:
            like = f"%{t}%"
            conditions.append("(d.title LIKE ? OR v.content LIKE ?)")
            params.extend([like, like])
        sql = (
            "SELECT d.canonical_id, d.title, v.content FROM documents d "
            "JOIN document_versions v ON v.version_id = d.current_version "
            "WHERE " + " AND ".join(conditions))
        rows = self.conn.execute(sql, params).fetchall()
        # 取前 50 篇避免太长
        return [(r["canonical_id"], r["title"],
                 self._snippet(r["content"], raw_query, width=15))
                for r in rows[:50]]

    def _search_like(self, q: str):
        like = f"%{q}%"
        rows = self.conn.execute(
            "SELECT d.canonical_id, d.title, v.content FROM documents d "
            "JOIN document_versions v ON v.version_id = d.current_version "
            "WHERE d.title LIKE ? OR v.content LIKE ?", (like, like)).fetchall()
        return [(r["canonical_id"], r["title"], self._snippet(r["content"], q))
                for r in rows]

    @staticmethod
    def _snippet(content, q, width=20):
        if not content:
            return ""
        # 对多词查询，找第一个命中的 token 位置
        tokens = [t for t in q.split() if t]
        pos = -1
        for tok in tokens:
            i = content.find(tok)
            if i >= 0:
                pos = i
                break
        if pos < 0:
            return content[:width * 2]
        start = max(0, pos - width)
        end = min(len(content), pos + len(tokens[0] if tokens else q) + width)
        return ("..." if start > 0 else "") + content[start:end] + \
               ("..." if end < len(content) else "")

    def list_conflicts(self):
        rows = self.conn.execute("SELECT canonical_id FROM documents WHERE conflict=1").fetchall()
        return [r["canonical_id"] for r in rows]

    def upsert_file(self, sha256: str, path: str, size: int, fmt: str):
        self.conn.execute(
            "INSERT INTO files(sha256, path, size, format, stored_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(sha256) DO UPDATE SET path=excluded.path, size=excluded.size",
            (sha256, path, size, fmt, _now()))
        self.conn.commit()

    def add_ebook(self, canonical_id: str, title: str, fmt: str, file_hash: str,
                  source_id: str, meta: Optional[dict] = None):
        now = _now()
        self.conn.execute(
            "INSERT INTO documents(canonical_id, title, current_version, source_ids, "
            "created_at, updated_at, doc_type, conflict, format, ingested, file_hash) "
            "VALUES(?,?,0,?,?,?,'ebook',0,?,0,?) "
            "ON CONFLICT(canonical_id) DO UPDATE SET title=excluded.title, "
            "file_hash=excluded.file_hash, updated_at=excluded.updated_at",
            (canonical_id, title, json.dumps([source_id]), now, now, fmt, file_hash))
        if meta:
            self.conn.execute(
                "INSERT INTO ebook_meta(canonical_id, author, isbn, lang, page_count, "
                "publisher, published_date, cover_path, toc_json) "
                "VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(canonical_id) DO UPDATE SET "
                "author=excluded.author, isbn=excluded.isbn, lang=excluded.lang, "
                "page_count=excluded.page_count, publisher=excluded.publisher, "
                "published_date=excluded.published_date, cover_path=excluded.cover_path, "
                "toc_json=excluded.toc_json",
                (canonical_id, meta.get("author"), meta.get("isbn"), meta.get("lang"),
                 meta.get("page_count"), meta.get("publisher"), meta.get("published_date"),
                 meta.get("cover_path"), meta.get("toc_json")))
        self.conn.commit()

    def list_ebooks(self):
        rows = self.conn.execute(
            "SELECT d.canonical_id, d.title, d.format, d.ingested, d.file_hash, "
            "e.author, e.isbn, e.lang "
            "FROM documents d LEFT JOIN ebook_meta e ON d.canonical_id=e.canonical_id "
            "WHERE d.doc_type='ebook' ORDER BY d.title").fetchall()
        return [dict(r) for r in rows]

    def mark_ingested(self, canonical_id: str, version_id: int):
        self.conn.execute(
            "UPDATE documents SET ingested=1, current_version=? WHERE canonical_id=?",
            (version_id, canonical_id))
        self.conn.commit()
