import json
import os
import urllib.request
from .db import Store
from .models import CanonicalDoc

BASE = "https://ima.qq.com/openapi/wiki/v1"


def _get_client_id():
    return os.environ.get("IMA_CLIENT_ID", "")


def _get_api_key():
    return os.environ.get("IMA_API_KEY", "")


def _req(endpoint, body):
    url = f"{BASE}/{endpoint}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("ima-openapi-clientid", _get_client_id())
    req.add_header("ima-openapi-apikey", _get_api_key())
    with urllib.request.urlopen(req, timeout=30) as resp:
        obj = json.loads(resp.read().decode())
    if obj.get("code") != 0:
        raise RuntimeError(f"IMA error: {obj.get('msg','')}")
    return obj.get("data", {})


def list_knowledge_bases():
    """列出所有知识库。返回 [{id, name, file_count}]。"""
    items = []
    cursor = ""
    while True:
        data = _req("search_knowledge_base", {"query": "", "cursor": cursor, "limit": 20})
        for i in data.get("info_list", []):
            items.append({"id": i.get("kb_id", ""), "name": i.get("kb_name", ""),
                          "file_count": int(i.get("content_count", 0))})
        if data.get("is_end", True):
            break
        cursor = data.get("next_cursor", "")
    return items


def get_knowledge_base(kb_id):
    """获取单个知识库详情。"""
    data = _req("get_knowledge_base", {"ids": [kb_id]})
    infos = data.get("infos", {})
    kb = infos.get(kb_id, {})
    return {"id": kb.get("id", ""), "name": kb.get("name", ""),
            "file_count": 0}


def _browse(store, kb_id, folder_id, client_id, api_key, ingested):
    """递归浏览知识库并入库文档。"""
    cursor = ""
    while True:
        data = _req("get_knowledge_list", {"cursor": cursor, "limit": 50, "knowledge_base_id": kb_id, "folder_id": folder_id})
        for item in data.get("knowledge_list", []):
            doc_type = item.get("doc_type", 1)
            if doc_type == 2:  # 文件夹
                _browse(store, kb_id, item.get("folder_id", ""), client_id, api_key, ingested)
                continue
            media_id = item.get("media_id", "")
            title = item.get("title", "")
            if not media_id:
                continue
            cid = f"ima:{media_id}"
            if store.get_document(cid):
                continue
            try:
                media_data = _req("get_media_info", {"media_id": media_id})
                url_info = media_data.get("url_info", {})
                file_url = url_info.get("url", "")
                if file_url:
                    dl = urllib.request.Request(file_url)
                    with urllib.request.urlopen(dl, timeout=60) as resp:
                        content_bytes = resp.read()
                    text = content_bytes.decode("utf-8", errors="replace")
                    doc = CanonicalDoc(canonical_id=cid, title=title, content=text,
                                       source="ima", source_id=media_id, origin="ima")
                    store.store_document(doc)
                    ingested.append(cid)
            except Exception:
                pass
        if data.get("is_end", True):
            break
        cursor = data.get("next_cursor", "")


def sync_knowledge_base(store, kb_id):
    return _sync(store, kb_id)


def _sync(store, kb_id):
    ingested = []
    _browse(store, kb_id, "", _get_client_id(), _get_api_key(), ingested)
    return {"ingested": len(ingested), "skipped": 0}


def sync_all(store):
    results = []
    for kb in list_knowledge_bases():
        res = _sync(store, kb["id"])
        res["kb_id"] = kb["id"]
        res["kb_name"] = kb["name"]
        results.append(res)
    return results
