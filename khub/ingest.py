import os

from .extractors import parse_meta
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
