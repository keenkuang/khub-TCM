import re
import zipfile
from xml.etree import ElementTree as ET

NS = {"dc": "http://purl.org/dc/elements/1.1/"}


def _find_opf(z):
    if "META-INF/container.xml" in z.namelist():
        container = z.read("META-INF/container.xml").decode("utf-8", "ignore")
        m = re.search(r'full-path="([^"]+)"', container)
        if m:
            return m.group(1)
    candidates = [n for n in z.namelist() if n.endswith(".opf")]
    return candidates[0] if candidates else None


def parse_meta(path):
    meta = {}
    try:
        with zipfile.ZipFile(path) as z:
            opf_name = _find_opf(z)
            if not opf_name:
                return meta
            root = ET.fromstring(z.read(opf_name))
    except (zipfile.BadZipFile, ET.ParseError, OSError):
        return meta

    def text(tag):
        el = root.find(f".//dc:{tag}", NS)
        return el.text.strip() if el is not None and el.text else None

    title = text("title")
    if title:
        meta["title"] = title
    author = text("creator")
    if author:
        meta["author"] = author
    lang = text("language")
    if lang:
        meta["lang"] = lang
    ident = text("identifier")
    if ident:
        meta["isbn"] = ident
    return meta
