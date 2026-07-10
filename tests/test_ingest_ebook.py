import os
import tempfile
import zipfile

from khub.db import Store
from khub.ingest import ingest_ebook, register_ebook
from khub.storage import ManagedLibrary
import pytest
pytestmark = [pytest.mark.slow, pytest.mark.full]



def _make_epub_with_text(path, title="黄帝内经", body="中医讲究阴阳平衡"):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="c.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles>'
                   "</container>")
        opf = ('<?xml version="1.0"?><package '
               'xmlns="http://www.idpf.org/2007/opf" '
               'xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata>'
               f"<dc:title>{title}</dc:title>"
               "</metadata></package>")
        z.writestr("c.opf", opf)
        z.writestr("chap1.xhtml",
                   f'<?xml version="1.0"?><html><body><p>{body}</p></body></html>')


def test_ingest_ebook_indexes_text():
    d = tempfile.mkdtemp()
    src = os.path.join(d, "b.epub")
    _make_epub_with_text(src)
    store = Store(":memory:")
    lib = ManagedLibrary(os.path.join(d, "lib"))
    cid = register_ebook(store, lib, src)

    assert store.list_ebooks()[0]["ingested"] == 0
    vid = ingest_ebook(store, cid)
    assert vid >= 1
    assert store.list_ebooks()[0]["ingested"] == 1
    # 有正文版本
    assert len(store.get_versions(cid)) == 1
    # FTS 可检索正文关键词
    hits = store.search_old("阴阳平衡")
    assert hits and hits[0][0] == cid
    # 向量化入库：embeddings 表写入了本版本文档的向量
    emb = store.conn.execute(
        "SELECT count(*) AS c FROM embeddings WHERE doc_id=? AND version_id=?",
        (cid, vid)).fetchone()["c"]
    assert emb == 1
    # 向量检索能召回本文档
    from khub.retrieval import Retriever
    sim = Retriever(store).search_similar("中医 阴阳", k=3)
    assert any(d == cid for d, _ in sim)


def test_ingest_unknown_raises():
    store = Store(":memory:")
    try:
        ingest_ebook(store, "ebook:deadbeef")
        assert False, "should raise"
    except ValueError:
        pass
