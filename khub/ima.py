import json
import urllib.request
from .db import Store
from .models import CanonicalDoc

BASE = "https://ima.qq.com/openapi/wiki/v1"


def _req(endpoint, body, client_id, api_key):
    url = f"{BASE}/{endpoint}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("ima-openapi-clientid", client_id)
    req.add_header("ima-openapi-apikey", api_key)
    with urllib.request.urlopen(req, timeout=30) as resp:
        obj = json.loads(resp.read().decode("utf-8"))
    if obj.get("code") != 0:
        raise RuntimeError(f"IMA API error: {obj.get('msg', '')}")
    return obj.get("data", {})


def list_knowledge_bases(client_id, api_key):
    items = []
    cursor = ""
    while True:
        data = _req(
            "search_knowledge_base",
            {"query": "", "cursor": cursor, "limit": 20},
            client_id,
            api_key,
        )
        for i in data.get("info_list", []):
            kb = i.get("knowledge_base", {})
            items.append(
                {
                    "id": kb.get("knowledge_base_id", ""),
                    "name": kb.get("name", ""),
                    "file_count": kb.get("file_count", 0),
                }
            )
        if data.get("is_end", True):
            break
        cursor = data.get("next_cursor", "")
    return items


def _browse_kb(store, kb_id, folder_id, client_id, api_key, ingested):
    cursor = ""
    while True:
        data = _req(
            "get_knowledge_list",
            {
                "cursor": cursor,
                "limit": 50,
                "knowledge_base_id": kb_id,
                "folder_id": folder_id,
            },
            client_id,
            api_key,
        )
        for item in data.get("knowledge_list", []):
            if item.get("doc_type") == 2:  # 文件夹
                _browse_kb(
                    store,
                    kb_id,
                    item.get("folder_id", ""),
                    client_id,
                    api_key,
                    ingested,
                )
                continue
            media_id = item.get("media_id", "")
            title = item.get("title", "")
            if not media_id:
                continue
            cid = f"ima:{media_id}"
            if store.get_document(cid):
                continue
            try:
                md = _req(
                    "get_media_info", {"media_id": media_id}, client_id, api_key
                )
                url_info = md.get("url_info", {})
                file_url = url_info.get("url", "")
                file_name = url_info.get("file_name", "")
                if file_url:
                    dl_req = urllib.request.Request(file_url)
                    with urllib.request.urlopen(dl_req, timeout=60) as dl_resp:
                        content_bytes = dl_resp.read()
                    ext = file_name.lower().split(".")[-1] if "." in file_name else ""
                    if ext in ("txt", "md"):
                        text = content_bytes.decode("utf-8", errors="replace")
                    else:
                        text = (
                            f"[IMA file: {file_name}, {len(content_bytes)} bytes]"
                        )
                    doc = CanonicalDoc(
                        canonical_id=cid,
                        title=title,
                        content=text,
                        source="ima",
                        source_id=media_id,
                        origin="ima",
                    )
                    store.store_document(doc)
                    ingested.append(cid)
            except Exception:
                pass
        if data.get("is_end", True):
            break
        cursor = data.get("next_cursor", "")


def sync_knowledge_base(store, kb_id, client_id, api_key):
    ingested = []
    _browse_kb(store, kb_id, "", client_id, api_key, ingested)
    return {"ingested": len(ingested), "skipped": 0}


def sync_all(store, client_id, api_key):
    results = []
    for kb in list_knowledge_bases(client_id, api_key):
        res = sync_knowledge_base(store, kb["id"], client_id, api_key)
        res["kb_id"] = kb["id"]
        res["kb_name"] = kb["name"]
        results.append(res)
    return results
