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
        CREATE TABLE IF NOT EXISTS ha_state(
            key TEXT PRIMARY KEY, value TEXT);
        """)
        # 复制 WAL 表与 lsn 分配器（与业务写入同事务）
        self.conn.execute("""CREATE TABLE IF NOT EXISTS replication_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lsn INTEGER,
            op TEXT, table_name TEXT, row_id TEXT,
            payload TEXT, at TEXT, applied INTEGER DEFAULT 0)""")
        cols = {r["name"] for r in
                self.conn.execute("PRAGMA table_info(replication_log)")}
        if "lsn" not in cols:
            self.conn.execute("ALTER TABLE replication_log ADD COLUMN lsn INTEGER")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS lsn_seq(seq INTEGER NOT NULL)")
        if self.conn.execute("SELECT COUNT(*) FROM lsn_seq").fetchone()[0] == 0:
            self.conn.execute("INSERT INTO lsn_seq(seq) VALUES(0)")
        self._migrate()
        self.conn.commit()
        # documents 复制触发器（仅 Primary 自动记账；备机回放前关 recursive_triggers）
        from .replication import install_triggers
        install_triggers(self.conn, "documents", pk="canonical_id")

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

    def transaction(self):
        """上下文管理器：统一 begin/commit/rollback。

        用法::

            with store.transaction():
                store.store_document(doc)   # 内部不再各自 commit

        回放/批量写入须包在此内，保证 WAL 与主表同一事务一次性提交。
        """
        class _Tx:
            def __init__(self, conn):
                self.conn = conn
            def __enter__(self):
                self.conn.execute("BEGIN")
                return self.conn
            def __exit__(self, exc, *_):
                if exc:
                    self.conn.rollback()
                else:
                    self.conn.commit()
                return False
        return _Tx(self.conn)

    def _replicate(self, op: str, table: str, row_id: str, payload: dict):
        """P0a：复制改由 DB 触发器自动记账（仅 Primary 安装，见 replication.install_triggers）。

        保留此接口为 no-op，避免任何残留双记；手动补记路径见
        replication.manual_record_change（同样复用 lsn_seq）。
        """
        return

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
        # WAL 记账已由 documents 表上的 AFTER INSERT/UPDATE 触发器自动完成（与主写入同事务）。
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

    # ---- 搜索（旧接口，保持兼容） ----
    def search_old(self, text: str) -> list:
        """旧版 search，返回 list。仅用于向后兼容。"""
        q = (text or "").strip()
        if not q:
            return []
        tokens = [t for t in q.split() if t]
        if len(tokens) > 1:
            return self._search_multitoken_old(tokens, q)
        return self._search_single_old(tokens[0] if tokens else q)

    def _search_single_old(self, q: str):
        """旧版单关键词搜索。"""
        if len(q) < 3:
            return self._search_like_old(q)
        try:
            rows = self.conn.execute(
                "SELECT doc_id, title, snippet(docs_fts, 2, '[', ']', '...', 10) AS snip "
                "FROM docs_fts WHERE docs_fts MATCH ? "
                "ORDER BY rank", (q,)).fetchall()
        except sqlite3.OperationalError:
            return self._search_like_old(q)
        return [(r["doc_id"], r["title"], r["snip"]) for r in rows]

    def _search_multitoken_old(self, tokens: list[str], raw_query: str):
        """旧版多词联合搜索。"""
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
        return [(r["canonical_id"], r["title"],
                 self._snippet(r["content"], raw_query, width=15))
                for r in rows[:50]]

    def _search_like_old(self, q: str):
        like = f"%{q}%"
        rows = self.conn.execute(
            "SELECT d.canonical_id, d.title, v.content FROM documents d "
            "JOIN document_versions v ON v.version_id = d.current_version "
            "WHERE d.title LIKE ? OR v.content LIKE ?", (like, like)).fetchall()
        return [(r["canonical_id"], r["title"], self._snippet(r["content"], q))
                for r in rows]

    # ---- 搜索（新版，支持分页与来源过滤） ----
    def search(self, text: str, page: int = 0, per_page: int = 50,
               source: str = "") -> tuple:
        """返回 (hits: list, total: int)。支持分页和来源过滤。"""
        q = (text or "").strip()
        if not q:
            return [], 0
        tokens = [t for t in q.split() if t]
        if len(tokens) > 1:
            return self._search_multitoken(tokens, q, page, per_page, source)
        return self._search_single_paged(tokens[0] if tokens else q,
                                         page, per_page, source)

    def _search_single_paged(self, q: str, page: int = 0, per_page: int = 50,
                             source: str = ""):
        """单关键词搜索：>=3 字符走 trigram MATCH，短词走 LIKE。支持分页与来源过滤。"""
        if len(q) < 3:
            return self._search_like(q, page, per_page, source)
        params = [q]
        source_where = ""
        if source:
            source_where = " AND d.source_ids LIKE ?"
            params.append(f'%"{source}"%')
        try:
            total = self.conn.execute(
                "SELECT count(*) FROM docs_fts f"
                " JOIN documents d ON d.canonical_id = f.doc_id"
                " WHERE f.docs_fts MATCH ?" + source_where,
                params).fetchone()[0]
            rows = self.conn.execute(
                "SELECT f.doc_id, f.title,"
                " snippet(f.docs_fts, 2, '[', ']', '...', 10) AS snip"
                " FROM docs_fts f"
                " JOIN documents d ON d.canonical_id = f.doc_id"
                " WHERE f.docs_fts MATCH ?" + source_where
                + " ORDER BY rank LIMIT ? OFFSET ?",
                params + [per_page, page * per_page]).fetchall()
        except sqlite3.OperationalError:
            return self._search_like(q, page, per_page, source)
        return ([(r["doc_id"], r["title"], r["snip"]) for r in rows], total)

    def _search_multitoken(self, tokens: list[str], raw_query: str,
                           page: int = 0, per_page: int = 50,
                           source: str = ""):
        """多词联合搜索（AND）：对每个 token 搜 LIKE，取交集。支持分页与来源过滤。"""
        conditions = []
        params = []
        for t in tokens:
            like = f"%{t}%"
            conditions.append("(d.title LIKE ? OR v.content LIKE ?)")
            params.extend([like, like])
        if source:
            conditions.append("d.source_ids LIKE ?")
            params.append(f'%"{source}"%')
        where_clause = " AND ".join(conditions)
        total = self.conn.execute(
            "SELECT count(*) FROM documents d"
            " JOIN document_versions v ON v.version_id = d.current_version"
            " WHERE " + where_clause,
            params).fetchone()[0]
        rows = self.conn.execute(
            "SELECT d.canonical_id, d.title, v.content FROM documents d"
            " JOIN document_versions v ON v.version_id = d.current_version"
            " WHERE " + where_clause
            + " ORDER BY d.updated_at DESC LIMIT ? OFFSET ?",
            params + [per_page, page * per_page]).fetchall()
        return ([(r["canonical_id"], r["title"],
                  self._snippet(r["content"], raw_query, width=15))
                 for r in rows], total)

    def _search_like(self, q: str, page: int = 0, per_page: int = 50,
                     source: str = ""):
        like = f"%{q}%"
        params = [like, like]
        source_where = ""
        if source:
            source_where = " AND d.source_ids LIKE ?"
            params.append(f'%"{source}"%')
        total = self.conn.execute(
            "SELECT count(*) FROM documents d"
            " JOIN document_versions v ON v.version_id = d.current_version"
            " WHERE (d.title LIKE ? OR v.content LIKE ?)" + source_where,
            params).fetchone()[0]
        rows = self.conn.execute(
            "SELECT d.canonical_id, d.title, v.content FROM documents d"
            " JOIN document_versions v ON v.version_id = d.current_version"
            " WHERE (d.title LIKE ? OR v.content LIKE ?)" + source_where
            + " ORDER BY d.updated_at DESC LIMIT ? OFFSET ?",
            params + [per_page, page * per_page]).fetchall()
        return ([(r["canonical_id"], r["title"], self._snippet(r["content"], q))
                 for r in rows], total)

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

    # ---- HA / 复制状态（不提交，由调用方事务统一提交） ----
    def ha_get(self, key: str, default=None):
        row = self.conn.execute(
            "SELECT value FROM ha_state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def ha_set(self, key: str, value: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO ha_state(key, value) VALUES(?,?)", (key, value))

    def applied_max(self) -> int:
        v = self.ha_get("applied_max", "0")
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    def set_applied_max(self, value: int):
        self.ha_set("applied_max", str(int(value)))

    def apply_document(self, payload: dict):
        """直接重建一篇文档（documents+versions+fts+attachments），**不写 WAL**。

        供备机回放/重同步使用；与 store_document 写入逻辑等价，但绕过 record_change。
        """
        cid = payload["canonical_id"]
        cur = self.conn
        cur.execute(
            "INSERT OR REPLACE INTO documents("
            "canonical_id, title, current_version, source_ids, created_at, updated_at, "
            "doc_type, conflict, format, ingested, file_hash) "
            "VALUES(?,?,1,?,?,?,?,0,?,0,?)",
            (cid, payload.get("title", ""), json.dumps([payload.get("source", "")]),
             _now(), _now(), payload.get("doc_type", ""), payload.get("format", ""),
             payload.get("hash", "")))
        c = cur.execute(
            "INSERT INTO document_versions(doc_id, content, format, origin, author, "
            "updated_at, hash, parent_version, note) VALUES(?,?,?,?,?,?,?,?,?)",
            (cid, payload.get("content", ""), payload.get("format", ""),
             payload.get("origin", ""), "", _now(), payload.get("hash", ""),
             None, payload.get("note", "")))
        vid = c.lastrowid
        cur.execute("UPDATE documents SET current_version=? WHERE canonical_id=?",
                    (vid, cid))
        content = payload.get("content", "") or ""
        title = payload.get("title", "") or ""
        cur.execute("DELETE FROM docs_fts WHERE doc_id=?", (cid,))
        if content.strip():
            cur.execute("INSERT INTO docs_fts(doc_id, title, content) VALUES(?,?,?)",
                        (cid, title, content))
        cur.execute("DELETE FROM attachments WHERE doc_id=?", (cid,))
        for a in payload.get("attachments", []) or []:
            cur.execute(
                "INSERT INTO attachments(doc_id, version_id, kind, path, hash) "
                "VALUES(?,?,?,?,?)",
                (cid, vid, a.get("kind", ""), a.get("path", ""), a.get("hash", "")))


# ── WAL / 快照底层工具 ──────────────────────────────────────────────────────

def next_lsn(conn) -> int:
    """在同一事务内分配下一个全局 lsn（P0a 单节点 epoch=0，lsn 即 seq）。

    与业务写入同事务提交；升主后由上层以新 epoch 前缀续接（P1）。
    """
    conn.execute("UPDATE lsn_seq SET seq=seq+1")
    return conn.execute("SELECT seq FROM lsn_seq").fetchone()[0]


def rebuild_fts(store):
    """重建 docs_fts 全文索引（由 documents 当前版本反算）。

    快照/恢复后 FTS 虚表不随数据拷贝（不能 SELECT *），须显式重建。
    """
    conn = store.conn
    conn.execute("DELETE FROM docs_fts")
    rows = conn.execute(
        "SELECT d.canonical_id, d.title, v.content FROM documents d "
        "JOIN document_versions v ON v.version_id = d.current_version"
    ).fetchall()
    for r in rows:
        content = r["content"] or ""
        if content.strip():
            conn.execute(
                "INSERT INTO docs_fts(doc_id, title, content) VALUES(?,?,?)",
                (r["canonical_id"], r["title"], content))


def make_snapshot_db(src_conn, dst_path: str):
    """一致性快照：排除 ha_state / docs_fts 虚表 / vec0 向量虚表，

    其余用户表经 ATTACH 逐表 `INSERT INTO snap.t SELECT * FROM main.t` 拷贝。
    FTS/向量由恢复侧 rebuild_fts 重建（避免 SELECT * 拷贝虚表）。
    """
    import re
    import sqlite3  # noqa: F401（保证 sqlite3 可用）

    if os.path.exists(dst_path):
        os.remove(dst_path)
    src_conn.execute("ATTACH DATABASE ? AS snap", (dst_path,))
    try:
        # 识别虚表（FTS5 / vec0）及其 shadow 表，快照排除，恢复后重建
        virtual_names = [r["name"] for r in src_conn.execute(
            "SELECT name FROM sqlite_master WHERE sql LIKE 'CREATE VIRTUAL TABLE%'"
        ).fetchall()]

        def _is_virtual(name):
            if name in ("ha_state",):
                return True
            if name.startswith("sqlite_"):
                return True
            for v in virtual_names:
                if name == v or name.startswith(v + "_"):
                    return True
            return False

        rows = src_conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall()
        for r in rows:
            name = r["name"]
            sql = r["sql"]
            if _is_virtual(name):
                continue
            # 把 DDL 中的表名改写为 snap.<name>，其余（列/约束）原样保留
            m = re.match(
                r'^(CREATE\s+(?:TEMP\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?)'
                r'(["\']?)([A-Za-z0-9_]+)\2', sql, re.IGNORECASE)
            if not m:
                continue
            new_sql = m.group(1) + m.group(2) + "snap." + m.group(3) + m.group(2) \
                + sql[m.end():]
            src_conn.execute(new_sql)
            src_conn.execute(f"INSERT INTO snap.{name} SELECT * FROM main.{name}")
        src_conn.commit()
    except Exception:
        try:
            src_conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            src_conn.execute("DETACH DATABASE snap")
        except Exception:
            pass
