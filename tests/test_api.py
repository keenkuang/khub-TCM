import os
import tempfile
import zipfile

from khub.api import App
from khub.db import Store
from khub.storage import ManagedLibrary


def _make_epub(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="c.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles>'
                   "</container>")
        z.writestr("c.opf", '<?xml version="1.0"?><package '
                   'xmlns="http://www.idpf.org/2007/opf" '
                   'xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   "<metadata><dc:title>伤寒论</dc:title></metadata></package>")
        z.writestr("chap1.xhtml",
                   '<?xml version="1.0"?><html><body><p>太阳病，发热汗出</p></body></html>')


def _app():
    d = tempfile.mkdtemp()
    src = os.path.join(d, "b.epub")
    _make_epub(src)
    store = Store(":memory:")
    lib = ManagedLibrary(os.path.join(d, "lib"))
    return App(store, lib), src, d


def test_api_register_then_ingest_then_search():
    app, src, _ = _app()
    code, obj = app.dispatch("POST", "/ebooks/register", {"path": src})
    assert code == 201
    cid = obj["canonical_id"]

    code, obj = app.dispatch("POST", f"/ebooks/{cid}/ingest")
    assert code == 200 and obj["version_id"] >= 1

    code, obj = app.dispatch("GET", "/ebooks")
    assert code == 200 and obj[0]["ingested"] == 1

    code, obj = app.dispatch("GET", "/search?q=" + "太阳病")
    assert code == 200 and obj and obj[0]["doc_id"] == cid


def test_api_not_found():
    app, _, _ = _app()
    code, _ = app.dispatch("GET", "/nope")
    assert code == 404
