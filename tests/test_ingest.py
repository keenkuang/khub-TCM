import os
import tempfile
import zipfile

from khub.db import Store
from khub.ingest import register_ebook
from khub.storage import ManagedLibrary


def _make_epub(path, title="My Book", creator="Jane"):
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
               f"<dc:creator>{creator}</dc:creator>"
               "</metadata></package>")
        z.writestr("c.opf", opf)


def test_register_ebook_catalog_only():
    d = tempfile.mkdtemp()
    src = os.path.join(d, "b.epub")
    _make_epub(src)
    store = Store(":memory:")
    lib = ManagedLibrary(os.path.join(d, "lib"))
    cid = register_ebook(store, lib, src)

    assert cid.startswith("ebook:")
    ebooks = store.list_ebooks()
    assert len(ebooks) == 1
    assert ebooks[0]["title"] == "My Book"
    assert ebooks[0]["author"] == "Jane"
    assert ebooks[0]["ingested"] == 0

    # 原文件已入受管库
    f = store.conn.execute("SELECT * FROM files").fetchone()
    assert f is not None and os.path.exists(f["path"])

    # 不入库：无正文版本、无 FTS 行
    assert len(store.get_versions(cid)) == 0
    assert store.conn.execute(
        "SELECT count(*) AS c FROM docs_fts WHERE doc_id=?", (cid,)).fetchone()["c"] == 0


def test_register_ebook_idempotent():
    d = tempfile.mkdtemp()
    src = os.path.join(d, "b.epub")
    _make_epub(src)
    store = Store(":memory:")
    lib = ManagedLibrary(os.path.join(d, "lib"))
    c1 = register_ebook(store, lib, src)
    c2 = register_ebook(store, lib, src)
    assert c1 == c2
    assert len(store.list_ebooks()) == 1
