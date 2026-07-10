import json
import urllib.request

from khub.db import Store
from khub.retrieval import Retriever, RemoteEmbedder, get_embedder
import pytest
pytestmark = [pytest.mark.net, pytest.mark.slow]



def _ingest_two(store):
    r = Retriever(store)
    store.store_document(_doc("d1", "太阳病，发热汗出，桂枝汤主之。", "kzocr-d1"))
    store.store_document(_doc("d2", "少阴病，脉微细，但欲寐。", "kzocr-d2"))
    r.index_document("d1", 1, "太阳病，发热汗出，桂枝汤主之。")
    r.index_document("d2", 2, "少阴病，脉微细，但欲寐。")
    return r


def _doc(cid, content, sid):
    from khub.models import CanonicalDoc
    return CanonicalDoc(canonical_id=cid, title=cid, content=content,
                        source="kzocr", source_id=sid, origin="kzocr")


def test_ann_search_uses_vec_index():
    store = Store(":memory:")
    r = _ingest_two(store)
    # vec0 表应已建好（sqlite-vec 可用时）
    assert r._vec_table == "vec_local"
    meta = store.conn.execute("SELECT dim FROM vec_meta WHERE name='vec_local'").fetchone()
    assert meta is not None and meta["dim"] == 256
    hits = r.search_similar("桂枝汤 太阳", k=2)
    assert hits and hits[0][0] == "d1"


def test_ann_disabled_falls_back_to_bruteforce():
    store = Store(":memory:")
    r = _ingest_two(store)
    r.ann = False
    hits = r.search_similar("桂枝汤", k=2)
    assert hits and hits[0][0] == "d1"


def test_remote_embedder_parses_openai_style(monkeypatch):
    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"data": [{"embedding": [0.1, 0.2, 0.3]}]}).encode()

    def fake_urlopen(req, timeout=0):
        assert req.full_url.endswith("/v1/embeddings")
        return FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    emb = RemoteEmbedder("http://127.0.0.1:9999")
    vec = emb.embed("中医")
    assert vec == [0.1, 0.2, 0.3]
    assert emb.dim == 3


def test_get_embedder_selects_remote_when_url_set(monkeypatch):
    monkeypatch.setenv("KHUB_EMBEDDING_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("KHUB_EMBED_DIM", "3")
    e = get_embedder()
    assert isinstance(e, RemoteEmbedder)
    monkeypatch.delenv("KHUB_EMBEDDING_URL")
    assert isinstance(get_embedder(), __import__("khub.retrieval", fromlist=["LocalEmbedder"]).LocalEmbedder)
