"""Replication interface and local reference implementation for khub disaster recovery.

Provides:
- Change / WALLog: row-level change tracking via replication_log table.
- export_snapshot / import_snapshot_manifest: snapshot metadata helpers.
- ReplicaTarget: abstract interface for remote/standby replica targets.
- LocalFileReplica: filesystem-based reference implementation.
- record_change: convenience hook for core functions to log changes.
"""

import dataclasses
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from typing import Any, Optional

import khub.db


@dataclasses.dataclass
class Change:
    """A single row-level change recorded in replication_log."""
    op: str          # "insert" | "update" | "delete"
    table: str
    row_id: str
    payload: str     # JSON
    at: str = ""


class WALLog:
    """Write-ahead change log backed by the replication_log table.

    Every mutation to core tables should be recorded here so that standby
    / disaster-recovery replicas can replay changes and converge.
    """

    def __init__(self, store):
        self.store = store
        self.conn = store.conn
        # 建表不提交：若调用方已在事务内（如 store_document），建表随外层一并提交。
        self.conn.execute("""CREATE TABLE IF NOT EXISTS replication_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lsn INTEGER,
            op TEXT, table_name TEXT, row_id TEXT,
            payload TEXT, at TEXT, applied INTEGER DEFAULT 0)""")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS lsn_seq(seq INTEGER NOT NULL)")
        if self.conn.execute("SELECT COUNT(*) FROM lsn_seq").fetchone()[0] == 0:
            self.conn.execute("INSERT INTO lsn_seq(seq) VALUES(0)")

    def record(self, op: str, table: str, row_id: str, payload: str):
        """Insert a new change entry (applied=0). 不提交——由调用方事务统一提交。

        使用 next_lsn 在同一事务内分配全局 lsn，与业务写入同源可比。
        """
        from .db import next_lsn
        lsn = next_lsn(self.conn)
        at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        self.conn.execute(
            "INSERT INTO replication_log(lsn, op, table_name, row_id, payload, at) "
            "VALUES(?,?,?,?,?,?)",
            (lsn, op, table, str(row_id), payload, at))

    def pending(self) -> list[dict[str, Any]]:
        """Return all un-applied changes ordered by id."""
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM replication_log WHERE applied=0 ORDER BY id").fetchall()]

    def mark_applied(self, ids: list[int]):
        """Mark changes as applied so they are excluded from future pending()."""
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        self.conn.execute(
            f"UPDATE replication_log SET applied=1 WHERE id IN ({placeholders})",
            ids)
        self.conn.commit()


def export_snapshot(store) -> dict:
    """Return a manifest describing the current database state.

    The manifest includes per-table row counts and the max replication_log id
    so a replica can determine which WAL entries to replay after restoring
    this snapshot.
    """
    tables = [
        "documents", "document_versions", "attachments", "patients", "records",
        "consultations", "schedules", "appointments", "visits", "embeddings",
        "vec_meta", "files", "ebook_meta", "sync_states",
    ]
    counts: dict[str, int] = {}
    total = 0
    for t in tables:
        try:
            n = store.conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"]
        except Exception:
            n = 0
        counts[t] = n
        total += n

    try:
        max_rid = store.conn.execute(
            "SELECT COALESCE(MAX(lsn), 0) AS m FROM replication_log"
        ).fetchone()["m"]
    except Exception:
        max_rid = 0

    return {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "tables": counts,
        "max_replication_id": max_rid,
        "total_rows": total,
    }


def import_snapshot_manifest(store, manifest: dict) -> dict:
    """Validate a snapshot manifest and persist its metadata.

    This is a local reference implementation. Future remote implementations
    will parse the manifest, copy the database file, and replay WAL entries.
    """
    required_keys = {"at", "tables", "max_replication_id", "total_rows"}
    missing = required_keys - set(manifest.keys())
    if missing:
        raise ValueError(f"manifest missing keys: {missing}")
    if not isinstance(manifest["tables"], dict):
        raise ValueError("manifest.tables must be a dict")
    if not isinstance(manifest["max_replication_id"], int):
        raise ValueError("manifest.max_replication_id must be int")

    store.conn.execute(
        "CREATE TABLE IF NOT EXISTS snapshot_meta(key TEXT PRIMARY KEY, value TEXT)")
    store.conn.execute(
        "INSERT OR REPLACE INTO snapshot_meta(key, value) VALUES('last_manifest', ?)",
        (json.dumps(manifest),))
    store.conn.execute(
        "INSERT OR REPLACE INTO snapshot_meta(key, value) VALUES('last_snapshot_at', ?)",
        (manifest["at"],))
    store.conn.commit()
    return {"status": "ok", "manifest_at": manifest["at"]}


class ReplicaTarget:
    """Interface contract for a replica target.

    Concrete implementations (e.g. SshReplica, S3Replica) must implement
    all methods to enable push-based replication.
    """

    @property
    def name(self) -> str:
        raise NotImplementedError

    def push_snapshot(self, meta: dict, db_path: str = ""):
        """Push a full snapshot (manifest + optional db file) to the target."""
        raise NotImplementedError

    def push_changes(self, changes: list):
        """Push a batch of WAL changes to the target."""
        raise NotImplementedError

    def fetch_snapshot(self) -> dict | None:
        """拉取远端快照 manifest（无则返回 None）。"""
        raise NotImplementedError

    def fetch_changes(self) -> list:
        """拉取远端 WAL 变更列表（每项为含 id 的 dict）。"""
        raise NotImplementedError

    def health(self) -> tuple[bool, str]:
        """Return (is_alive: bool, status_message: str)."""
        raise NotImplementedError

    def best_snapshot_for(self, target_lsn: int | None = None) -> dict | None:
        """返回 lsn<=target_lsn 中最新的一份快照（target_lsn=None 返回最新）。"""
        raise NotImplementedError


class LocalFileReplica(ReplicaTarget):
    """Filesystem-based replica — writes snapshot & WAL to a local directory.

    Snapshots are kept multi-version under {dir}/snapshots/<timestamp>.db
    (keep 最近 N 份，默认 5)，供误删/改坏后回退。注意：同机另一目录**不算**
    异地灾备，仅防误删（见 design §0 / review_impl I7）。
    """

    def __init__(self, dir_path: str, keep: int = 5):
        self.dir = dir_path
        self.keep = keep
        os.makedirs(dir_path, exist_ok=True)
        os.makedirs(os.path.join(dir_path, "snapshots"), exist_ok=True)

    @property
    def name(self) -> str:
        return f"local:{self.dir}"

    def push_snapshot(self, meta: dict, db_path: str = ""):
        """写最新 manifest 到 {dir}/snapshot.json，并多版本存 db 到
        {dir}/snapshots/<timestamp>.db（保留最近 keep 份）；同时写同名的
        <timestamp>.json manifest（含 lsn/at），供 PITR 选快照。"""
        meta = dict(meta)
        meta["at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        with open(os.path.join(self.dir, "snapshot.json"), "w") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        if db_path and os.path.isfile(db_path):
            ts = time.strftime("%Y%m%dT%H%M%S")
            dest = os.path.join(self.dir, "snapshots", f"{ts}.db")
            if os.path.exists(dest):
                ts = f"{ts}-{int(time.time()*1000)}"
                dest = os.path.join(self.dir, "snapshots", f"{ts}.db")
            shutil.copy2(db_path, dest)
            # 多版本 manifest：与 db 同 ts 的 json 落地（含 lsn/at）
            with open(os.path.join(self.dir, "snapshots", f"{ts}.json"), "w") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            self._prune_snapshots()
        return meta

    def list_versions(self) -> list:
        """返回按时间升序的快照版本列表
        `[{ts, db, manifest, lsn, at}]`（lsn = manifest.max_replication_id）。"""
        d = os.path.join(self.dir, "snapshots")
        if not os.path.isdir(d):
            return []
        versions = []
        for fn in os.listdir(d):
            if not fn.endswith(".json"):
                continue
            ts = fn[: -len(".json")]
            db = os.path.join(d, f"{ts}.db")
            if not os.path.isfile(db):
                continue
            try:
                with open(os.path.join(d, fn)) as f:
                    manifest = json.load(f)
            except Exception:
                continue
            versions.append({
                "ts": ts,
                "db": db,
                "manifest": manifest,
                "lsn": manifest.get("max_replication_id", 0),
                "at": manifest.get("at", ""),
            })
        versions.sort(key=lambda v: v["ts"])
        return versions

    def best_snapshot_for(self, target_lsn: int | None = None) -> dict | None:
        """返回 `lsn<=target_lsn` 中最新的一份（target_lsn=None 返回最新）。

        用于 PITR：恢复点 = 选 lsn 不超过目标时间点的、最新的完整快照，
        再 `replay_from(changes, target_lsn=target)` 回放增量 WAL 至目标。
        无候选返回 None。
        """
        versions = self.list_versions()
        if not versions:
            return None
        if target_lsn is None:
            return versions[-1]
        candidates = [v for v in versions if v["lsn"] <= target_lsn]
        return candidates[-1] if candidates else None

    def _prune_snapshots(self):
        d = os.path.join(self.dir, "snapshots")
        files = [os.path.join(d, f) for f in os.listdir(d)
                 if f.endswith(".db")]
        files.sort(key=lambda p: os.path.getmtime(p))
        for old in files[:-self.keep]:
            try:
                os.remove(old)
            except OSError:
                pass

    def list_snapshots(self) -> list:
        """返回快照 db 路径列表（按修改时间升序）。"""
        d = os.path.join(self.dir, "snapshots")
        if not os.path.isdir(d):
            return []
        files = [os.path.join(d, f) for f in os.listdir(d)
                 if f.endswith(".db")]
        files.sort(key=lambda p: os.path.getmtime(p))
        return files

    def push_changes(self, changes: list):
        """Append WAL changes as NDJSON lines to {dir}/wal.ndjson（含 id 以便幂等回放）。"""
        path = os.path.join(self.dir, "wal.ndjson")
        with open(path, "a") as f:
            for ch in changes:
                f.write(json.dumps(_to_wal_dict(ch), ensure_ascii=False) + "\n")

    def fetch_snapshot(self) -> dict | None:
        p = os.path.join(self.dir, "snapshot.json")
        if not os.path.isfile(p):
            return None
        with open(p) as f:
            return json.load(f)

    def fetch_changes(self) -> list:
        p = os.path.join(self.dir, "wal.ndjson")
        if not os.path.isfile(p):
            return []
        out = []
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def health(self) -> tuple[bool, str]:
        ok = os.access(self.dir, os.W_OK)
        return (ok, "writable" if ok else "not writable")


def manual_record_change(store, op: str, table: str, row_id: str, payload_json: str):
    """手动补记一条变更（非主路径），写入 `wal_staging`，由 WalFlusher 落盘。

    P0a 主路径已由 DB 触发器（install_triggers）自动记账。此处仅用于触发器覆盖
    不到的角落场景，与触发器统一走 `wal_staging` → replication_log 解耦路径。
    """
    at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    store.conn.execute(
        "INSERT INTO wal_staging(op, table_name, row_id, payload, at) "
        "VALUES(?,?,?,?,?)",
        (op, table, str(row_id), payload_json, at))


# 兼容别名（原 record_change，已改名）。既有测试/调用方继续可用。
record_change = manual_record_change


class UnknownTableError(Exception):
    """回放时遇到未注册（未知）表的变更。"""
    pass


# ── 触发器（仅 Primary 安装，自动记账，与主写入同事务） ────────────────────────

TRIGGERS_INSTALLED = False

# 被复制的表 → 主键列（用于 row_id 与触发器定位）
_REPLICATED_TABLES = {
    "documents": "canonical_id",
    "patients": "id",
    "records": "id",
    "consultations": "id",
    "schedules": "id",
    "appointments": "id",
    "visits": "id",
}


def install_triggers(conn, table: str, pk: str | None = None):
    """为单张表安装 AFTER INSERT/UPDATE/DELETE 三个触发器，自动落 replication_log。

    - pk 缺省时用 PRAGMA table_info 找 pk==1 的列作为 row_id。
    - payload 用 json_object(col, ref.col, ...) 序列化；BLOB 列用 base64() 包裹
      （json1 不表示 BLOB，否则损坏）。
    - 触发器用 CREATE TRIGGER IF NOT EXISTS，可重复安装（幂等）。
    - 触发器内先 `UPDATE lsn_seq SET seq=seq+1` 再写入，lsn 与业务同事务。
    """
    if pk is None:
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        pk = None
        for c in cols:
            if c["pk"] == 1:
                pk = c["name"]
                break
        if pk is None:                      # 复合主键：退化为第一列
            pk = cols[0]["name"] if cols else None
    if pk is None:
        raise ValueError(f"无法确定表 {table} 的主键，无法安装触发器")
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    col_names = [c["name"] for c in cols]
    blob_cols = {c["name"] for c in cols
                 if (c["type"] or "").upper().startswith("BLOB")}

    def payload_expr(ref: str) -> str:
        parts = []
        for cn in col_names:
            if cn in blob_cols:
                parts.append(f"'{cn}', base64({ref}.{cn})")
            else:
                parts.append(f"'{cn}', {ref}.{cn}")
        return "json_object(" + ", ".join(parts) + ")"

    for op in ("insert", "update", "delete"):
        ref = "NEW" if op != "delete" else "OLD"
        trigger_name = f"khub_rpl_{table}_{op}"
        # 触发器只写轻量 wal_staging（与主写入同事务、几乎不失败）。
        # replication_log + lsn 由 WalFlusher 在独立连接上 best-effort 落盘，
        # 从而 WAL 写失败仅告警、绝不回滚业务写（M2/A5：解耦）。
        body = (
            f"INSERT INTO wal_staging(op, table_name, row_id, payload, at) "
            f"VALUES('{op}', '{table}', CAST({ref}.{pk} AS TEXT), "
            f"{payload_expr(ref)}, strftime('%Y-%m-%dT%H:%M:%S','now'));"
        )
        # WHEN 守卫：回放（备机）期间设置 ha_state.__replay_lock='1'，
        # 触发器整体跳过 → 备机回放不二次写本机 replication_log。
        # 注：PRAGMA recursive_triggers=OFF 仅抑制递归触发链，无法阻止首层触发；
        # 故用 WHEN 守卫作为真正的防重入机制（见 replay_from）。
        when = ("WHEN COALESCE((SELECT value FROM ha_state "
                "WHERE key='__replay_lock'), '0') = '0'")
        # 先 DROP 再 CREATE：触发器由当前 schema 代码生成（评审 LOW L1）。
        # 若只用 IF NOT EXISTS，旧触发器（含旧列清单）不会被更新，迁移新增列后
        # WAL 静默漏记该列；DROP+CREATE 保证每次（重）安装都按最新 PRAGMA table_info 重建。
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
        sql = (f"CREATE TRIGGER {trigger_name} "
               f"AFTER {op.upper()} ON {table} {when} BEGIN {body} END;")
        conn.execute(sql)


def install_all_triggers(store):
    """为所有已知复制表安装触发器（表存在才装）。设模块级 TRIGGERS_INSTALLED。"""
    global TRIGGERS_INSTALLED
    existing = {r["name"] for r in
                store.conn.execute("SELECT name FROM sqlite_master "
                                   "WHERE type='table'").fetchall()}
    for table, pk in _REPLICATED_TABLES.items():
        if table in existing:
            install_triggers(store.conn, table, pk=pk)
    TRIGGERS_INSTALLED = True


# ── WAL 解耦：暂存表 best-effort 异步刷盘（M2/A5） ───────────────────────────
class WalFlusher:
    """把 `wal_staging` 暂存行 best-effort 落盘到 `replication_log` + `lsn_seq`。

    业务写只在主事务写轻量 `wal_staging`（几乎不失败），WAL 持久化由此对象在
    **独立连接**（文件库）或主连接（:memory:）上完成。任一失败仅 `logging.warning`，
    绝不回滚业务写 → 满足「WAL 写失败仅告警不阻塞主事务」。WAL 变最终一致，
    缺口由快照/PITR 兜底（明确取舍）。

    - 文件库：daemon 线程按 POLL 周期刷盘，使用独立连接（不阻塞业务连接）。
    - :memory:：不启后台线程（独立 :memory: 连接是空库），靠显式 `store.flush_wal()` 驱动。
    """

    BATCH = 200
    POLL = 0.2

    def __init__(self, store):
        self.store = store
        self._lock = threading.Lock()
        self._stop = False
        self._thread = None
        self._conn = None
        if store.path != ":memory:":
            try:
                self._conn = sqlite3.connect(
                    store.path, check_same_thread=False, isolation_level=None)
                self._conn.row_factory = sqlite3.Row
            except Exception as e:  # pragma: no cover - 依赖/路径问题
                logging.warning("[wal] 无法建立独立刷盘连接，WAL 暂不落盘: %s", e)
                self._conn = None

    def _conn_for(self):
        # :memory: 复用主连接；文件库用独立连接（避免阻塞业务事务）
        return self._conn if self._conn is not None else self.store.conn

    def start(self):
        if self._thread is not None or self.store.path == ":memory:":
            return
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _run(self):
        while not self._stop:
            try:
                self.flush()
            except Exception as e:  # pragma: no cover - 防御性
                logging.warning("[wal] 刷盘循环异常: %s", e)
            # 分段休眠，便于快速响应 stop
            for _ in range(int(self.POLL / 0.05)):
                if self._stop:
                    break
                time.sleep(0.05)

    def flush(self):
        """将一批 wal_staging 落 replication_log（独立事务，失败仅告警）。"""
        with self._lock:
            from .db import next_lsn
            conn = self._conn_for()
            try:
                rows = conn.execute(
                    "SELECT id, op, table_name, row_id, payload, at "
                    "FROM wal_staging ORDER BY id LIMIT ?", (self.BATCH,)).fetchall()
            except Exception:
                return
            if not rows:
                return
            try:
                conn.execute("BEGIN")
                for r in rows:
                    lsn = next_lsn(conn)
                    conn.execute(
                        "INSERT INTO replication_log(lsn, op, table_name, row_id, payload, at) "
                        "VALUES(?,?,?,?,?,?)",
                        (lsn, r["op"], r["table_name"], r["row_id"],
                         r["payload"], r["at"]))
                ids = [r["id"] for r in rows]
                conn.execute(
                    "DELETE FROM wal_staging WHERE id IN (%s)"
                    % ",".join("?" * len(ids)), ids)
                conn.execute("COMMIT")
            except Exception as e:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                logging.warning("[wal] 刷盘失败（仅告警，不阻塞业务写）: %s", e)


# ── 回放（分发表 + 幂等 + 未知表隔离） ───────────────────────────────────────

_REPLAYERS = None
_REPLAYERS_LOCK = threading.Lock()


def _build_dispatch():
    from .clinical.patients import apply_change as pa
    from .clinical.records import apply_change as ra
    from .clinical.consultations import apply_change as ca
    from .ops.store import apply_schedule, apply_appointment, apply_visit
    return {
        "documents": lambda s, op, rid, p: s.apply_document(p),
        "patients": pa, "records": ra, "consultations": ca,
        "schedules": apply_schedule, "appointments": apply_appointment,
        "visits": apply_visit,
    }


def _ensure_replayers():
    global _REPLAYERS
    if _REPLAYERS is None:
        with _REPLAYERS_LOCK:
            if _REPLAYERS is None:
                _REPLAYERS = _build_dispatch()
    return _REPLAYERS


def register_replayer(table: str, fn):
    """注册某表的回放函数（签名 (store, op, row_id, payload)）。

    分发表首次使用时在 Lock 内惰性构建（避免循环 import）；运行时注册
    直接并入 _REPLAYERS，供回放 dispatch 使用。
    """
    global _REPLAYERS
    with _REPLAYERS_LOCK:
        if _REPLAYERS is None:
            _REPLAYERS = _build_dispatch()
        _REPLAYERS[table] = fn


def replay_from(store, changes: list, target_lsn: int | None = None) -> int:
    """把 WAL 变更回放到 store（统一回放入口，替代旧 apply_changes）。

    - 回放前 `PRAGMA recursive_triggers=OFF`，备机回放不二次触发本机 WAL。
    - 按 lsn 升序；`lsn<=applied_max` 跳过 → 幂等。
    - **PITR 截断**：`target_lsn` 给定时，仅回放 `lsn<=target_lsn` 的变更；
      回放后 `set_applied_max(min(target_lsn, 实际最大已回放lsn))`，使 PITR
      恢复到指定语句级位置（设计 §5/§7）。`target_lsn is None` 则回放全量
      并 `set_applied_max(max_lsn)`（原行为）。
    - 未知表 → 捕获 UnknownTableError / 无 replayer → 告警并继续（隔离不崩整体），
      仍推进 applied_max 标记。
    - 回放直写主表（UPSERT），绕过 record_change，不污染 WAL。
    - 整段在单一事务内一次性提交；中途任意异常整体 rollback
      （半回放 + 未提交的 applied_max + 回放锁一并撤销），由调用方处理异常。
      这保证 P1 复用的长连接 standby 循环不会把半回放落库污染副本，
      也不会因锁残留导致后续正常写入被 WHEN 守卫静默漏记。
    返回本次实际回放（写入主表）条数。
    """
    replays = _ensure_replayers()
    conn = store.conn
    conn.execute("PRAGMA recursive_triggers=OFF")
    ordered = sorted(
        changes,
        key=lambda c: (c.get("lsn") if c.get("lsn") is not None
                       else (c.get("id") or 0)))
    applied_max = store.applied_max()
    max_lsn = applied_max
    applied = 0
    try:
        # autocommit 模式下需显式 BEGIN，使回放锁、各 replayer 直写、applied_max、
        # 解锁在同一事务内一次性提交；中途异常由下方 rollback 整体撤销。
        conn.execute("BEGIN")
        # 防重入：设置回放锁，使本机复制触发器（WHEN 守卫）整体跳过。
        conn.execute("INSERT OR REPLACE INTO ha_state(key, value) "
                     "VALUES('__replay_lock', '1')")

        for ch in ordered:
            lsn = ch.get("lsn")
            if lsn is None:
                lsn = ch.get("id") or 0
            if lsn <= applied_max:
                continue                                    # 幂等跳过
            # PITR 截断：仅回放 lsn<=target_lsn（target 给定时）
            if target_lsn is not None and lsn > target_lsn:
                continue
            op = ch.get("op")
            table = ch.get("table_name") or ch.get("table")
            row_id = ch.get("row_id")
            payload = ch.get("payload")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = {}
            fn = replays.get(table)
            if fn is None:
                # 未知表：隔离 + 告警，不阻塞整体回放
                logging.warning("[replication] 未知表 '%s' 的变更被隔离跳过 (lsn=%s)",
                                table, lsn)
                max_lsn = max(max_lsn, lsn)
                continue
            try:
                fn(store, op, row_id, payload)
            except UnknownTableError:
                logging.warning(
                    "[replication] 回放表 '%s' 抛 UnknownTableError，隔离 (lsn=%s)",
                    table, lsn)
            max_lsn = max(max_lsn, lsn)
            applied += 1
        if target_lsn is None:
            store.set_applied_max(max_lsn)
        else:
            # PITR：applied_max 取 target 与实际最大已回放 lsn 的较小者
            store.set_applied_max(min(target_lsn, max_lsn))
        # 解除回放锁，与回放、applied_max 同事务一次性提交（设计 §6.3）。
        conn.execute("DELETE FROM ha_state WHERE key='__replay_lock'")
        conn.commit()
    except Exception:
        # 回放中途任意异常（replayer 抛非 UnknownTableError 等）：
        # 整体 rollback 撤销半回放 + 未提交的 applied_max + 回放锁，
        # 避免半回放被后续 commit 落库污染副本，或锁残留导致漏记。
        conn.rollback()
        raise
    return applied


def apply_changes(store, changes: list) -> int:
    """兼容别名：指向 replay_from。"""
    return replay_from(store, changes)


# ── 恢复校验（dr verify） ────────────────────────────────────────────────────

def verify_store(store) -> dict:
    """对 store 做恢复前校验：integrity_check + 行数 + max(lsn) + FTS 抽样。

    返回人类可读报告 dict（ok / errors / row_counts / max_lsn / fts_sample）。
    """
    conn = store.conn
    report: dict[str, Any] = {
        "integrity": None, "row_counts": {}, "max_lsn": 0,
        "fts_sample": None, "ok": True, "errors": [],
    }
    try:
        report["integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
    except Exception as e:
        report["integrity"] = f"error:{e}"
    if report["integrity"] != "ok":
        report["ok"] = False
        report["errors"].append(f"integrity_check={report['integrity']}")

    tables = ["documents", "document_versions", "attachments", "patients",
              "records", "consultations", "schedules", "appointments",
              "visits", "embeddings", "files", "ebook_meta", "sync_states"]
    for t in tables:
        try:
            report["row_counts"][t] = conn.execute(
                f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception:
            report["row_counts"][t] = -1

    try:
        report["max_lsn"] = conn.execute(
            "SELECT COALESCE(MAX(lsn), 0) FROM replication_log").fetchone()[0]
    except Exception:
        report["max_lsn"] = 0

    # FTS 抽样：取一篇文档标题前缀做 MATCH，验证 docs_fts 可用
    sample = conn.execute(
        "SELECT title FROM documents WHERE title IS NOT NULL LIMIT 1").fetchone()
    if not sample or not (sample["title"] or "").strip():
        report["fts_sample"] = "skipped(empty)"
    else:
        term = (sample["title"] or "").strip()[:3]
        try:
            rows = conn.execute(
                "SELECT doc_id FROM docs_fts WHERE docs_fts MATCH ? LIMIT 5",
                (term,)).fetchall()
            report["fts_sample"] = {"term": term, "hits": len(rows)}
        except Exception as e:
            report["fts_sample"] = {"term": term, "error": str(e)}
            report["ok"] = False
            report["errors"].append(f"fts:{e}")
    return report


# ── 回放辅助 ────────────────────────────────────────────────────────────────

def _to_wal_dict(item) -> dict:
    """把 Change 或 dict 规范化为 WAL 记录 dict（保留 id 与 lsn 以便
    备机按 lsn 排序/幂等回放、以及 PITR 按 lsn 截断）。"""
    if isinstance(item, Change):
        return {"id": None, "lsn": getattr(item, "lsn", None), "op": item.op,
                "table": item.table, "row_id": item.row_id,
                "payload": item.payload, "at": item.at}
    d = dict(item)
    d.setdefault("id", None)
    d.setdefault("lsn", None)
    return d


# ── 远程副本目标：传输层 + SSH / S3 ──────────────────────────────────────────

class Transport:
    """传输抽象：run/send/recv。默认 SshTransport（subprocess，list 传参禁 shell）。"""

    def run(self, cmd_list, input=None, **kw) -> "subprocess.CompletedProcess":
        raise NotImplementedError

    def send(self, local: str, remote: str):
        raise NotImplementedError

    def recv(self, remote: str, local: str):
        raise NotImplementedError


class SshTransport(Transport):
    def __init__(self, userhost: str, ssh_bin: str = "ssh", scp_bin: str = "scp"):
        self.uh = userhost
        self.ssh = ssh_bin
        self.scp = scp_bin

    def run(self, cmd_list, input=None, **kw):
        return subprocess.run([self.ssh, self.uh, *cmd_list],
                              input=input, capture_output=True, text=True, **kw)

    def send(self, local: str, remote: str):
        subprocess.run([self.scp, local, f"{self.uh}:{remote}"], check=True)

    def recv(self, remote: str, local: str):
        subprocess.run([self.scp, f"{self.uh}:{remote}", local], check=True)


def _parse_ssh_target(target: str):
    """ssh://user@host/path -> (userhost, remote_dir)。"""
    s = target[len("ssh://"):]
    # 找第一个 '/' 作为 host 与路径分界
    idx = s.find("/")
    if idx < 0:
        raise ValueError(f"ssh target 需含路径: {target}")
    userhost = s[:idx]
    remote_dir = s[idx:] or "/"
    return userhost, remote_dir


class SshReplica(ReplicaTarget):
    """经 SSH/SCP 推送多版本快照+全量 WAL 到远端目录（零依赖，subprocess）。

    远端布局：
      {remote_dir}/snapshots/<ts>/db.snapshot + snapshot.json   （多版本，保留 keep 份）
      {remote_dir}/wal.ndjson                                    （全量 WAL 增量，append）

    凭证沿用 `SSH_AUTH_SOCK`/key；`SshTransport` 用 list 传参（禁 shell=True）。
    安全落地（评审 LOW §8）：远端文件经 `scp .part` + 同连接 `ssh mv` 原子替换，
    读者不会拉到半成品；终态文件 `chmod 600`（私有医疗数据收窄权限）。WAL 全量
    保留未做归档窗口（I5：保留全量历史即满足 PITR）。远端保留 keep 份由
    `run(["ls"])` 列目录后删最旧实现。若需更强防勒索（版本不可改写+校验）可在
    P1 换 SFTP 协议。注：`flock` 仅适用于本地追加，远端 WAL 追加的并发竞争由
    PITR/快照兜底，不在此处加锁。
    """

    def __init__(self, target: str, transport: Transport | None = None, keep: int = 5):
        self.userhost, self.remote_dir = _parse_ssh_target(target)
        self.transport = transport or SshTransport(self.userhost)
        self.keep = keep
        self._snap_seq = 0
        self.stage = tempfile.mkdtemp(prefix="khub-ssh-")

    @property
    def name(self) -> str:
        return f"ssh:{self.userhost}{self.remote_dir}"

    def push_snapshot(self, meta: dict, db_path: str = ""):
        meta = dict(meta)
        if "at" not in meta:
            meta["at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        # ts = 本地时间 + 零填充自增序号，保证目录全局唯一且可按字典序排序。
        # （不用裸时间戳作目录名：多版本 + 远端清理后，同名裸 ts 可能被后续推送
        # 复用，破坏"最新快照"判定。见 tests/test_ssh_replica_prune_keeps_recent。）
        self._snap_seq += 1
        ts = f"{time.strftime('%Y%m%dT%H:%M%S')}-{self._snap_seq:08d}"
        snap_dir = f"{self.remote_dir}/snapshots/{ts}"
        # 防同秒/同毫秒碰撞：该 ts 已存在则追加自增序号，保证目录唯一
        if self.transport.run(["ls", snap_dir]).returncode == 0:
            self._snap_seq += 1
            ts = f"{ts}-{self._snap_seq}"
            snap_dir = f"{self.remote_dir}/snapshots/{ts}"
        self.transport.run(["mkdir", "-p", snap_dir])
        json_path = os.path.join(self.stage, "snapshot.json")
        with open(json_path, "w") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        self._atomic_send(json_path, f"{snap_dir}/snapshot.json", mode="600")
        if db_path and os.path.isfile(db_path):
            self._atomic_send(db_path, f"{snap_dir}/db.snapshot", mode="600")
        self._prune_remote(self.keep)
        return meta

    def _atomic_send(self, local, remote, mode=None):
        """原子替换远端文件：先 scp 到 `<remote>.part`，再同一条 ssh 连接内
        `mv` 改名（POSIX rename 原子），读者拉取时不会看到半成品文件。

        设计 §8 安全落地（评审 LOW）：scp 无法跨连接 rename，故用 ssh `mv`
        完成原子替换，避免远端快照/库被读取到半写入状态（防勒索/防损坏）。
        mode 非空时对最终文件 `chmod`（如 "600"，私有医疗数据远端收窄权限）。
        """
        part = remote + ".part"
        self.transport.send(local, part)
        self.transport.run(["mv", part, remote])
        if mode is not None:
            self.transport.run(["chmod", str(mode), remote])

    def _prune_remote(self, keep: int):
        """远端保留最近 keep 份快照：ls 列目录 → 删最旧。"""
        r = self.transport.run(["ls", f"{self.remote_dir}/snapshots"])
        if r.returncode != 0:
            return
        dirs = [x for x in r.stdout.split() if x not in (".", "..")]
        dirs.sort()
        for old in (dirs[:-keep] if keep > 0 else dirs):
            self.transport.run(["rm", "-rf", f"{self.remote_dir}/snapshots/{old}"])

    def list_remote_versions(self) -> list:
        """返回按时间升序的远端快照列表 `[{ts, manifest, lsn, at, snap_dir}]`。"""
        r = self.transport.run(["ls", f"{self.remote_dir}/snapshots"])
        if r.returncode != 0:
            return []
        ts_list = [x for x in r.stdout.split() if x not in (".", "..")]
        ts_list.sort()
        out = []
        for ts in ts_list:
            snap_dir = f"{self.remote_dir}/snapshots/{ts}"
            rc = self.transport.run(["cat", f"{snap_dir}/snapshot.json"])
            if rc.returncode != 0:
                continue
            try:
                manifest = json.loads(rc.stdout)
            except json.JSONDecodeError:
                continue
            out.append({
                "ts": ts,
                "manifest": manifest,
                "lsn": manifest.get("max_replication_id", 0),
                "at": manifest.get("at", ""),
                "snap_dir": snap_dir,
            })
        return out

    def fetch_remote_snapshot_db(self, ts: str) -> str:
        """scp 远端 {snapshots/<ts>/db.snapshot} 到本地临时文件并返回路径。"""
        remote = f"{self.remote_dir}/snapshots/{ts}/db.snapshot"
        lp = os.path.join(self.stage, f"db-{ts}.snapshot")
        self.transport.recv(remote, lp)
        return lp

    def push_changes(self, changes: list):
        # 保留全量 WAL 历史（I5）：先拉取远端已有 WAL（若存在），再 append 本次变更。
        lp = os.path.join(self.stage, "wal.ndjson")
        try:
            self.transport.recv(f"{self.remote_dir}/wal.ndjson", lp)
        except Exception:
            pass
        with open(lp, "a") as f:
            for ch in changes:
                f.write(json.dumps(_to_wal_dict(ch), ensure_ascii=False) + "\n")
        self._atomic_send(lp, f"{self.remote_dir}/wal.ndjson", mode="600")

    def fetch_snapshot(self) -> dict | None:
        versions = self.list_remote_versions()
        return versions[-1]["manifest"] if versions else None

    def fetch_changes(self) -> list:
        lp = os.path.join(self.stage, "wal.ndjson")
        try:
            self.transport.recv(f"{self.remote_dir}/wal.ndjson", lp)
        except Exception:
            return []
        out = []
        if os.path.isfile(lp):
            with open(lp) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        out.append(json.loads(line))
        return out

    def health(self) -> tuple[bool, str]:
        r = self.transport.run(["true"])
        return (r.returncode == 0, "ok" if r.returncode == 0 else (r.stderr or "ssh failed"))


class S3Replica(ReplicaTarget):
    """S3 兼容对象存储副本（惰性 import boto3，未安装则运行时报错）。"""

    def __init__(self, target: str, endpoint_url: str | None = None, region: str | None = None):
        # s3://bucket/prefix
        s = target[len("s3://"):]
        idx = s.find("/")
        self.bucket = s[:idx]
        self.prefix = s[idx + 1:].strip("/")
        self.endpoint_url = endpoint_url
        self.region = region
        self._client_cache = None

    def _client(self):
        if self._client_cache is None:
            try:
                import boto3  # 惰性导入
            except ImportError:
                raise RuntimeError("未安装 boto3，无法使用 S3 副本（pip install boto3）")
            self._client_cache = boto3.client(
                "s3", endpoint_url=self.endpoint_url, region_name=self.region)
        return self._client_cache

    @property
    def name(self) -> str:
        return f"s3://{self.bucket}/{self.prefix}"

    def _key(self, name: str):
        return f"{self.prefix}/{name}" if self.prefix else name

    def push_snapshot(self, meta: dict, db_path: str = ""):
        c = self._client()
        c.put_object(Bucket=self.bucket, Key=self._key("snapshot.json"),
                     Body=json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        if db_path:
            with open(db_path, "rb") as f:
                c.put_object(Bucket=self.bucket, Key=self._key("db.snapshot"), Body=f.read())

    def push_changes(self, changes: list):
        c = self._client()
        # 读改写：append 到现有 wal.ndjson
        existing = ""
        try:
            obj = c.get_object(Bucket=self.bucket, Key=self._key("wal.ndjson"))
            existing = obj["Body"].read().decode("utf-8")
        except Exception:
            existing = ""
        lines = existing.splitlines()
        for ch in changes:
            lines.append(json.dumps(_to_wal_dict(ch), ensure_ascii=False))
        c.put_object(Bucket=self.bucket, Key=self._key("wal.ndjson"),
                     Body=("\n".join(lines) + "\n").encode("utf-8"))

    def fetch_snapshot(self) -> dict | None:
        import io
        c = self._client()
        try:
            obj = c.get_object(Bucket=self.bucket, Key=self._key("snapshot.json"))
            return json.loads(obj["Body"].read().decode("utf-8"))
        except Exception:
            return None

    def fetch_changes(self) -> list:
        c = self._client()
        try:
            obj = c.get_object(Bucket=self.bucket, Key=self._key("wal.ndjson"))
            text = obj["Body"].read().decode("utf-8")
        except Exception:
            return []
        return [json.loads(l) for l in text.splitlines() if l.strip()]

    def health(self) -> tuple[bool, str]:
        try:
            self._client().head_bucket(Bucket=self.bucket)
            return (True, "ok")
        except Exception as e:
            return (False, str(e))


def make_replica(target: str) -> ReplicaTarget:
    """由 file:// / ssh:// / s3:// 目标串构造 ReplicaTarget（零 duplicataion 工厂）。"""
    if target.startswith("file://"):
        return LocalFileReplica(os.path.expanduser(target[len("file://"):]))
    if target.startswith("ssh://"):
        return SshReplica(target)
    if target.startswith("s3://"):
        return S3Replica(target)
    raise ValueError(f"无法识别的 target 前缀：{target}（须以 file:/// ssh:// 或 s3:// 开头）")


class ReplicationManager:
    """编排推送/拉取/回放。"""

    def __init__(self, store):
        self.store = store

    def push_snapshot(self, replica: ReplicaTarget, db_path: str = ""):
        if not db_path:
            db_path = self.store.path
        meta = export_snapshot(self.store)
        if db_path and os.path.isfile(db_path) and db_path != ":memory:":
            # 一致性快照：ATTACH 逐表拷贝、排除 ha_state / 虚表（见 db.make_snapshot_db）
            from .db import make_snapshot_db
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db").name
            make_snapshot_db(self.store.conn, tmp)
            replica.push_snapshot(meta, db_path=tmp)
            try:
                os.remove(tmp)
            except OSError:
                pass
        else:
            replica.push_snapshot(meta)
        return meta

    def push_pending(self, replica: ReplicaTarget, mark: bool = True) -> int:
        rows = WALLog(self.store).pending()
        items = [{"id": r["id"], "lsn": r["lsn"], "op": r["op"],
                 "table_name": r["table_name"], "row_id": r["row_id"],
                 "payload": r["payload"], "at": r["at"]}
                for r in rows]
        if items:
            replica.push_changes(items)
        if mark and items:
            WALLog(self.store).mark_applied([r["id"] for r in rows])
        # I5 — 归档窗口：推送成功（已 applied）即清理旧 WAL，防磁盘膨胀。
        # 须在 push 之后调用：推送前删会丢失 PITR/副本需要的 WAL。
        self.store.prune_wal()
        return len(items)

    def pull_and_replay(self, replica: ReplicaTarget, db_path: str = "") -> dict:
        changes = replica.fetch_changes() or []
        applied = apply_changes(self.store, changes)
        return {"applied": applied, "total": len(changes)}
