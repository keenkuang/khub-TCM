import json
import os
import time
import urllib.error
import urllib.request
import warnings

from .db import Store
from .models import CanonicalDoc

BASE = "https://ima.qq.com/openapi/wiki/v1"
_API_DELAY = 0.5  # 每次 API 调用间隔（秒），避免触发频率限制


def _get_client_id():
    return os.environ.get("IMA_CLIENT_ID", "")


def _get_api_key():
    return os.environ.get("IMA_API_KEY", "")


def _req(endpoint, body, _retry=0):
    """带频率限制处理的 API 请求。遇 429/110021 自动退避重试（最多 3 次）。"""
    url = f"{BASE}/{endpoint}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("ima-openapi-clientid", _get_client_id())
    req.add_header("ima-openapi-apikey", _get_api_key())

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            obj = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 429 and _retry < 3:
            wait = 2 ** (_retry + 1)
            warnings.warn(f"IMA 频率限制(429)，{wait}s 后重试")
            time.sleep(wait)
            return _req(endpoint, body, _retry + 1)
        raise RuntimeError(f"IMA HTTP {e.code}: {e.reason}")

    if obj.get("code") != 0:
        code = obj.get("code", 0)
        msg = obj.get("msg", "")
        if code == 110021 and _retry < 3:  # 请求频控
            wait = 2 ** (_retry + 1)
            warnings.warn(f"IMA 频控(code=110021)，{wait}s 后重试")
            time.sleep(wait)
            return _req(endpoint, body, _retry + 1)
        raise RuntimeError(f"IMA error [{code}]: {msg}")

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
        time.sleep(_API_DELAY)
    return items


def get_knowledge_base(kb_id):
    """获取单个知识库详情。"""
    data = _req("get_knowledge_base", {"ids": [kb_id]})
    info = data.get("infos", {}).get(kb_id, {})
    return {"id": info.get("id", ""), "name": info.get("name", ""),
            "file_count": 0}


def _browse(store, kb_id, folder_id, ingested, _depth=0):
    """递归浏览知识库并入库文档。_depth 防止过深递归。"""
    if _depth > 20:
        return
    cursor = ""
    while True:
        data = _req("get_knowledge_list", {
            "cursor": cursor, "limit": 50,
            "knowledge_base_id": kb_id, "folder_id": folder_id})
        for item in data.get("knowledge_list", []):
            media_type = item.get("media_type", 0)
            if media_type == 99:  # 文件夹
                _browse(store, kb_id, item.get("media_id", ""),
                        ingested, _depth + 1)
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
                if not file_url:
                    continue
                dl = urllib.request.Request(file_url)
                with urllib.request.urlopen(dl, timeout=60) as resp:
                    content_bytes = resp.read()
                text = content_bytes.decode("utf-8", errors="replace")
                doc = CanonicalDoc(
                    canonical_id=cid, title=title, content=text,
                    source="ima", source_id=media_id, origin="ima")
                store.store_document(doc)
                ingested.append(cid)
                time.sleep(_API_DELAY)
            except Exception as exc:
                warnings.warn(f"IMA 跳过 {title}({media_id}): {exc}")
        if data.get("is_end", True):
            break
        cursor = data.get("next_cursor", "")
        time.sleep(_API_DELAY)


def sync_knowledge_base(store, kb_id):
    """同步单个知识库。返回 {ingested, skipped}。"""
    ingested = []
    _browse(store, kb_id, "", ingested)
    return {"ingested": len(ingested), "skipped": 0}


def sync_all(store, verbose=True):
    """同步所有知识库。返回 [{"kb_id","kb_name","ingested"}]。"""
    results = []
    kbs = list_knowledge_bases()
    if verbose:
        print(f"IMA 知识库: {len(kbs)} 个")
    for i, kb in enumerate(kbs, 1):
        if verbose:
            print(f"  [{i}/{len(kbs)}] {kb['name']} ({kb['file_count']} 篇)...", end=" ")
        try:
            res = sync_knowledge_base(store, kb["id"])
        except Exception as exc:
            res = {"ingested": 0, "skipped": 0}
            if verbose:
                print(f"失败: {exc}")
        res["kb_id"] = kb["id"]
        res["kb_name"] = kb["name"]
        results.append(res)
        if verbose:
            print(f"入库 {res['ingested']}")
    return results


# ---------- 写回 IMA 知识库（双向同步） ----------

def sync_adapter(store, kb_id):
    """返回一个 TwoWaySyncAdapter，供 TwoWaySyncEngine 使用。
    调用方传 kb_id 来指定推送到哪个知识库。"""
    from .sync_engine import TwoWaySyncAdapter
    adapter = TwoWaySyncAdapter()
    adapter.name = f"ima:{kb_id}"
    adapter.direction = "both"
    adapter.pull = lambda s: _browse_for_sync(s, kb_id)
    adapter.push = lambda s, doc_id, content, title: _push_doc(s, kb_id, content, title)
    adapter.delete = lambda s, source_id: _delete_doc(s, kb_id, source_id)
    return adapter

def _browse_for_sync(store, kb_id):
    """供 engine 使用的 pull 函数，返回 [{source_id, title, content, hash}]。"""
    ingested = []
    _browse(store, kb_id, "", ingested)
    items = []
    for cid in ingested:
        doc = store.get_document(cid)
        if doc:
            vers = store.get_versions(cid)
            h = vers[-1]["hash"] if vers else ""
            items.append({
                "source_id": cid,
                "title": doc["title"],
                "content": vers[-1]["content"] if vers else "",
                "hash": h,
            })
    return items

def _push_doc(store, kb_id, content, title):
    """推送一篇文档到指定 IMA 知识库。用 add_knowledge 接口。
    返回 media_id。"""
    ext = "txt"
    body_bytes = content.encode("utf-8")
    create_data = _req("create_media", {
        "file_name": title + "." + ext,
        "file_size": len(body_bytes),
        "content_type": "text/plain",
        "knowledge_base_id": kb_id,
        "file_ext": ext,
    })
    media_id = create_data.get("media_id", "")
    if not media_id:
        raise RuntimeError("create_media 未返回 media_id")
    add_data = _req("add_knowledge", {
        "media_id": media_id,
        "title": title,
        "knowledge_base_id": kb_id,
        "file_info": {"file_name": title + "." + ext, "file_size": len(body_bytes)},
    })
    return add_data.get("media_id", media_id)

def _delete_doc(store, kb_id, source_id):
    """删除 IMA 知识库中的文档（暂未找到 IMA 删除 API，留空）。
    返回 True 表示成功。"""
    import warnings
    warnings.warn(f"IMA 删除暂未实现: {source_id}")
    return False
