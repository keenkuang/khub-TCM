import json
import os
import time
import urllib.request

from .db import Store
from .models import CanonicalDoc

NOTE_BASE = "https://ima.qq.com/openapi/note/v1"
_API_DELAY = 0.5


def _get_client_id():
    return os.environ.get("IMA_CLIENT_ID", "")


def _get_api_key():
    return os.environ.get("IMA_API_KEY", "")


def _req(endpoint, body):
    url = f"{NOTE_BASE}/{endpoint}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("ima-openapi-clientid", _get_client_id())
    req.add_header("ima-openapi-apikey", _get_api_key())
    with urllib.request.urlopen(req, timeout=30) as resp:
        obj = json.loads(resp.read().decode())
    if obj.get("code") != 0:
        raise RuntimeError(f"IMA note error [{obj.get('code', '')}]: {obj.get('msg', '')}")
    return obj.get("data", {})


def list_notebooks():
    """列出所有笔记本。返回 [{folder_id, name, note_number}]。"""
    items = []
    cursor = "0"
    while True:
        data = _req("list_notebook", {"cursor": cursor, "limit": 20})
        for nb in data.get("note_folder_infos", []):
            items.append({
                "id": nb.get("folder_id", ""),
                "name": nb.get("name", ""),
                "note_number": nb.get("note_number", 0),
            })
        if data.get("is_end", True):
            break
        cursor = data.get("next_cursor", "")
        time.sleep(_API_DELAY)
    return items


def list_notes(folder_id=""):
    """列出笔记。返回 [{note_id, title, summary, folder_name}]。"""
    items = []
    cursor = ""
    while True:
        data = _req("list_note", {"folder_id": folder_id, "cursor": cursor, "limit": 20})
        for nb in data.get("note_book_list", []):
            ext = nb.get("note_ext_info", {})
            items.append({
                "note_id": nb.get("note_id", ""),
                "title": nb.get("title", ""),
                "summary": nb.get("summary", ""),
                "folder_name": ext.get("folder_name", ""),
            })
        if data.get("is_end", True):
            break
        cursor = data.get("next_cursor", "")
        time.sleep(_API_DELAY)
    return items


def get_note_content(note_id):
    """获取笔记正文（纯文本格式）。"""
    data = _req("get_doc_content", {"note_id": note_id, "target_content_format": 0})
    return data.get("content", "")


def sync_all(store, verbose=True):
    """拉取所有笔记入库。"""
    results = []
    notebooks = list_notebooks()
    if verbose:
        print(f"IMA 笔记本: {len(notebooks)} 个")
    for nb in notebooks:
        notes = list_notes(nb["id"])
        ingested = 0
        for n in notes:
            cid = f"imanote:{n['note_id']}"
            if store.get_document(cid):
                continue
            content = get_note_content(n["note_id"])
            doc = CanonicalDoc(
                canonical_id=cid,
                title=n["title"],
                content=content,
                source="imanote",
                source_id=n["note_id"],
                origin="imanote",
            )
            store.store_document(doc)
            ingested += 1
            time.sleep(_API_DELAY)
        results.append({
            "folder": nb["name"],
            "note_number": nb["note_number"],
            "ingested": ingested,
        })
        if verbose:
            print(f"  {nb['name']}: {ingested}/{nb['note_number']} 篇")
    return results


def sync_cli(store, verbose=True):
    """与 sync_all 相同（供 CLI 调用）。"""
    return sync_all(store, verbose=verbose)
