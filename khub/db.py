import binascii
import sqlite3
import hashlib
import json
import logging
import os
import secrets
import threading
import time
from datetime import datetime, timedelta
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
        # check_same_thread=False: API 用 ThreadingHTTPServer 在后台线程访问同一连接，
        # 必须允许跨线程；isolation_level=None: 关闭隐式事务，由 transaction() 显式管理
        # BEGIN/COMMIT（避免「cannot start a transaction within a transaction」）。
        self.conn = sqlite3.connect(self.path, check_same_thread=False,
                                    isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()  # 序列化写，避免共享连接并发损坏
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
        # WAL 暂存表：触发器只写此轻量表（与主写入同事务、几乎不失败），
        # 由 WalFlusher 在独立连接上 best-effort 落 replication_log（M2/A5 解耦）。
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS wal_staging(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op TEXT, table_name TEXT, row_id TEXT,
            payload TEXT, at TEXT)""")
        self._migrate()
        self.conn.commit()
        # WAL 模式：允许并发读/写，避免 delete 模式的读写锁互相阻塞
        self.conn.execute("PRAGMA journal_mode=WAL")
        # documents 复制触发器（仅 Primary 自动记账；备机回放前关 recursive_triggers）
        from .replication import install_triggers, WalFlusher
        install_triggers(self.conn, "documents", pk="canonical_id")
        # WAL 解耦：暂存表由后台 flusher best-effort 落盘（M2/A5）
        self.wal_flusher = WalFlusher(self)
        if self.path != ":memory:":
            self.wal_flusher.start()
        # 0.2.7 临床增强业务表
        self._init_clinical_v2_tables(self.conn)
        # 0.2.9 知识库增强：标签 + 收藏
        from .replication import install_triggers as _it
        self.conn.execute("""CREATE TABLE IF NOT EXISTS doc_tags (
            id INTEGER PRIMARY KEY, doc_id TEXT NOT NULL,
            tag TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(doc_id, tag))""")
        _it(self.conn, "doc_tags")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY, doc_id TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT (datetime('now')))""")
        _it(self.conn, "favorites")
        # 0.2.10 课程运营管理系统
        self._init_course_tables(self.conn)
        # 0.2.11 微信公众号
        from .replication import install_triggers as _wxtrig
        self.conn.execute("""CREATE TABLE IF NOT EXISTS wechat_articles (
            id INTEGER PRIMARY KEY, doc_id TEXT, title TEXT NOT NULL, author TEXT DEFAULT '',
            digest TEXT DEFAULT '', content TEXT NOT NULL,
            content_source_url TEXT DEFAULT '', thumb_media_id TEXT DEFAULT '',
            need_open_comment INTEGER DEFAULT 0, only_fans_can_comment INTEGER DEFAULT 0,
            wechat_media_id TEXT DEFAULT '', wechat_url TEXT DEFAULT '',
            status TEXT DEFAULT 'draft',
            created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')))""")
        _wxtrig(self.conn, "wechat_articles")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS wechat_schedules (
            id INTEGER PRIMARY KEY, article_id INTEGER NOT NULL,
            publish_at TEXT NOT NULL, tag_id INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending', error_msg TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')), published_at TEXT)""")
        _wxtrig(self.conn, "wechat_schedules")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS wechat_followers (
            openid TEXT PRIMARY KEY, subscribe INTEGER DEFAULT 1,
            nickname TEXT DEFAULT '', sex INTEGER DEFAULT 0,
            language TEXT DEFAULT 'zh_CN', city TEXT DEFAULT '', province TEXT DEFAULT '',
            country TEXT DEFAULT '', headimgurl TEXT DEFAULT '',
            subscribe_time TEXT, unionid TEXT DEFAULT '', remark TEXT DEFAULT '',
            tagid_list TEXT DEFAULT '[]', subscribe_scene TEXT DEFAULT '',
            last_sync_at TEXT DEFAULT (datetime('now')))""")
        _wxtrig(self.conn, "wechat_followers")
        # 0.3.0 多用户鉴权
        from .replication import install_triggers as _authtrig
        self.conn.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, display_name TEXT DEFAULT '',
            role TEXT DEFAULT 'admin', active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')))""")
        # 首次启动创建默认 admin 用户（在 install_triggers 之前，避免 WAL 记录）
        admin_exists = self.conn.execute(
            "SELECT 1 FROM users WHERE username='admin'").fetchone()
        if not admin_exists:
            pwd = os.environ.get("KHUB_ADMIN_PASSWORD", secrets.token_urlsafe(12))
            salt = os.urandom(16)
            dk = hashlib.pbkdf2_hmac("sha256", pwd.encode(), salt, 100000)
            pwd_hash = binascii.hexlify(salt + dk).decode()
            self.conn.execute(
                "INSERT INTO users (username, password_hash, display_name, role) "
                "VALUES (?, ?, ?, ?)",
                ("admin", pwd_hash, "系统管理员", "admin"))
            logging.getLogger("khub.auth").info(
                "默认 admin 用户已创建，密码: %s", pwd)
            if not os.environ.get("KHUB_ADMIN_PASSWORD"):
                print(f"\n⚠ 默认管理员密码：{pwd}"
                      "  （请登录后修改，或设置 KHUB_ADMIN_PASSWORD 环境变量）\n")
        _authtrig(self.conn, "users")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS auth_tokens (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
            token TEXT NOT NULL UNIQUE, expires_at TEXT,
            created_at TEXT DEFAULT (datetime('now')))""")
        _authtrig(self.conn, "auth_tokens")
        # 0.5.0 中医知识图谱
        from .knowledge.schema import init as _kg_init
        _kg_init(self.conn)
        # 0.6.0 开放平台 Webhook 订阅与投递
        from .replication import install_triggers as _whtrig
        self.conn.execute("""CREATE TABLE IF NOT EXISTS webhook_subscriptions (
            id INTEGER PRIMARY KEY, event TEXT NOT NULL, url TEXT NOT NULL,
            secret TEXT DEFAULT '', active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')))""")
        _whtrig(self.conn, "webhook_subscriptions")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS webhook_deliveries (
            id INTEGER PRIMARY KEY, subscription_id INTEGER, event TEXT,
            payload TEXT, status TEXT, response_code INTEGER, response_body TEXT,
            created_at TEXT DEFAULT (datetime('now')))""")
        _whtrig(self.conn, "webhook_deliveries")
        # 0.6.1 实时协作与消息推送：通知系统
        from .replication import install_triggers as _ntrig
        self.conn.execute("""CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT NOT NULL,
            body TEXT, event_type TEXT, resource_type TEXT, resource_id TEXT,
            read INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')))""")
        _ntrig(self.conn, "notifications")
        # 0.6.2 高级BI与报表
        from .replication import install_triggers as _rtrig
        self.conn.execute("""CREATE TABLE IF NOT EXISTS report_templates (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT,
            query TEXT NOT NULL, chart_type TEXT DEFAULT 'table',
            format TEXT DEFAULT 'table', config TEXT,
            created_at TEXT DEFAULT (datetime('now')))""")
        _rtrig(self.conn, "report_templates")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS report_jobs (
            id INTEGER PRIMARY KEY, template_id INTEGER, status TEXT DEFAULT 'pending',
            output TEXT, error TEXT, created_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT)""")
        _rtrig(self.conn, "report_jobs")
        # 0.7.1 工作流引擎
        from .replication import install_triggers as _wftrig
        self.conn.execute("""CREATE TABLE IF NOT EXISTS workflow_definitions (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT,
            steps TEXT NOT NULL, version INTEGER DEFAULT 1, active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')))""")
        _wftrig(self.conn, "workflow_definitions")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS workflow_instances (
            id INTEGER PRIMARY KEY, definition_id INTEGER NOT NULL,
            entity_type TEXT, entity_id TEXT, status TEXT DEFAULT 'running',
            current_step TEXT, context TEXT, history TEXT,
            created_at TEXT DEFAULT (datetime('now')), completed_at TEXT)""")
        _wftrig(self.conn, "workflow_instances")

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
        except Exception:  # nosec B110
            pass  # 列已存在

    def transaction(self):
        """上下文管理器：统一 begin/commit/rollback。

        用法::

            with store.transaction():
                store.store_document(doc)   # 内部不再各自 commit

        回放/批量写入须包在此内，保证 WAL 与主表同一事务一次性提交。
        """
        class _Tx:
            def __init__(self, store):
                self.store = store
                self.conn = store.conn
            def __enter__(self):
                self.store._lock.acquire()
                self.conn.execute("BEGIN")
                return self.conn
            def __exit__(self, exc, *_):
                try:
                    if exc:
                        self.conn.rollback()
                    else:
                        self.conn.commit()
                finally:
                    self.store._lock.release()
                return False
        return _Tx(self)

    def flush_wal(self):
        """同步刷盘：将 wal_staging 暂存行落 replication_log（测试/关闭前调用）。

        后台 flusher 线程已在持续刷盘；此方法用于确定性断言与优雅关闭。
        """
        if getattr(self, "wal_flusher", None) is not None:
            self.wal_flusher.flush()

    def prune_wal(self, keep: Optional[int] = None,
                  keep_days: Optional[float] = None) -> int:
        """I5 — WAL 归档窗口：清理已推送（applied=1）的旧 WAL，防磁盘膨胀。

        仅删 `applied=1` 的行，**绝不删 pending（applied=0）**——未推送的 WAL 是
        PITR/副本的唯一来源，删了会丢数据。保留窗口由二选一（或多选）控制：
        - `keep`：本地保留最近 N 条已 applied WAL（其余更旧的删除）；
        - `keep_days`：保留最近 D 天内的已 applied WAL（`at` 早于 cutoff 的删除）。
        两者皆 `None` 时回退读环境变量 `KHUB_WAL_KEEP` / `KHUB_WAL_KEEP_DAYS`；
        若仍都为空 → 不清理（向后兼容：默认保留全量，PITR 无界）。
        PITR 回放走副本（replica.fetch_changes）而非本地 replication_log，故本地
        清理不影响 PITR；清理后 SQLite 复用空闲页，文件大小随窗口收敛而非无限增长。
        返回删除条数。
        """
        if keep is None:
            v = os.environ.get("KHUB_WAL_KEEP")
            keep = int(v) if v else None
        if keep_days is None:
            v = os.environ.get("KHUB_WAL_KEEP_DAYS")
            keep_days = float(v) if v else None
        if keep is None and keep_days is None:
            return 0

        conn = self.conn
        deleted = 0
        # 按条数：保留最近 keep 条，删除更旧的 applied 行
        if keep is not None and keep >= 0:
            if keep == 0:
                deleted += conn.execute(
                    "DELETE FROM replication_log WHERE applied=1").rowcount
            else:
                # (keep-1) 即第 keep 新（最大）条的 id；其之前的更旧 applied 行皆删，
                # 留下最近 keep 条。applied 总数 <= keep 时 row 为 None → 不删。
                row = conn.execute(
                    "SELECT id FROM replication_log WHERE applied=1 "
                    "ORDER BY id DESC LIMIT 1 OFFSET ?", (keep - 1,)).fetchone()
                if row is not None:
                    cid = row["id"]
                    deleted += conn.execute(
                        "DELETE FROM replication_log WHERE applied=1 AND id < ?",
                        (cid,)).rowcount
        # 按天数：删除 at 早于 cutoff 的 applied 行
        if keep_days is not None and keep_days >= 0:
            cutoff = (datetime.now() - timedelta(days=keep_days)).strftime(
                "%Y-%m-%dT%H:%M:%S")
            deleted += conn.execute(
                "DELETE FROM replication_log WHERE applied=1 AND at < ?",
                (cutoff,)).rowcount
        conn.commit()
        return deleted

    def close(self):
        """优雅关闭：停 flusher、末次刷盘、关连接。"""
        flusher = getattr(self, "wal_flusher", None)
        if flusher is not None:
            try:
                flusher.stop()
                flusher.flush()
            except Exception:  # nosec B110
                pass
        try:
            self.conn.close()
        except Exception:  # nosec B110
            pass

    def __del__(self):
        try:
            self.close()
        except Exception:  # nosec B110
            pass

    def store_document(self, doc: CanonicalDoc, parent_version: Optional[int] = None) -> int:
        with self._lock:
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

    def get_version(self, doc_id: str, version_id: int):
        """返回指定文档的指定版本。"""
        return self.conn.execute(
            "SELECT * FROM document_versions WHERE doc_id=? AND version_id=?",
            (doc_id, version_id)).fetchone()

    def resolve_conflict(self, canonical_id: str, keep_version_id: int):
        """解决冲突：将所选版本内容写入新版本，清除冲突标记。"""
        with self._lock:
            ver = self.conn.execute(
                "SELECT * FROM document_versions WHERE version_id=? AND doc_id=?",
                (keep_version_id, canonical_id)).fetchone()
            if not ver:
                raise ValueError(
                    f"version {keep_version_id} not found for doc {canonical_id}")
            # 写入新版本表示解决结果
            c = self.conn.execute(
                "INSERT INTO document_versions(doc_id, content, format, origin, "
                "author, updated_at, hash, parent_version, note) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (canonical_id, ver["content"], ver["format"], "webui-resolve", "",
                 _now(), compute_hash(ver["content"]), keep_version_id,
                 f"conflict resolved, kept version {keep_version_id}"))
            vid = c.lastrowid
            self.conn.execute(
                "UPDATE documents SET conflict=0, current_version=?, updated_at=? "
                "WHERE canonical_id=?",
                (vid, _now(), canonical_id))
            # 同步 FTS
            self.conn.execute("DELETE FROM docs_fts WHERE doc_id=?",
                              (canonical_id,))
            if ver["content"] and ver["content"].strip():
                title_row = self.conn.execute(
                    "SELECT title FROM documents WHERE canonical_id=?",
                    (canonical_id,)).fetchone()
                title_row = title_row["title"] if title_row else ""
                self.conn.execute(
                    "INSERT INTO docs_fts(doc_id, title, content) VALUES(?,?,?)",
                    (canonical_id, title_row, ver["content"]))
            self.conn.commit()

    def set_sync_state(self, source_id: str, doc_id: str, etag: str, h: str):
        with self._lock:
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
        with self._lock:
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
        with self._lock:
            self.conn.execute("UPDATE documents SET conflict=? WHERE canonical_id=?",
                              (1 if flag else 0, doc_id))
            self.conn.commit()

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

    # ---- 搜索（向后兼容接口：返回 list，委托给新版分页 search） ----
    def search_old(self, text: str) -> list:
        """旧接口兼容：返回 hit 列表（与新版 search 行为一致，仅去掉分页元组）。"""
        return self.search(text)[0]

    # ---- 搜索（支持分页与来源过滤） ----
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
        with self._lock:
            self.conn.execute(
                "INSERT INTO files(sha256, path, size, format, stored_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(sha256) DO UPDATE SET path=excluded.path, size=excluded.size",
                (sha256, path, size, fmt, _now()))
            self.conn.commit()

    def add_ebook(self, canonical_id: str, title: str, fmt: str, file_hash: str,
                  source_id: str, meta: Optional[dict] = None):
        with self._lock:
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
        with self._lock:
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
        with self._lock:
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
        with self._lock:
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


    def _init_clinical_v2_tables(self, conn):
        """0.2.7 临床增强的业务表（遵循"业务模块只加表"）。"""
        from .replication import install_triggers
        conn.execute("""
            CREATE TABLE IF NOT EXISTS twin_versions (
                id INTEGER PRIMARY KEY,
                patient_id INTEGER NOT NULL,
                base_record_id INTEGER DEFAULT 0,
                base_consult_id INTEGER DEFAULT 0,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""")
        install_triggers(conn, "twin_versions")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS consult_sessions (
                id INTEGER PRIMARY KEY,
                patient_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""")
        install_triggers(conn, "consult_sessions")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS consult_messages (
                id INTEGER PRIMARY KEY,
                session_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""")
        install_triggers(conn, "consult_messages")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS followup_plans (
                id INTEGER PRIMARY KEY,
                patient_id INTEGER NOT NULL,
                due_date TEXT NOT NULL,
                reason TEXT,
                status TEXT DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""")
        install_triggers(conn, "followup_plans")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS followup_reminders (
                id INTEGER PRIMARY KEY,
                plan_id INTEGER NOT NULL,
                due_date TEXT NOT NULL,
                channel TEXT DEFAULT 'internal',
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""")
        install_triggers(conn, "followup_reminders")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS followup_adherence (
                id INTEGER PRIMARY KEY,
                plan_id INTEGER NOT NULL,
                attended INTEGER NOT NULL DEFAULT 0,
                note TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""")
        install_triggers(conn, "followup_adherence")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS record_struct (
                id INTEGER PRIMARY KEY,
                source TEXT NOT NULL,
                source_id INTEGER NOT NULL,
                differentiation_norm TEXT,
                syndrome TEXT,
                formula TEXT,
                method TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""")
        install_triggers(conn, "record_struct")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS syndrome_vocab (
                canonical TEXT PRIMARY KEY,
                aliases TEXT NOT NULL
            )""")
        install_triggers(conn, "syndrome_vocab")

    @staticmethod
    def _init_course_tables(conn):
        """0.2.10 课程运营管理系统——课程/课时/学员/成绩。"""
        from .replication import install_triggers as _it
        conn.execute("""CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT,
            teacher TEXT, start_date TEXT, end_date TEXT,
            capacity INTEGER DEFAULT 0, status TEXT DEFAULT 'active',
            price REAL DEFAULT 0, created_at TEXT DEFAULT (datetime('now')))""")
        _it(conn, "courses")
        conn.execute("""CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL,
            title TEXT NOT NULL, lesson_date TEXT NOT NULL,
            start_time TEXT, end_time TEXT, location TEXT, content TEXT,
            created_at TEXT DEFAULT (datetime('now')))""")
        _it(conn, "lessons")
        conn.execute("""CREATE TABLE IF NOT EXISTS enrollments (
            id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL,
            student_name TEXT NOT NULL, student_phone TEXT,
            status TEXT DEFAULT 'enrolled',
            enrolled_at TEXT DEFAULT (datetime('now')))""")
        _it(conn, "enrollments")
        conn.execute("""CREATE TABLE IF NOT EXISTS grades (
            id INTEGER PRIMARY KEY, enrollment_id INTEGER NOT NULL,
            lesson_id INTEGER, score REAL, comment TEXT,
            created_at TEXT DEFAULT (datetime('now')))""")
        _it(conn, "grades")


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
    """一致性快照：排除 ha_state / replication_log / lsn_seq 等节点本机记账表，
    以及 docs_fts 虚表 / vec0 向量虚表。

    其余用户表经 ATTACH 逐表 `INSERT INTO snap.t SELECT * FROM main.t` 拷贝。
    FTS/向量由恢复侧 rebuild_fts 重建（避免 SELECT * 拷贝虚表）。
    ha_state / replication_log / lsn_seq 由 `_EXCLUDE_TABLES` 控制：恢复库须自建，
    否则 lsn_seq 与主库对齐会导致备机升主后 lsn 重复/错乱、replication_log 被二次回放。
    """
    import re
    import sqlite3  # noqa: F401（保证 sqlite3 可用）

    # 将 WAL checkpoint 到主 DB，确保快照包含全部已提交数据
    # 注意：FULL 会阻塞等待，TRUNCATE 会重置 WAL（可能影响 vec0 虚表），
    # 用 PASSIVE 只 checkpoint 已完成的帧，不等待活跃读事务。
    # best-effort：并发写事务（如 WalFlusher 独立连接的 BEGIN）可能短暂持锁，
    # 导致 SQLITE_LOCKED/BUSY；checkpoint 失败不阻断快照（已提交数据仍可读）。
    try:
        src_conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
    except Exception as e:  # pragma: no cover - 依赖/并发边界
        logging.warning("[snapshot] wal_checkpoint 跳过（并发锁，已提交数据仍纳入快照）: %s", e)

    if os.path.exists(dst_path):
        os.remove(dst_path)
    src_conn.execute("ATTACH DATABASE ? AS snap", (dst_path,))
    try:
        # 识别虚表（FTS5 / vec0）及其 shadow 表，快照排除，恢复后重建
        virtual_names = [r["name"] for r in src_conn.execute(
            "SELECT name FROM sqlite_master WHERE sql LIKE 'CREATE VIRTUAL TABLE%'"
        ).fetchall()]

        # 复制记账表（WAL 日志 + 全局 lsn 序列器）不进入快照：
        # - replication_log：主库的 WAL 变更流水，恢复时若一并拷入会被二次回放。
        # - lsn_seq：全局 lsn 分配器；备机恢复应自起 lsn（各自 epoch），拷贝会令
        #   恢复库 lsn_seq 与主库对齐，后续升主可能产生重复/错乱 lsn。
        # - ha_state：节点角色/复制锁等本机状态，备机须保留自身状态。
        _EXCLUDE_TABLES = {"ha_state", "replication_log", "lsn_seq", "wal_staging"}

        def _is_virtual(name):
            if name in _EXCLUDE_TABLES:
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
        except Exception:  # nosec B110
            pass
        raise
    finally:
        try:
            src_conn.execute("DETACH DATABASE snap")
        except Exception:  # nosec B110
            pass
