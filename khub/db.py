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
        self.path = path
        if path != ":memory:":
            parent = os.path.dirname(os.path.abspath(path))
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
        CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(doc_id, title, content);
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

    def mark_conflict(self, doc_id: str, flag: bool = True):
        self.conn.execute("UPDATE documents SET conflict=? WHERE canonical_id=?",
                          (1 if flag else 0, doc_id))
        self.conn.commit()

    def search(self, text: str):
        rows = self.conn.execute(
            "SELECT doc_id, title, snippet(docs_fts, 2, '[', ']', '...', 10) AS snip "
            "FROM docs_fts WHERE docs_fts MATCH ?", (text,)).fetchall()
        return [(r["doc_id"], r["title"], r["snip"]) for r in rows]

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
