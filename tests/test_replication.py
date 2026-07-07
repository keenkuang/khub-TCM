"""Tests for khub.replication — WALLog, export/import snapshot, LocalFileReplica."""

import json
import os
import tempfile
from dataclasses import asdict

from khub.db import Store
from khub.replication import (
    Change,
    WALLog,
    export_snapshot,
    import_snapshot_manifest,
    LocalFileReplica,
    record_change,
)


# ── WALLog ──────────────────────────────────────────────────────────────────


def test_wal_log_record_pending_mark_applied():
    store = Store(":memory:")
    log = WALLog(store)
    log.record("insert", "documents", "d1", '{"title": "one"}')
    log.record("update", "documents", "d2", '{"title": "two"}')
    log.record("delete", "documents", "d3", '{"title": "three"}')

    pending = log.pending()
    assert len(pending) == 3
    for p in pending:
        assert p["applied"] == 0

    log.mark_applied([1, 2])
    remaining = log.pending()
    assert len(remaining) == 1
    assert remaining[0]["id"] == 3
    assert remaining[0]["op"] == "delete"


def test_wal_log_mark_applied_empty():
    """mark_applied with empty list is a no-op."""
    store = Store(":memory:")
    log = WALLog(store)
    log.mark_applied([])  # must not crash


def test_record_change_convenience():
    """record_change creates a WALLog entry via the convenience function."""
    store = Store(":memory:")
    record_change(store, "insert", "documents", "c1", '{"x": 1}')
    rows = store.conn.execute(
        "SELECT * FROM replication_log WHERE applied=0").fetchall()
    assert len(rows) == 1
    assert rows[0]["row_id"] == "c1"


# ── export_snapshot ─────────────────────────────────────────────────────────


def test_export_snapshot_empty_store():
    store = Store(":memory:")
    m = export_snapshot(store)
    assert "at" in m
    assert "tables" in m
    assert "max_replication_id" in m
    assert m["max_replication_id"] == 0
    assert m["total_rows"] == 0
    for t in ["documents", "document_versions"]:
        assert m["tables"].get(t) == 0


def test_export_snapshot_with_data():
    from khub.models import CanonicalDoc

    store = Store(":memory:")
    doc = CanonicalDoc(
        canonical_id="d1", title="T", content="hello",
        source="test", source_id="t/1",
    )
    store.store_document(doc)

    log = WALLog(store)
    log.record("insert", "documents", "d1", '{"title": "T"}')

    m = export_snapshot(store)
    assert m["tables"]["documents"] >= 1
    assert m["tables"]["document_versions"] >= 1
    assert m["total_rows"] >= 2
    assert m["max_replication_id"] >= 1


# ── import_snapshot_manifest ────────────────────────────────────────────────


def test_import_snapshot_manifest_valid():
    store = Store(":memory:")
    manifest = {
        "at": "2026-01-01T00:00:00",
        "tables": {"documents": 5, "document_versions": 10},
        "max_replication_id": 3,
        "total_rows": 15,
    }
    result = import_snapshot_manifest(store, manifest)
    assert result["status"] == "ok"

    row = store.conn.execute(
        "SELECT value FROM snapshot_meta WHERE key='last_manifest'"
    ).fetchone()
    loaded = json.loads(row["value"])
    assert loaded["max_replication_id"] == 3


def test_import_snapshot_manifest_missing_keys():
    store = Store(":memory:")
    try:
        import_snapshot_manifest(store, {"at": "x"})
        assert False, "expected ValueError"
    except ValueError as e:
        assert "missing keys" in str(e)


# ── LocalFileReplica ────────────────────────────────────────────────────────


def test_local_replica_push_snapshot():
    tmp = tempfile.mkdtemp()
    try:
        replica = LocalFileReplica(tmp)
        meta = {"at": "now", "tables": {"d": 1}, "max_replication_id": 0, "total_rows": 1}
        replica.push_snapshot(meta)

        snap_path = os.path.join(tmp, "snapshot.json")
        assert os.path.isfile(snap_path)
        with open(snap_path) as f:
            loaded = json.load(f)
        assert loaded == meta
    finally:
        _rmtree(tmp)


def test_local_replica_push_snapshot_with_db():
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "source.db")
    store = Store(db_path)
    store.conn.execute("CREATE TABLE t(x)")
    store.conn.execute("INSERT INTO t VALUES(42)")
    store.conn.commit()

    target_dir = tempfile.mkdtemp()
    try:
        replica = LocalFileReplica(target_dir)
        replica.push_snapshot(
            {"at": "now", "tables": {}, "max_replication_id": 0, "total_rows": 0},
            db_path=db_path,
        )

        snap_path = os.path.join(target_dir, "db.snapshot")
        assert os.path.isfile(snap_path)

        # Verify the copy is usable
        import sqlite3
        c2 = sqlite3.connect(snap_path)
        val = c2.execute("SELECT x FROM t").fetchone()[0]
        assert val == 42
        c2.close()
    finally:
        _rmtree(tmp)
        _rmtree(target_dir)


def test_local_replica_push_changes():
    tmp = tempfile.mkdtemp()
    try:
        replica = LocalFileReplica(tmp)
        changes = [
            Change("insert", "documents", "d1", '{"a":1}', "2026-01-01T00:00:00"),
            Change("update", "documents", "d2", '{"a":2}', "2026-01-01T00:00:01"),
        ]
        replica.push_changes(changes)

        wal_path = os.path.join(tmp, "wal.ndjson")
        assert os.path.isfile(wal_path)
        with open(wal_path) as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert len(lines) == 2
        assert lines[0]["op"] == "insert"
        assert lines[0]["row_id"] == "d1"
        assert lines[1]["row_id"] == "d2"

        # Append more changes
        more = [Change("delete", "documents", "d3", '{}', "2026-01-01T00:00:02")]
        replica.push_changes(more)
        with open(wal_path) as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert len(lines) == 3
    finally:
        _rmtree(tmp)


def test_local_replica_health():
    tmp = tempfile.mkdtemp()
    try:
        replica = LocalFileReplica(tmp)
        alive, msg = replica.health()
        assert alive is True
        assert msg == "writable"
    finally:
        _rmtree(tmp)


def test_local_replica_health_not_writable():
    tmp = tempfile.mkdtemp()
    # Remove write permission
    os.chmod(tmp, 0o444)
    try:
        replica = LocalFileReplica(tmp)
        alive, msg = replica.health()
        assert alive is False
        assert msg == "not writable"
    finally:
        os.chmod(tmp, 0o755)
        _rmtree(tmp)


def test_change_dataclass_fields():
    c = Change("insert", "t", "r", '{}', "2026-01-01")
    d = asdict(c)
    assert d["op"] == "insert"
    assert d["table"] == "t"
    assert d["row_id"] == "r"
    assert d["payload"] == "{}"
    assert d["at"] == "2026-01-01"


# ── helpers ─────────────────────────────────────────────────────────────────


def _rmtree(path: str):
    """Remove a tree without depending on shutil."""
    for root, dirs, files in os.walk(path, topdown=False):
        for name in files:
            os.remove(os.path.join(root, name))
        for name in dirs:
            os.rmdir(os.path.join(root, name))
    os.rmdir(path)
