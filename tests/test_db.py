from khub.db import Store, compute_hash
from khub.models import CanonicalDoc

def test_init_schema_creates_tables():
    s = Store(":memory:")
    rows = s.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r["name"] for r in rows}
    assert {"documents", "document_versions", "sync_states", "docs_fts"} <= names

def test_store_document_creates_version_and_fts():
    s = Store(":memory:")
    doc = CanonicalDoc(canonical_id="d1", title="T", content="hello world",
                       source="ocr", source_id="ocr/1")
    vid = s.store_document(doc)
    assert vid >= 1
    ver = s.conn.execute("SELECT * FROM document_versions WHERE version_id=?", (vid,)).fetchone()
    assert ver["content"] == "hello world"
    assert s.search_old("hello")[0][0] == "d1"

def test_second_version_is_new_row_not_overwrite():
    s = Store(":memory:")
    d1 = CanonicalDoc(canonical_id="d1", title="T", content="v1", source="ocr", source_id="ocr/1")
    v1 = s.store_document(d1)
    d2 = CanonicalDoc(canonical_id="d1", title="T", content="v2", source="ocr", source_id="ocr/1", origin="hub")
    v2 = s.store_document(d2, parent_version=v1)
    assert v1 != v2
    assert len(s.get_versions("d1")) == 2
