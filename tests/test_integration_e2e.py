"""核心链路端到端集成测试。
覆盖完整闭环：患者→病历→问诊→孪生摘要→电子书入库→KZOCR 推送→全文检索→语义检索→PII 加密→审计。"""
import json
import os
import tempfile
import zipfile

from khub.api import App
from khub.db import Store
from khub.storage import ManagedLibrary
import pytest
pytestmark = [pytest.mark.slow, pytest.mark.full]



def _make_epub(path, title="温病条辨", body="太阴风温、温热、温疫、冬温，初起恶风寒者，桂枝汤主之。"):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="c.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("c.opf", f'<?xml version="1.0"?><package'
                   f' xmlns="http://www.idpf.org/2007/opf"'
                   f' xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   f"<metadata><dc:title>{title}</dc:title></metadata></package>")
        z.writestr("chap1.xhtml", f'<?xml version="1.0"?><html><body><p>{body}</p></body></html>')


def test_e2e_full_chain():
    """完整业务链路测试：一个情景走完全部子系统。"""
    d = tempfile.mkdtemp()
    store = Store(":memory:")
    lib = ManagedLibrary(os.path.join(d, "lib"))
    app = App(store, lib)

    # ── 1. 患者登记 ──
    code, obj = app.dispatch("POST", "/clinical/patients", {"id": "p001", "name": "李四",
                                                            "gender": "男", "born": "1975-06-15"})
    assert code == 201 and obj["id"] == "p001"
    code, patients = app.dispatch("GET", "/clinical/patients")
    assert code == 200 and len(patients) == 1 and patients[0]["name"] == "李四"

    # ── 2. 病历 ──
    code, obj = app.dispatch("POST", "/clinical/records",
                             {"patient_id": "p001", "diagnosis": "太阴温病",
                              "prescription": "桂枝汤加减", "note": "初诊"})
    assert code == 201 and obj["id"] >= 1

    # ── 3. 问诊 ──
    code, obj = app.dispatch("POST", "/clinical/consultations",
                             {"patient_id": "p001", "chief_complaint": "发热恶寒",
                              "tongue_pulse": "舌红苔薄，脉浮数",
                              "differentiation": "卫分证", "plan": "辛凉解表"})
    assert code == 201 and obj["id"] >= 1

    # ── 4. 孪生摘要（NoOp 兜底应包含聚合数据） ──
    code, obj = app.dispatch("POST", "/clinical/twin/p001/summarize")
    assert code == 200
    summary = obj["summary"]
    assert "李四" in summary
    assert "太阴温病" in summary
    assert "桂枝汤" in summary
    assert "发热恶寒" in summary

    # ── 5. 电子书注册 + 入库 ──
    epath = os.path.join(d, "test.epub")
    _make_epub(epath, body="温病条辨，始上焦，终于下焦。")
    code, obj = app.dispatch("POST", "/ebooks/register", {"path": epath})
    assert code == 201
    cid = obj["canonical_id"]

    code, obj = app.dispatch("POST", f"/ebooks/{cid}/ingest")
    assert code == 200 and obj["version_id"] >= 1

    # ── 6. 全文检索 ──
    code, obj = app.dispatch("GET", "/search?q=" + "温病条辨")
    assert code == 200
    assert any(cid == h["doc_id"] for h in obj["hits"])

    # ── 7. KZOCR 文档推送 ──
    code, obj = app.dispatch("POST", "/documents",
                             {"title": "临证指南医案·咳嗽",
                              "content": "某，咳逆旬日，痰粘喉梗，肺失清肃。",
                              "source_id": "kzocr-e2e-001",
                              "metadata": {"book": "临证指南医案", "page": 15}})
    assert code == 201 and obj["doc_id"] == "kzocr-e2e-001"
    code, obj = app.dispatch("GET", "/search?q=" + "咳逆")
    assert code == 200 and obj["hits"] and obj["hits"][0]["doc_id"] == "kzocr-e2e-001"

    # ── 8. 语义检索（ANN / 暴力余弦） ──
    code, hits = app.dispatch("GET", "/semantic?q=" + "温病")
    assert code == 200
    assert any(d["doc_id"] == cid for d in hits)

    # ── 9. 文档列表 + 冲突 ──
    code, docs = app.dispatch("GET", "/documents")
    assert code == 200 and len(docs) >= 1
    code, conflicts = app.dispatch("GET", "/conflicts")
    assert code == 200 and conflicts == []

    # ── 10. 短查询（2 字符 LIKE 回退） ──
    code, hits = app.dispatch("GET", "/search?q=" + "咳嗽")
    assert code == 200 and hits

    # ── 11. 审计：操作后应有审计日志 ──
    from khub.audit import recent
    rows = recent(store, limit=20)
    events = {r["event"] for r in rows}
    assert "read_twin" in events
    assert "read_patient" in events or "list_patients" in events


def test_e2e_pii_encryption_roundtrip():
    """PII 加密端到端：启用加密后，DB 密文不可读，API 返回明文。"""
    import time
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()

    # 在创建 Store 和调用 API 前设好 env
    os.environ["KHUB_PII_ENCRYPT"] = "1"
    os.environ["KHUB_PII_KEY"] = key
    # 清除可能的 cipher 缓存
    import khub.crypto
    # 重新加载确保新 env 生效
    from importlib import reload
    reload(khub.crypto)
    # 审计模块也需要 reload
    import khub.audit
    reload(khub.audit)

    try:
        d = tempfile.mkdtemp()
        store = Store(":memory:")
        lib = ManagedLibrary(os.path.join(d, "lib"))
        app = App(store, lib)

        # 登记患者
        code, obj = app.dispatch("POST", "/clinical/patients",
                                 {"id": "p_enc", "name": "王五加密测试",
                                  "gender": "女", "born": "1990-07-20"})
        assert code == 201

        # DB 中应是密文（不可读）
        row = store.conn.execute("SELECT name, gender, born FROM patients WHERE id=?",
                                 ("p_enc",)).fetchone()
        assert row["name"] != "王五加密测试"
        assert "王五" not in (row["name"] or "")
        assert row["gender"] != "女"
        assert row["born"] != "1990-07-20"

        # API 读取应正确解密
        code, patients = app.dispatch("GET", "/clinical/patients")
        assert code == 200
        p = next(p for p in patients if p["id"] == "p_enc")
        assert p["name"] == "王五加密测试"
        assert p["gender"] == "女"

        # 审计应仍记录
        from khub.audit import recent
        rows = recent(store, limit=10)
        assert any(r["event"] == "list_patients" for r in rows)
    finally:
        del os.environ["KHUB_PII_ENCRYPT"]
        del os.environ["KHUB_PII_KEY"]


def test_e2e_short_query_like():
    """2 字符短查询（方剂名）应触发 LIKE 回退而非 trigram 空结果。"""
    d = tempfile.mkdtemp()
    store = Store(":memory:")
    lib = ManagedLibrary(os.path.join(d, "lib"))
    app = App(store, lib)

    code, obj = app.dispatch("POST", "/documents",
                             {"title": "桂枝汤", "content": "太阳病，发热汗出，桂枝汤主之。",
                              "source_id": "kzocr-gz"})
    assert code == 201

    # 2 字符查询
    code, obj = app.dispatch("GET", "/search?q=" + "桂枝")
    assert code == 200 and obj["hits"] and obj["hits"][0]["doc_id"] == "kzocr-gz"

    # 1 字符查询
    code, obj = app.dispatch("GET", "/search?q=" + "桂")
    assert code == 200 and obj["hits"] and obj["hits"][0]["doc_id"] == "kzocr-gz"

    # 语义检索也支持短词
    code, hits = app.dispatch("GET", "/semantic?q=" + "桂枝")
    assert code == 200 and hits
