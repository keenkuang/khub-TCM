"""双向同步引擎：拉取远端修改 + 推送本地修改到远端。"""
from .db import Store


class TwoWaySyncAdapter:
    """适配器接口：每个源（如 IMA KB、Quip）实现此接口用于双向同步。"""
    name: str = ""
    direction: str = "pull"  # pull / push / both

    def pull(self, store: Store) -> list:
        """拉取远端文档列表。每条记录是 dict，须含 source_id / content / title / hash。"""
        return []

    def push(self, store: Store, doc_id: str, content: str, title: str) -> str:
        """推送一篇文档到远端。返回远端的 source_id。"""
        raise NotImplementedError

    def delete(self, store: Store, source_id: str):
        """删除远端一篇文档。"""
        raise NotImplementedError


class TwoWaySyncEngine:
    def __init__(self, store: Store):
        self.store = store

    def sync_pull(self, source_name: str, items: list):
        """Phase 1: Pull — 把远端文档入库。
        items: [{source_id, title, content, hash}]"""
        from .models import CanonicalDoc
        ingested = 0
        for item in items:
            cid = item.get("source_id", "")
            if not cid:
                continue
            content = item.get("content", "")
            title = item.get("title", "")
            h = item.get("hash", "")
            doc = CanonicalDoc(
                canonical_id=cid, title=title, content=content,
                source=source_name, source_id=cid, origin=source_name,
                hash=h or "")
            self.store.store_document(doc)
            self.store.upsert_sync_state(source_name, cid, hash=h,
                                         direction="pull")
            ingested += 1
        return {"ingested": ingested}

    def sync_push(self, source_name: str, adapter: TwoWaySyncAdapter):
        """Phase 2: Push — 把 kHUB 本地改动推送到远端。"""
        pending = self.store.list_pending_push(source_name)
        pushed = 0
        for doc in pending:
            try:
                remote_id = adapter.push(
                    self.store, doc["canonical_id"],
                    doc["content"], doc["title"])
                self.store.upsert_sync_state(
                    source_name, doc["canonical_id"],
                    hash=doc["hash"], direction="push")
                pushed += 1
            except Exception as e:
                import warnings
                warnings.warn(f"push 失败 {doc['canonical_id']}: {e}")
        return {"pushed": pushed}

    def sync(self, source_name: str, adapter: TwoWaySyncAdapter,
             direction: str = "both"):
        """两阶段同步。"""
        result = {}
        if direction in ("pull", "both"):
            items = adapter.pull(self.store)
            result["pull"] = self.sync_pull(source_name, items)
        if direction in ("push", "both"):
            result["push"] = self.sync_push(source_name, adapter)
        return result
