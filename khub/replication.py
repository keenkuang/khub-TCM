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
import os
import shutil
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
        self.conn.execute("""CREATE TABLE IF NOT EXISTS replication_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op TEXT, table_name TEXT, row_id TEXT,
            payload TEXT, at TEXT, applied INTEGER DEFAULT 0)""")
        self.conn.commit()

    def record(self, op: str, table: str, row_id: str, payload: str):
        """Insert a new change entry (applied=0)."""
        at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        self.conn.execute(
            "INSERT INTO replication_log(op,table_name,row_id,payload,at) VALUES(?,?,?,?,?)",
            (op, table, str(row_id), payload, at))
        self.conn.commit()

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
        "documents", "document_versions", "patients", "records",
        "consultations", "audit_log", "replication_log",
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
            "SELECT COALESCE(MAX(id), 0) AS m FROM replication_log"
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

    def push_changes(self, changes: list[Change]):
        """Push a batch of WAL changes to the target."""
        raise NotImplementedError

    def health(self) -> tuple[bool, str]:
        """Return (is_alive: bool, status_message: str)."""
        raise NotImplementedError


class LocalFileReplica(ReplicaTarget):
    """Filesystem-based replica — writes snapshot & WAL to a local directory.

    Useful for testing and as a reference for remote implementations.
    """

    def __init__(self, dir_path: str):
        self.dir = dir_path
        os.makedirs(dir_path, exist_ok=True)

    @property
    def name(self) -> str:
        return f"local:{self.dir}"

    def push_snapshot(self, meta: dict, db_path: str = ""):
        """Write snapshot manifest to {dir}/snapshot.json and optionally
        copy the database file to {dir}/db.snapshot."""
        with open(os.path.join(self.dir, "snapshot.json"), "w") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        if db_path:
            dest = os.path.join(self.dir, "db.snapshot")
            shutil.copy2(db_path, dest)

    def push_changes(self, changes: list[Change]):
        """Append WAL changes as NDJSON lines to {dir}/wal.ndjson."""
        path = os.path.join(self.dir, "wal.ndjson")
        with open(path, "a") as f:
            for ch in changes:
                line = json.dumps(dataclasses.asdict(ch), ensure_ascii=False)
                f.write(line + "\n")

    def health(self) -> tuple[bool, str]:
        ok = os.access(self.dir, os.W_OK)
        return (ok, "writable" if ok else "not writable")


def record_change(store, op: str, table: str, row_id: str, payload_json: str):
    """Convenience: create a WALLog and record one change.

    This is the intended entry point for core functions (store_document,
    update_patient, etc.) to hook into the replication change log.
    """
    WALLog(store).record(op, table, row_id, payload_json)
