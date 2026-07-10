import os
import shutil
import sqlite3
import tempfile

import pytest

from khub.db import Store, make_snapshot_db, rebuild_fts
from khub.retrieval import HAVE_VEC, _pack, rebuild_vec
pytestmark = pytest.mark.slow



def _seed_embeddings(conn, n=4, dim=4, model="local"):
    conn.execute("DELETE FROM embeddings")
    for i in range(n):
        vec = [(i + 1) * 0.1 + j * 0.01 for j in range(dim)]
        conn.execute(
            "INSERT INTO embeddings(doc_id, version_id, model, vector) VALUES(?,?,?,?)",
            (f"d{i}", i, model, sqlite3.Binary(_pack(vec))))
    conn.commit()


def test_rebuild_vec_populates_vec0():
    """rebuild_vec 从 embeddings 反算 vec0 虚表。"""
    if not HAVE_VEC:
        pytest.skip("sqlite_vec 不可用，rebuild_vec 会跳过")
    d = tempfile.mkdtemp()
    try:
        store = Store(os.path.join(d, "s.db"))
        _seed_embeddings(store.conn, n=5)
        rebuild_vec(store)
        n_vec = store.conn.execute("SELECT COUNT(*) FROM vec_local").fetchone()[0]
        assert n_vec == 5
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_rebuild_vec_after_restore():
    """恢复后（vec0 被快照排除）rebuild_vec 重建向量索引。"""
    if not HAVE_VEC:
        pytest.skip("sqlite_vec 不可用")
    d = tempfile.mkdtemp()
    try:
        src = Store(os.path.join(d, "src.db"))
        _seed_embeddings(src.conn, n=4)
        snap = os.path.join(d, "snap.db")
        make_snapshot_db(src.conn, snap)
        out = os.path.join(d, "restored.db")
        shutil.copy(snap, out)
        for ext in ("-wal", "-shm"):
            p = out + ext
            if os.path.exists(p):
                os.remove(p)
        restored = Store(out)
        rebuild_fts(restored)
        rebuild_vec(restored)
        n_emb = restored.conn.execute(
            "SELECT COUNT(*) FROM embeddings WHERE model='local'").fetchone()[0]
        n_vec = restored.conn.execute("SELECT COUNT(*) FROM vec_local").fetchone()[0]
        assert n_vec == n_emb == 4
    finally:
        shutil.rmtree(d, ignore_errors=True)
