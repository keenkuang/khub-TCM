import os
import re
import zipfile
from xml.etree import ElementTree as ET

NS = {"dc": "http://purl.org/dc/elements/1.1/"}
OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}


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


def extract_cover(path):
    """Detect the cover image of an EPUB and return its raw bytes, or None.

    Supports EPUB2 (<meta name="cover" content="ID"/> + manifest item) and
    EPUB3 (manifest item with properties="cover-image").
    """
    try:
        with zipfile.ZipFile(path) as z:
            opf_name = _find_opf(z)
            if not opf_name:
                return None
            root = ET.fromstring(z.read(opf_name))
            manifest = root.find("opf:manifest", OPF_NS)
            if manifest is None:
                return None
            cover_id = None
            # EPUB2: <meta name="cover" content="ID"/>
            meta_el = root.find("opf:metadata", OPF_NS)
            if meta_el is not None:
                for m in meta_el.findall("opf:meta", OPF_NS):
                    if m.get("name") == "cover":
                        cover_id = m.get("content")
                        break
            href = None
            for item in manifest.findall("opf:item", OPF_NS):
                if item.get("properties") == "cover-image":
                    href = item.get("href")
                    break
                if cover_id is not None and item.get("id") == cover_id:
                    href = item.get("href")
                    break
            if not href:
                return None
            # Resolve relative to the OPF directory
            base = os.path.dirname(opf_name)
            entry = os.path.normpath(os.path.join(base, href)).replace(os.sep, "/")
            if entry not in z.namelist():
                return None
            return z.read(entry)
    except (zipfile.BadZipFile, ET.ParseError, OSError, KeyError):
        return None


def extract_text(path):
    try:
        with zipfile.ZipFile(path) as z:
            htmls = [n for n in z.namelist()
                     if n.endswith((".xhtml", ".html", ".htm"))]
            parts = []
            for n in htmls:
                data = z.read(n).decode("utf-8", "ignore")
                plain = re.sub(r"<[^>]+>", " ", data)
                plain = re.sub(r"\s+", " ", plain).strip()
                if plain:
                    parts.append(plain)
            return "\n".join(parts)
    except (zipfile.BadZipFile, OSError):
        return ""
