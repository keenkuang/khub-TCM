import os
import tempfile
import zipfile

from khub.api import App
from khub.db import Store
from khub.storage import ManagedLibrary
import pytest
pytestmark = pytest.mark.smoke



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
    assert code == 200 and obj["hits"] and obj["hits"][0]["doc_id"] == cid


def test_api_documents_requires_title_and_content():
    app, _, _ = _app()
    code, obj = app.dispatch("POST", "/documents", {"title": "x"})
    assert code == 400 and "必填" in obj["error"]
    code, obj = app.dispatch("POST", "/documents", {"content": "y"})
    assert code == 400 and "必填" in obj["error"]


def test_api_documents_ingest_and_searchable():
    app, _, _ = _app()
    payload = {
        "title": "桂枝汤证治",
        "content": "太阳病，头痛发热，汗出恶风者，桂枝汤主之。",
        "source": "KZOCR",
        "source_id": "kzocr-abc",
        "format": "markdown",
        "metadata": {"book": "伤寒论", "page": 12},
    }
    code, obj = app.dispatch("POST", "/documents", payload)
    assert code == 201
    assert obj["doc_id"] == "kzocr-abc"
    assert obj["version_id"] >= 1

    code, obj = app.dispatch("GET", "/search?q=" + "桂枝汤")
    assert code == 200 and obj["hits"] and obj["hits"][0]["doc_id"] == "kzocr-abc"

    # metadata 应被序列化为 note 字段落库（存于 document_versions.note）
    import json
    ver = app.store.get_versions("kzocr-abc")[0]
    assert json.loads(ver["note"])["book"] == "伤寒论"
    # 全文查看
    code, obj = app.dispatch("GET", "/documents/kzocr-abc")
    assert code == 200
    assert "太阳病" in obj["content"]

def test_api_document_url_encoded():
    """URL 编码的文档 ID 应正常解码。"""
    app, _, _ = _app()
    app.dispatch("POST", "/documents",
                 {"title": "麻黄汤", "content": "麻黄汤主之。",
                  "source_id": "kzocr-encoded"})
    # 模拟 JS encodeURIComponent 编码后的 URL
    code, obj = app.dispatch("GET", "/documents/kzocr%2Dencoded")
    assert code == 200 and obj["title"] == "麻黄汤"


def test_api_document_format_field():
    """文档详情应返回 format 字段。"""
    import os, tempfile, zipfile
    from khub.api import App
    from khub.db import Store
    from khub.storage import ManagedLibrary
    d = tempfile.mkdtemp()
    store = Store(":memory:")
    lib = ManagedLibrary(os.path.join(d, "lib"))
    app = App(store, lib)
    app.dispatch("POST", "/documents",
                 {"title": "格式化测试", "content": "<p>HTML内容</p>",
                  "source_id": "fmt-test"})
    code, obj = app.dispatch("GET", "/documents/fmt-test")
    assert code == 200
    assert "format" in obj
    assert obj["format"] in ("html", "markdown", "plain")


def test_api_documents_auto_id_when_missing_source_id():
    app, _, _ = _app()
    code, obj = app.dispatch("POST", "/documents",
                             {"title": "无源编号", "content": "正文内容"})
    assert code == 201
    assert obj["doc_id"].startswith("kzocr-")
    assert app.store.get_document(obj["doc_id"]) is not None


def test_api_short_query_search_fallback():
    # trigram 不支持 <3 字符，短查询（如方剂名"麻黄"）应退回 LIKE 命中
    app, _, _ = _app()
    app.dispatch("POST", "/documents",
                 {"title": "麻黄汤证治",
                  "content": "太阳病，头痛发热，身疼腰痛，恶风无汗而喘者，麻黄汤主之。",
                  "source_id": "kzocr-mahuang"})
    code, obj = app.dispatch("GET", "/search?q=" + "麻黄")
    assert code == 200 and obj["hits"] and obj["hits"][0]["doc_id"] == "kzocr-mahuang"


def test_api_multi_token_search():
    """多词联合搜索："麻黄 桂枝" 应命中同时包含两者的文档。"""
    app, _, _ = _app()
    app.dispatch("POST", "/documents",
                 {"title": "方一", "content": "麻黄、桂枝、杏仁、甘草。麻黄汤方。",
                  "source_id": "mt-1"})
    app.dispatch("POST", "/documents",
                 {"title": "方二", "content": "桂枝、芍药、生姜、大枣。桂枝汤方。",
                  "source_id": "mt-2"})
    # 两个词都命中
    code, obj = app.dispatch("GET", "/search?q=" + "麻黄 桂枝")
    assert code == 200
    ids = [d["doc_id"] for d in obj["hits"]]
    assert "mt-1" in ids
    assert "mt-2" not in ids  # 方二不包含"麻黄"
    # 1 个词
    code, obj = app.dispatch("GET", "/search?q=" + "桂枝")
    assert code == 200 and len(obj["hits"]) == 2


def test_api_list_documents_and_conflicts():
    app, _, _ = _app()
    app.dispatch("POST", "/documents",
                 {"title": "清单文档", "content": "正文", "source_id": "kzocr-list"})
    code, obj = app.dispatch("GET", "/documents")
    assert code == 200
    assert any(d["canonical_id"] == "kzocr-list" for d in obj)

    code, obj = app.dispatch("GET", "/conflicts")
    assert code == 200 and obj == []


def test_api_root_serves_html_ui():
    app, _, _ = _app()
    res = app.dispatch("GET", "/")
    assert len(res) == 3
    code, html, ctype = res
    assert code == 200 and "text/html" in ctype and "kHUB" in html


def test_api_health():
    app, _, _ = _app()
    code, obj = app.dispatch("GET", "/health")
    assert code == 200
    assert obj["status"] == "ok"
    assert obj["version"] == "0.2.9"
    assert "uptime_sec" in obj
    assert "checks" in obj
    assert obj["checks"]["db"]["documents"] == 0
    app.dispatch("POST", "/documents",
                 {"title": "x", "content": "y", "source_id": "hz"})
    code, obj = app.dispatch("GET", "/health")
    assert obj["checks"]["db"]["documents"] == 1


def test_api_semantic_search():
    app, _, _ = _app()
    app.dispatch("POST", "/documents",
                 {"title": "桂枝汤证治", "content": "太阳病，发热汗出，桂枝汤主之。",
                  "source_id": "kzocr-sem"})
    code, obj = app.dispatch("GET", "/semantic?q=" + "桂枝汤")
    assert code == 200
    assert any(d["doc_id"] == "kzocr-sem" for d in obj)
    assert "score" in obj[0]


class TestAsk:
    def test_post_ask_returns_answer_and_sources(self):
        from khub.api import App
        from khub.db import Store
        from khub.storage import ManagedLibrary
        import tempfile, os
        store = Store()
        lib = ManagedLibrary(tempfile.mkdtemp())
        app = App(store, lib)
        # 先入库文档使之可被检索
        from khub.models import CanonicalDoc
        store.store_document(CanonicalDoc(
            canonical_id="rag-test", title="测试方剂",
            content="小青龙汤：麻黄、芍药、细辛、干姜、甘草、桂枝、五味子、半夏。",
            source="test", source_id="t/r"))
        from khub.retrieval import Retriever
        Retriever(store).index_ebook("rag-test")
        code, obj = app.dispatch("POST", "/ask",
                                 {"question": "小青龙汤的组成？", "k": 3})
        assert code == 200
        assert "answer" in obj
        assert "sources" in obj
        assert isinstance(obj["sources"], list)

    def test_post_ask_missing_question(self):
        from khub.api import App
        from khub.db import Store
        from khub.storage import ManagedLibrary
        import tempfile
        app = App(Store(), ManagedLibrary(tempfile.mkdtemp()))
        code, obj = app.dispatch("POST", "/ask", {})
        assert code == 400
        assert "必填" in obj["error"]

    def test_post_ask_too_long_question(self):
        from khub.api import App
        from khub.db import Store
        from khub.storage import ManagedLibrary
        import tempfile
        app = App(Store(), ManagedLibrary(tempfile.mkdtemp()))
        code, obj = app.dispatch("POST", "/ask",
                                 {"question": "字" * 2001})
        assert code == 400
        assert "2000 字符" in obj["error"]


def test_api_not_found():
    app, _, _ = _app()
    code, _ = app.dispatch("GET", "/nope")
    assert code == 404
