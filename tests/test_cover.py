import os, zipfile, tempfile
from khub.db import Store
from khub.ingest import ingest_ebook, register_ebook
from khub.storage import ManagedLibrary
from khub.extractors.epub import extract_cover

PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)  # minimal fake PNG header for ext detection

def _make_epub_with_cover(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        opf = ('<?xml version="1.0"?><package '
               'xmlns="http://www.idpf.org/2007/opf" '
               'xmlns:dc="http://purl.org/dc/elements/1.1/">'
               '<metadata><dc:title>T</dc:title>'
               '<meta name="cover" content="cv"/></metadata>'
               '<manifest><item id="cv" href="images/cover.png" '
               'media-type="image/png"/><item id="c1" href="c1.xhtml" '
               'media-type="application/xhtml+xml"/></manifest></package>')
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/images/cover.png", PNG)
        z.writestr("OEBPS/c1.xhtml", "<html><body>正文</body></html>")

def test_extract_cover_returns_bytes():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "b.epub")
    _make_epub_with_cover(p)
    data = extract_cover(p)
    assert data is not None and data[:4] == b"\x89PNG"

def test_ingest_stores_cover():
    d = tempfile.mkdtemp()
    src = os.path.join(d, "b.epub")
    _make_epub_with_cover(src)
    store = Store(":memory:")
    lib = ManagedLibrary(os.path.join(d, "lib"))
    cid = register_ebook(store, lib, src)
    ingest_ebook(store, cid)
    em = store.conn.execute("SELECT cover_path FROM ebook_meta WHERE canonical_id=?", (cid,)).fetchone()
    assert em["cover_path"]
    assert os.path.exists(em["cover_path"])
    att = store.conn.execute("SELECT * FROM attachments WHERE doc_id=? AND kind='cover'", (cid,)).fetchone()
    assert att is not None
