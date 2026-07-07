def _reader(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        return PdfReader(path)
    except Exception:
        return None


def parse_meta(path):
    """Best-effort PDF 元数据提取，依赖可选 pypdf；缺失时返回空 dict。"""
    reader = _reader(path)
    if reader is None:
        return {}
    try:
        info = reader.metadata
        meta = {}
        if info:
            if info.title:
                meta["title"] = str(info.title)
            if info.author:
                meta["author"] = str(info.author)
        meta["page_count"] = len(reader.pages)
        return meta
    except Exception:
        return {}


def extract_text(path):
    reader = _reader(path)
    if reader is None:
        return ""
    try:
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:
        return ""
