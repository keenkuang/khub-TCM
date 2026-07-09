"""Tests for khub.replication — WALLog, export/import snapshot, LocalFileReplica."""

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict

from khub.db import Store, rebuild_fts, make_snapshot_db
from khub.replication import (
    Change,
    WALLog,
    export_snapshot,
    import_snapshot_manifest,
    LocalFileReplica,
    SshReplica,
    ReplicationManager,
    record_change,
    replay_from,
)


def _max_lsn(store):
    return store.conn.execute(
        "SELECT COALESCE(MAX(lsn),0) FROM replication_log").fetchone()[0]


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
    # WAL mode: checkpoint before file copy, ensure data in main DB
    store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

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


def test_make_snapshot_db_excludes_internal_tables():
    """快照必须排除 ha_state / replication_log / lsn_seq。

    这三类表是节点本机的复制记账状态：拷入恢复库会导致
    ① replication_log 被二次回放；② lsn_seq 与主库对齐、
    备机升主后产生重复/错乱 lsn；③ ha_state 覆盖备机自身角色/锁状态。
    """
    tmp = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmp, "source.db")
        store = Store(db_path)
        store.conn.execute("CREATE TABLE t(x)")
        store.conn.execute("INSERT INTO t VALUES(42)")
        # 填充内部记账表
        store.conn.execute(
            "INSERT INTO replication_log(op, table_name, row_id, payload) "
            "VALUES('insert','t','1','{}')")
        store.conn.execute("UPDATE lsn_seq SET seq=seq+1")
        store.ha_set("ha_epoch", "5")
        store.conn.commit()
        store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        snap_path = os.path.join(tmp, "snap.db")
        make_snapshot_db(store.conn, snap_path)

        import sqlite3
        c2 = sqlite3.connect(snap_path)
        c2.row_factory = sqlite3.Row
        names = {r[0] for r in c2.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        # 用户表保留
        assert "t" in names
        assert c2.execute("SELECT x FROM t").fetchone()[0] == 42
        # 内部记账表必须被排除
        for excluded in ("ha_state", "replication_log", "lsn_seq"):
            assert excluded not in names, f"{excluded} 不应出现在快照中"
        c2.close()
    finally:
        _rmtree(tmp)


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


def test_replay_rolls_back_on_error():
    """#1 replay_from 中途异常须整体 rollback：半回放不落库、回放锁清除、applied_max 不变。

    P1 的 standby 长连接循环直接复用同一连接，若半回放不被回滚，下一次
    commit 会把残缺数据落库污染副本；锁残留还会让后续正常写入被 WHEN 守卫
    静默漏记。本测试卡住这两个回归。
    """
    import khub.models
    import khub.replication as R

    d = tempfile.mkdtemp()
    try:
        store = Store(os.path.join(d, "dst.db"))
        # 预置一条已提交基线，确认 rollback 只撤销本次回放、不动既有数据
        store.store_document(khub.models.CanonicalDoc(
            canonical_id="base", title="B", content="b",
            source="s", source_id="s/0"))
        store.conn.commit()

        # 注入第二条变更抛错的 documents replayer（第一条正常写入）
        real = R._REPLAYERS.get("documents")
        calls = {"n": 0}

        def flaky(s, op, row_id, payload):
            calls["n"] += 1
            if row_id == "d2":
                raise RuntimeError("injected failure on 2nd change")
            s.apply_document(payload)

        R._REPLAYERS["documents"] = flaky
        try:
            changes = [
                {"lsn": 1, "op": "insert", "table_name": "documents",
                 "row_id": "d1",
                 "payload": json.dumps({"canonical_id": "d1", "title": "D1",
                                        "content": "c1"})},
                {"lsn": 2, "op": "insert", "table_name": "documents",
                 "row_id": "d2",
                 "payload": json.dumps({"canonical_id": "d2", "title": "D2",
                                        "content": "c2"})},
            ]
            raised = False
            try:
                replay_from(store, changes)
            except RuntimeError:
                raised = True
            assert raised, "replay_from 中途异常应向上抛出"

            # 半回放（d1）不应落库
            assert store.get_document("d1") is None, "半回放应被 rollback 撤销"
            assert store.get_document("d2") is None
            # 基线仍在
            assert store.get_document("base") is not None
            # 回放锁已随 rollback 清除（不残留导致后续漏记）
            lock = store.conn.execute(
                "SELECT value FROM ha_state WHERE key='__replay_lock'").fetchone()
            assert lock is None, "异常后回放锁须随 rollback 清除"
            # applied_max 未推进
            assert store.applied_max() == 0
        finally:
            if real is None:
                R._REPLAYERS.pop("documents", None)
            else:
                R._REPLAYERS["documents"] = real
    finally:
        _rmtree(d)


def test_dr_restore_target_backs_up_existing():
    """#2 `dr restore --target <已存在>` 须先备份旧库，绝不静默覆盖（设计 §5/§8）。"""
    import khub.cli as cli
    import khub.models

    base = tempfile.mkdtemp()
    rep_dir = tempfile.mkdtemp()
    main_db = os.path.join(base, "main.db")
    target_db = os.path.join(base, "out.db")
    try:
        # 主库写数据并推快照 + WAL 到本地副本
        store = Store(main_db)
        _write_docs(store, 3, start=1)
        replica = LocalFileReplica(rep_dir)
        mgr = ReplicationManager(store)
        mgr.push_snapshot(replica, db_path=store.path)
        mgr.push_pending(replica)

        # 预置一个「线上」旧库，写入标记行，模拟 --target 指向现网 db
        old = Store(target_db)
        old.store_document(khub.models.CanonicalDoc(
            canonical_id="LIVE", title="live", content="do-not-lose",
            source="s", source_id="s/x"))
        old.conn.commit()

        # 经由 CLI 恢复（覆盖默认库路径，避免动 ~/.khub）
        saved_env = dict(os.environ)
        os.environ["KHUB_DB"] = main_db
        os.environ["KHUB_LIBRARY"] = os.path.join(base, "lib")
        try:
            rc = cli.main(["dr", "restore", "--replica", f"file://{rep_dir}",
                           "--to", "latest", "--target", target_db])
        finally:
            os.environ.clear()
            os.environ.update(saved_env)

        assert rc == 0, "restore 应成功"
        # 旧库已被备份（生成 out.db.bak-<ts>），原文件名被新恢复库占用
        baks = sorted(f for f in os.listdir(base)
                      if f.startswith("out.db.bak-") and not f.endswith(("-wal", "-shm")))
        assert baks, "应生成旧库备份 out.db.bak-*，避免静默覆盖"
        # 备份保留旧库数据，未被覆盖
        bak_store = Store(os.path.join(base, baks[-1]))
        assert bak_store.get_document("LIVE") is not None, "备份须保留旧库数据"
        # 新恢复库含恢复的数据、不含旧标记
        new_store = Store(target_db)
        assert new_store.get_document("LIVE") is None
        assert new_store.get_document("d1") is not None
    finally:
        _rmtree(base)
        _rmtree(rep_dir)


# ── P0b：PITR + 多版本快照 + SshReplica（§5/§7/§8/§9）────────────────────────


def _write_docs(store, count, start=1):
    """写 count 篇文档（canonical_id d<start..start+count-1>）。"""
    from khub.models import CanonicalDoc
    for i in range(start, start + count):
        store.store_document(CanonicalDoc(
            canonical_id=f"d{i}", title=f"T{i}", content=f"C{i}",
            source="s", source_id="s/1"))


def test_pitr_replay_from_target_lsn():
    """replay_from(target_lsn) 仅回放 lsn<=target 的变更。

    注：store_document 对 documents 表各触发 INSERT + UPDATE 两条 WAL，
    故每篇文档对应 2 个 lsn；边界 lsn 以实际 replication_log 最大值计。
    """
    d = tempfile.mkdtemp()
    try:
        store = Store(os.path.join(d, "m.db"))
        _write_docs(store, 5, start=1)          # 阶段 A -> lsn 边界 L5
        lsn5 = _max_lsn(store)
        _write_docs(store, 5, start=6)          # 阶段 B -> lsn 边界 L10
        lsn10 = _max_lsn(store)
        changes = [dict(r) for r in store.conn.execute(
            "SELECT lsn, op, table_name, row_id, payload FROM replication_log")]

        s = Store(os.path.join(d, "r.db"))
        applied = replay_from(s, changes, target_lsn=lsn5)
        # applied 计 WAL 条目数（每篇文档 = INSERT+UPDATE 两条），故 == lsn5
        assert applied == lsn5
        assert s.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 5
        assert s.get_document("d5") is not None
        assert s.get_document("d6") is None
        assert s.applied_max() == lsn5

        s2 = Store(os.path.join(d, "r2.db"))
        replay_from(s2, changes, target_lsn=lsn10)
        assert s2.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 10
    finally:
        _rmtree(d)


def test_pitr_target_lsn_monotonic_rows():
    """同一批变更回放到不同 target_lsn，行数随 target 单调非降。"""
    d = tempfile.mkdtemp()
    try:
        store = Store(os.path.join(d, "m.db"))
        _write_docs(store, 3, start=1)
        lsn3 = _max_lsn(store)
        _write_docs(store, 3, start=4)
        lsn6 = _max_lsn(store)
        _write_docs(store, 4, start=7)
        lsn10 = _max_lsn(store)
        changes = [dict(r) for r in store.conn.execute(
            "SELECT lsn, op, table_name, row_id, payload FROM replication_log")]
        counts = []
        for tl in (lsn3, lsn6, lsn10, None):
            s = Store(os.path.join(d, f"r{tl}.db"))
            replay_from(s, changes, target_lsn=tl)
            counts.append(
                s.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        assert counts == [3, 6, 10, 10]
        assert counts == sorted(counts)
    finally:
        _rmtree(d)


def test_pitr_local_file_replica():
    """完整 PITR：LocalFileReplica 多版本快照 + WAL，恢复到某 lsn 仅含之前的变更。"""
    base = tempfile.mkdtemp()
    rep_dir = tempfile.mkdtemp()
    try:
        main_db = os.path.join(base, "main.db")
        store = Store(main_db)
        replica = LocalFileReplica(rep_dir)
        mgr = ReplicationManager(store)

        # 写前 5 篇，记录边界 lsn
        _write_docs(store, 5, start=1)
        lsn5 = _max_lsn(store)
        mgr.push_snapshot(replica, db_path=store.path)
        mgr.push_pending(replica)

        # 再写 5 篇
        _write_docs(store, 5, start=6)
        mgr.push_snapshot(replica, db_path=store.path)
        mgr.push_pending(replica)

        # 副本侧：选 lsn<=lsn5 的最新快照
        best = replica.best_snapshot_for(lsn5)
        assert best is not None
        assert best["lsn"] == lsn5

        versions = replica.list_versions()
        assert len(versions) == 2
        assert versions[0]["lsn"] == lsn5 and versions[1]["lsn"] > lsn5

        # 恢复到临时 target 库：拷快照 + rebuild_fts + set_applied_max + 回放至 lsn5
        target_db = os.path.join(base, "restored.db")
        shutil.copy(best["db"], target_db)
        restored = Store(target_db)
        rebuild_fts(restored)
        restored.set_applied_max(best["lsn"])
        changes = replica.fetch_changes()
        replay_from(restored, changes, target_lsn=lsn5)

        assert restored.conn.execute(
            "SELECT COUNT(*) FROM documents").fetchone()[0] == 5
        assert restored.get_document("d5") is not None
        assert restored.get_document("d6") is None
        assert restored.applied_max() == lsn5

        # 直接 replay_from(changes, target_lsn=lsn5) 行为一致
        fresh = Store(os.path.join(base, "fresh.db"))
        replay_from(fresh, changes, target_lsn=lsn5)
        assert fresh.conn.execute(
            "SELECT COUNT(*) FROM documents").fetchone()[0] == 5
        assert fresh.get_document("d6") is None
    finally:
        _rmtree(base)
        _rmtree(rep_dir)


# ── SshReplica（用 FakeTransport 模拟远端，无需真实 sshd）────────────────────


class FakeTransport:
    """在本地临时目录模拟 SSH 远端文件系统的 Transport（行为对齐 SshTransport）。"""

    def __init__(self, root):
        self.root = root  # 本地目录，模拟远端根

    def _rp(self, p):
        return os.path.join(self.root, p.lstrip("/"))

    def run(self, cmd_list, input=None, **kw):
        op = cmd_list[0]
        if op == "true":
            return subprocess.CompletedProcess(cmd_list, 0, "", "")
        if op == "mkdir":
            os.makedirs(self._rp(cmd_list[-1]), exist_ok=True)
            return subprocess.CompletedProcess(cmd_list, 0, "", "")
        if op == "ls":
            d = self._rp(cmd_list[-1])
            if not os.path.isdir(d):
                return subprocess.CompletedProcess(cmd_list, 1, "", "no such dir")
            return subprocess.CompletedProcess(
                cmd_list, 0, " ".join(sorted(os.listdir(d))), "")
        if op == "rm":
            p = self._rp(cmd_list[-1])
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            elif os.path.isfile(p):
                os.remove(p)
            return subprocess.CompletedProcess(cmd_list, 0, "", "")
        if op == "cat":
            p = self._rp(cmd_list[-1])
            try:
                with open(p, encoding="utf-8") as f:
                    return subprocess.CompletedProcess(cmd_list, 0, f.read(), "")
            except Exception as e:
                return subprocess.CompletedProcess(cmd_list, 1, "", str(e))
        if op == "mv":
            src = self._rp(cmd_list[1])
            dst = self._rp(cmd_list[2])
            os.replace(src, dst)  # POSIX rename 原子替换
            return subprocess.CompletedProcess(cmd_list, 0, "", "")
        if op == "chmod":
            os.chmod(self._rp(cmd_list[-1]), int(cmd_list[1], 8))
            return subprocess.CompletedProcess(cmd_list, 0, "", "")
        return subprocess.CompletedProcess(cmd_list, 2, "", f"unsupported {op}")

    def send(self, local, remote):
        dst = self._rp(remote)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(local, dst)

    def recv(self, remote, local):
        shutil.copy(self._rp(remote), local)


def test_ssh_replica_multiversion_and_pitr_fake_transport():
    """SshReplica 多版本快照 + 全量 WAL + 远端恢复（FakeTransport，无真实 sshd）。"""
    base = tempfile.mkdtemp()
    remote_root = tempfile.mkdtemp()
    try:
        transport = FakeTransport(remote_root)
        replica = SshReplica("ssh://u@h/dr", transport=transport, keep=5)
        store = Store(os.path.join(base, "m.db"))
        mgr = ReplicationManager(store)

        # 两份多版本快照（边界 lsn 以实际计），且 WAL 全量保留
        _write_docs(store, 5, start=1)
        lsn5 = _max_lsn(store)
        mgr.push_snapshot(replica, db_path=store.path)
        mgr.push_pending(replica)
        _write_docs(store, 5, start=6)
        mgr.push_snapshot(replica, db_path=store.path)
        mgr.push_pending(replica)

        versions = replica.list_remote_versions()
        assert len(versions) == 2
        assert versions[0]["lsn"] == lsn5
        assert versions[1]["lsn"] > lsn5

        # 全量 WAL 历史（I5）：两次 push 的变更都在远端 wal.ndjson
        changes = replica.fetch_changes()
        assert len(changes) == _max_lsn(store)

        # PITR 恢复 lsn5：选 lsn<=lsn5 的最新快照 + 回放截断
        best = versions[0]
        snap_db = replica.fetch_remote_snapshot_db(best["ts"])
        target_db = os.path.join(base, "restored.db")
        shutil.copy(snap_db, target_db)
        restored = Store(target_db)
        rebuild_fts(restored)
        restored.set_applied_max(best["lsn"])
        replay_from(restored, changes, target_lsn=lsn5)
        assert restored.conn.execute(
            "SELECT COUNT(*) FROM documents").fetchone()[0] == 5
        assert restored.get_document("d6") is None
        assert restored.applied_max() == lsn5
    finally:
        _rmtree(base)
        _rmtree(remote_root)


def test_ssh_replica_prune_keeps_recent():
    """远端快照超过 keep 份时，最旧者被清理。"""
    base = tempfile.mkdtemp()
    remote_root = tempfile.mkdtemp()
    try:
        transport = FakeTransport(remote_root)
        replica = SshReplica("ssh://u@h/dr", transport=transport, keep=3)
        store = Store(os.path.join(base, "m.db"))
        # 推 5 份（每份不同 lsn 的 manifest），同秒内 ts 碰撞应自动加毫秒后缀
        for i in range(1, 6):
            replica.push_snapshot(
                {"at": f"t{i}", "tables": {}, "max_replication_id": i,
                 "total_rows": 1}, db_path=store.path)
        versions = replica.list_remote_versions()
        assert len(versions) == 3, versions
        # 保留最近的 3 份（lsn 3,4,5）
        lsns = sorted(v["lsn"] for v in versions)
        assert lsns == [3, 4, 5]
    finally:
        _rmtree(base)
        _rmtree(remote_root)


def test_ssh_replica_atomic_replace():
    """远端文件经 .part + 同连接 mv 原子替换：终态文件存在、无 .part 残留，
    且权限为 600（评审 LOW 安全落地 §8）。"""
    import stat
    base = tempfile.mkdtemp()
    remote_root = tempfile.mkdtemp()
    try:
        transport = FakeTransport(remote_root)
        replica = SshReplica("ssh://u@h/dr", transport=transport, keep=5)
        store = Store(os.path.join(base, "m.db"))
        replica.push_snapshot(
            {"at": "t", "tables": {}, "max_replication_id": 1, "total_rows": 1},
            db_path=store.path)

        snap_dir = os.path.join(remote_root, "dr", "snapshots")
        snaps = sorted(os.listdir(snap_dir))
        assert len(snaps) == 1
        d = os.path.join(snap_dir, snaps[0])
        # 终态文件齐全，且不应残留 .part 半成品
        final_files = sorted(os.listdir(d))
        assert "snapshot.json" in final_files
        assert "db.snapshot" in final_files
        assert not any(f.endswith(".part") for f in final_files), final_files
        # 权限收窄为 600
        for fn in ("snapshot.json", "db.snapshot"):
            mode = stat.S_IMODE(os.stat(os.path.join(d, fn)).st_mode)
            assert mode == 0o600, oct(mode)

        # WAL 推送同样原子且 chmod 600
        replica.push_changes([Change("insert", "documents", "d1", "{}")])
        wal = os.path.join(remote_root, "dr", "wal.ndjson")
        assert os.path.isfile(wal)
        assert not os.path.exists(wal + ".part")
        assert stat.S_IMODE(os.stat(wal).st_mode) == 0o600
    finally:
        _rmtree(base)
        _rmtree(remote_root)


def _ssh_available() -> bool:
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=3",
         "localhost", "true"],
        capture_output=True)
    return r.returncode == 0


def test_ssh_replica_integration_real_sshd():
    """真机 sshd 集成测试：多版本 push + list + restore。无 sshd 则跳过。"""
    import pytest
    if not _ssh_available():
        pytest.skip("本机无可用 sshd（ssh -o BatchMode=yes localhost true 失败）")

    from khub.replication import SshReplica, ReplicationManager

    base = tempfile.mkdtemp()
    try:
        remote_dir = f"~/khub-test-dr-{os.getpid()}"
        replica = SshReplica(f"ssh://localhost/{remote_dir}", keep=5)
        store = Store(os.path.join(base, "m.db"))
        mgr = ReplicationManager(store)

        _write_docs(store, 5, start=1)
        lsn5 = _max_lsn(store)
        mgr.push_snapshot(replica, db_path=store.path)
        mgr.push_pending(replica)
        _write_docs(store, 5, start=6)
        mgr.push_snapshot(replica, db_path=store.path)
        mgr.push_pending(replica)

        versions = replica.list_remote_versions()
        assert len(versions) == 2

        best = versions[0]
        snap_db = replica.fetch_remote_snapshot_db(best["ts"])
        target_db = os.path.join(base, "restored.db")
        shutil.copy(snap_db, target_db)
        restored = Store(target_db)
        rebuild_fts(restored)
        restored.set_applied_max(best["lsn"])
        replay_from(restored, replica.fetch_changes(), target_lsn=lsn5)
        assert restored.conn.execute(
            "SELECT COUNT(*) FROM documents").fetchone()[0] == 5
    finally:
        _rmtree(base)
