"""数据源适配器基础接口。

`SourceAdapter` Protocol：每个远端数据源（飞书、语雀等）实现此协议。
注意：这是 Protocol（结构子类型），不强制继承，满足接口即可。
"""

from __future__ import annotations

from typing import Optional, Protocol

from ..models import RawDoc, CanonicalDoc, SyncResult


class SourceAdapter(Protocol):
    """数据源适配器协议。

    每个远端数据源（飞书、语雀、Confluence 等）实现此协议。
    """

    # 适配器名称标识，如 "feishu", "yuque"；用作 source 字段写入文档
    name: str

    # 支持的同步方向：pull / push / both
    direction: str = "pull"

    def pull(self) -> list[RawDoc]:
        """从远端拉取所有文档（含增量）。

        Returns:
            RawDoc 列表。注意：此方法只负责数据获取，不负责入库。
            入库由调用方（CLI/main）统一处理。
        """
        ...

    def push(self, doc_id: str, content: str, title: str) -> SyncResult:
        """推送一篇文档到远端。"""
        ...

    def delete(self, source_id: str) -> SyncResult:
        """删除远端一篇文档。"""
        ...

    def normalize(self, raw: RawDoc) -> CanonicalDoc:
        """将 RawDoc 转换为 CanonicalDoc（准备入库）。

        默认实现填充 canonical_id = {name}:{raw.id}，
        source = name, source_id = raw.id, origin = name。
        子类可按需重写。
        """
        return CanonicalDoc(
            canonical_id=f"{self.name}:{raw.id}",
            title=raw.title,
            content=raw.content,
            source=self.name,
            source_id=raw.id,
            origin=self.name,
            format=raw.format,
            updated_at=raw.updated_at,
            hash=raw.etag,
            attachments=raw.attachments,
            note=str(raw.metadata) if raw.metadata else "",
        )


def rawdoc_to_sync_item(raw: RawDoc) -> dict:
    """将 RawDoc 转为 TwoWaySyncAdapter.pull() 期望的 dict 格式。"""
    return {
        "source_id": f"{raw.id}",
        "title": raw.title,
        "content": raw.content,
        "hash": raw.etag,
    }
