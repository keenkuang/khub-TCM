"""目录监听自动入库：KZOCR 产出目录新增/更新 .md 即自动入库到 khub。"""
import hashlib
import os
import time

from .db import Store, compute_hash
from .models import CanonicalDoc
from .retrieval import Retriever


def _sid(path: str) -> str:
    return "watch:" + hashlib.sha256(os.path.abspath(path).encode("utf-8")).hexdigest()[:16]


def _latest_hash(store: Store, doc_id: str):
    row = store.conn.execute(
        "SELECT hash FROM document_versions WHERE doc_id=? "
        "ORDER BY version_id DESC LIMIT 1", (doc_id,)).fetchone()
    return row["hash"] if row else None


def watch_and_ingest(store: Store, directory: str, interval: float = 3.0, stop=None):
    """轮询 directory 下的 .md 文件，新增或修改即入库（内容不变则跳过）。

    stop 为可选可调用对象；返回 True 时退出循环（便于测试/优雅停止）。
    """
    seen: dict[str, float] = {}  # sid -> mtime，单次运行内去重
    retr = Retriever(store)
    print(f"[watch] 监听目录 {directory}（间隔 {interval}s）")
    while True:
        for root, _, files in os.walk(directory):
            for fn in files:
                if not fn.endswith(".md"):
                    continue
                fp = os.path.join(root, fn)
                try:
                    mtime = os.path.getmtime(fp)
                except OSError:
                    continue
                sid = _sid(fp)
                if seen.get(sid) == mtime:
                    continue
                try:
                    with open(fp, encoding="utf-8") as fh:
                        content = fh.read()
                except OSError:
                    continue
                # 内容未变则跳过（跨进程也幂等）
                if _latest_hash(store, sid) == compute_hash(content):
                    seen[sid] = mtime
                    continue
                doc = CanonicalDoc(
                    canonical_id=sid, title=os.path.splitext(fn)[0],
                    content=content, source="watch", source_id=sid, origin="kzocr")
                store.store_document(doc)
                try:
                    retr.index_ebook(sid)
                except Exception:  # 向量化失败不影响入库  # nosec B110
                    pass
                seen[sid] = mtime
                print(f"[watch] 入库 {fp}")
        if stop is not None and stop():
            break
        time.sleep(interval)
