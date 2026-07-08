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
    replay_from,
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
        # push_snapshot 会用服务器时间覆盖 at（供 dr status 显示），其余字段一致即可
        assert loaded["tables"] == meta["tables"]
        assert loaded["max_replication_id"] == meta["max_replication_id"]
        assert loaded["total_rows"] == meta["total_rows"]
        assert "at" in loaded
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

        # P0a: 快照存到 <dir>/snapshots/<timestamp>.db
        import glob
        snaps = glob.glob(os.path.join(target_dir, "snapshots", "*.db"))
        assert len(snaps) == 1
        snap_path = snaps[0]

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
    import pytest
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root 绕过 chmod 权限检查，本测试无意义")
    tmp = tempfile.mkdtemp()
    # 先构造（tmp 可写），再移除写权限
    replica = LocalFileReplica(tmp)
    os.chmod(tmp, 0o444)
    try:
        alive, msg = replica.health()
        assert alive is False
        assert msg == "not writable"
    finally:
        # 恢复写权限并递归开放子目录，确保 _rmtree 清理不被权限阻塞
        os.chmod(tmp, 0o755)
        for root, dirs, _ in os.walk(tmp, topdown=False):
            for name in dirs:
                try:
                    os.chmod(os.path.join(root, name), 0o755)
                except OSError:
                    pass
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


# ── P0a：触发器记账 / 回放隔离（§13 单测要点 1/2/3/4）─────────────────────────


def test_business_write_lands_in_wal_with_lsn():
    """① 业务写入同事务落入 replication_log 且含正确 lsn。"""
    from khub.models import CanonicalDoc

    d = tempfile.mkdtemp()
    try:
        store = Store(os.path.join(d, "live.db"))  # init_schema 装 documents 触发器
        doc = CanonicalDoc(canonical_id="d1", title="T", content="hello",
                           source="s", source_id="s/1")
        store.store_document(doc)

        rows = store.conn.execute(
            "SELECT lsn, op, table_name, row_id FROM replication_log "
            "WHERE table_name='documents' ORDER BY lsn"
        ).fetchall()
        assert len(rows) >= 1
        for r in rows:
            assert r["lsn"] is not None and r["lsn"] >= 1
            assert r["row_id"] == "d1"
    finally:
        _rmtree(d)


def test_standby_replay_no_reentry():
    """② 备机（装有本机触发器）回放不二次触发本机 replication_log。"""
    from khub.models import CanonicalDoc

    d = tempfile.mkdtemp()
    try:
        src = Store(os.path.join(d, "src.db"))
        doc = CanonicalDoc(canonical_id="d1", title="T", content="hello",
                           source="s", source_id="s/1")
        src.store_document(doc)
        changes = [dict(r) for r in src.conn.execute(
            "SELECT lsn, op, table_name, row_id, payload FROM replication_log")]

        # 备机：普通 Store（init_schema 已装 documents 触发器），模拟「有触发器」的备机
        dst = Store(os.path.join(d, "dst.db"))
        before = dst.conn.execute(
            "SELECT COUNT(*) FROM replication_log").fetchone()[0]
        replay_from(dst, changes)
        after = dst.conn.execute(
            "SELECT COUNT(*) FROM replication_log").fetchone()[0]

        assert after == before, "备机回放不应二次写本机 replication_log"
        assert dst.get_document("d1") is not None
    finally:
        _rmtree(d)


def test_replay_idempotent():
    """③ 同一批变更回放两次，行数与 max(lsn) 不变（幂等）。"""
    from khub.models import CanonicalDoc
    from khub.clinical.patients import add_patient, init as patients_init

    d = tempfile.mkdtemp()
    try:
        src = Store(os.path.join(d, "src.db"))
        doc = CanonicalDoc(canonical_id="d1", title="T", content="hello",
                           source="s", source_id="s/1")
        src.store_document(doc)
        add_patient(src, "p1", "张三")  # 触发 patients 写入 + WAL
        changes = [dict(r) for r in src.conn.execute(
            "SELECT lsn, op, table_name, row_id, payload FROM replication_log")]

        dst = Store(os.path.join(d, "dst.db"))
        patients_init(dst)  # 备机需先有 patients 表结构（实战由 init 保证）
        replay_from(dst, changes)
        n1 = dst.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        l1 = dst.conn.execute("SELECT COALESCE(MAX(lsn),0) FROM replication_log").fetchone()[0]
        replay_from(dst, changes)
        n2 = dst.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        l2 = dst.conn.execute("SELECT COALESCE(MAX(lsn),0) FROM replication_log").fetchone()[0]

        assert n1 == n2
        assert l1 == l2
        assert dst.get_document("d1") is not None
    finally:
        _rmtree(d)


def test_unknown_table_isolated():
    """④ 喂入未知表的变更，整体回放不崩溃（被隔离告警并推进标记）。"""
    d = tempfile.mkdtemp()
    try:
        store = Store(os.path.join(d, "s.db"))
        bad = [{"lsn": 1, "op": "insert", "table_name": "__x",
                "row_id": "1", "payload": "{}"}]
        replay_from(store, bad)  # 不应抛出异常
        assert store.applied_max() == 1  # 标记仍推进
    finally:
        _rmtree(d)
