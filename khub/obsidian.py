"""Obsidian vault adapter — import .md files directly from a directory."""

import os
import hashlib

from .db import Store, compute_hash
from .models import CanonicalDoc


def import_vault(store: Store, vault_path: str, recursive: bool = True):
    """Walk vault_path, ingest every .md file into store.

    Returns (ingested_count, skipped_count).
    """
    ingested = 0
    skipped = 0
    vault_path = os.path.abspath(vault_path)

    for root, _dirs, files in os.walk(vault_path):
        if not recursive and root != vault_path:
            continue
        for fn in files:
            if not fn.endswith(".md"):
                continue
            fp = os.path.join(root, fn)
            ok, was_skipped = _import_file(store, vault_path, fp)
            ingested += ok
            skipped += was_skipped
        if not recursive:
            break

    return ingested, skipped


def _import_file(store: Store, vault_path: str, fp: str):
    """Import a single .md file. Returns (ingested, skipped) where one is 1, the other 0."""
    rel = os.path.relpath(fp, vault_path)
    source_id = "obsidian:" + hashlib.sha256(rel.encode("utf-8")).hexdigest()[:16]

    with open(fp, "r", encoding="utf-8") as fh:
        content = fh.read()

    content_hash = compute_hash(content)

    # 幂等检查：已存在且内容哈希相同 → 跳过
    row = store.get_document(source_id)
    if row is not None:
        cur = store.conn.execute(
            "SELECT hash FROM document_versions WHERE doc_id=? ORDER BY version_id DESC LIMIT 1",
            (source_id,),
        ).fetchone()
        if cur is not None and cur["hash"] == content_hash:
            return 0, 1  # skipped

    doc = CanonicalDoc(
        canonical_id=source_id,
        title=os.path.splitext(os.path.basename(fp))[0],
        content=content,
        source="obsidian",
        source_id=source_id,
        origin="obsidian",
        hash=content_hash,
    )
    store.store_document(doc)
    try:
        from .retrieval import Retriever
        Retriever(store).index_ebook(source_id)
    except Exception:  # nosec B110
        pass
    return 1, 0  # ingested
