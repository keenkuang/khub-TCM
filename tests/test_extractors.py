import os
import tempfile
import zipfile

from khub.extractors import parse_meta


def _make_epub(path, title="Test Book", creator="Author X", lang="zh",
               ident="urn:isbn:1234567890"):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles>'
                   "</container>")
        opf = (
            '<?xml version="1.0"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            "<metadata>"
            f"<dc:title>{title}</dc:title>"
            f"<dc:creator>{creator}</dc:creator>"
            f"<dc:language>{lang}</dc:language>"
            f"<dc:identifier>{ident}</dc:identifier>"
            "</metadata></package>"
        )
        z.writestr("OEBPS/content.opf", opf)


def test_epub_parse_meta():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "b.epub")
    _make_epub(p)
    meta = parse_meta(p)
    assert meta["title"] == "Test Book"
    assert meta["author"] == "Author X"
    assert meta["lang"] == "zh"
    assert meta["isbn"] == "urn:isbn:1234567890"


def test_unknown_extension_returns_empty():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "x.txt")
    with open(p, "w") as f:
        f.write("hi")
    assert parse_meta(p) == {}
