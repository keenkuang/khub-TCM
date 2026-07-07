import math
from khub.db import Store
from khub.retrieval import LocalEmbedder, Retriever, cosine

def test_local_embedder_deterministic_and_normalized():
    e = LocalEmbedder()
    v1 = e.embed("太阳病发热")
    v2 = e.embed("太阳病发热")
    assert v1 == v2
    assert abs(math.sqrt(sum(x*x for x in v1)) - 1.0) < 1e-6

def test_retriever_stores_and_finds_nearest():
    store = Store(":memory:")
    r = Retriever(store)
    r.index_document("d1", 1, "太阳病发热汗出恶寒")
    r.index_document("d2", 1, "少阴病脉微细但欲寐")
    hits = r.search_similar("太阳病", k=2)
    assert hits[0][0] == "d1"
    assert hits[0][1] >= hits[1][1]   # scores descending

def test_retriever_index_ebook_reads_version_content():
    # minimal: index a doc whose content lives in document_versions
    store = Store(":memory:")
    from khub.models import CanonicalDoc
    store.store_document(CanonicalDoc(canonical_id="x", title="t", content="中医阴阳平衡",
                                      source="s", source_id="s/1", doc_type="ebook"))
    r = Retriever(store)
    r.index_ebook("x")
    hits = r.search_similar("阴阳", k=1)
    assert hits and hits[0][0] == "x"
