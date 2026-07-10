import os
import tempfile

from khub.db import Store
from khub.watch import watch_and_ingest
import pytest
pytestmark = pytest.mark.smoke



def test_watch_ingests_new_md():
    d = tempfile.mkdtemp()
    store = Store(":memory:")
    # 首次扫描：空目录，应退出且不入库
    watch_and_ingest(store, d, interval=0.1, stop=lambda: True)
    assert store.conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 0

    # 落盘一份 .md
    p = os.path.join(d, "伤寒论.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write("太阳病，发热汗出。")
    watch_and_ingest(store, d, interval=0.1, stop=lambda: True)

    rows = store.conn.execute(
        "SELECT canonical_id, title FROM documents").fetchall()
    assert len(rows) == 1
    assert rows[0]["title"] == "伤寒论"
    # FTS 可检索
    assert store.search_old("太阳病")


def test_watch_skips_unchanged():
    d = tempfile.mkdtemp()
    store = Store(":memory:")
    p = os.path.join(d, "a.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write("内容一")
    watch_and_ingest(store, d, interval=0.1, stop=lambda: True)
    n0 = store.conn.execute("SELECT count(*) FROM document_versions").fetchone()[0]
    # 再次扫描，文件未变，不应新增版本
    watch_and_ingest(store, d, interval=0.1, stop=lambda: True)
    n1 = store.conn.execute("SELECT count(*) FROM document_versions").fetchone()[0]
    assert n1 == n0
