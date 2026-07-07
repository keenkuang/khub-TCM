def parse_meta(path):
    """Best-effort PDF 元数据提取，依赖可选 pypdf；缺失时返回空 dict。"""
    try:
        from pypdf import PdfReader
    except ImportError:
        return {}
    try:
        reader = PdfReader(path)
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
