import os

from . import epub, pdf


def parse_meta(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".epub":
        return epub.parse_meta(path)
    if ext == ".pdf":
        return pdf.parse_meta(path)
    return {}


def extract_text(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".epub":
        return epub.extract_text(path)
    if ext == ".pdf":
        return pdf.extract_text(path)
    return ""
