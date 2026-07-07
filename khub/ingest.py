import os

from .extractors import extract_text, parse_meta
from .models import CanonicalDoc
from .storage import ManagedLibrary


def register_ebook(store, library, src_path, move=False):
    """不入库闭环：原文件入受管库 + 注册 files + 解析元数据写 documents/ebook_meta。
    不抽取正文、不建 FTS、不向量化、不提取封面。"""
    sha, dest, size = library.store(src_path, move=move)
    ext = os.path.splitext(src_path)[1].lower().lstrip(".")
    store.upsert_file(sha, dest, size, ext)

    meta = parse_meta(src_path)
    canonical_id = f"ebook:{sha}"
    title = meta.get("title") or os.path.splitext(os.path.basename(src_path))[0]
    store.add_ebook(canonical_id, title, ext, sha, dest, meta)
    return canonical_id


def ingest_ebook(store, canonical_id):
    """入库：抽取正文 → 建版本 → FTS 索引 → 标记 ingested。不向量化/封面（后续阶段）。"""
    doc = store.get_document(canonical_id)
    if doc is None:
        raise ValueError(f"unknown ebook: {canonical_id}")
    frow = store.conn.execute(
        "SELECT path, format FROM files WHERE sha256=?",
        (doc["file_hash"],)).fetchone()
    if frow is None:
        raise ValueError(f"no file registered for {canonical_id}")
    text = extract_text(frow["path"])
    cd = CanonicalDoc(
        canonical_id=canonical_id, title=doc["title"], content=text,
        source="library", source_id=frow["path"], doc_type="ebook",
        format=frow["format"], origin="hub")
    version_id = store.store_document(cd)
    store.mark_ingested(canonical_id, version_id)
    return version_id
