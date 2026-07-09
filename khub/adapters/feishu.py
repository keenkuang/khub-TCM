"""飞书文档适配器：从知识空间拉取文档到本地库。

配置方式（环境变量）：
- FEISHU_APP_ID
- FEISHU_APP_SECRET
- FEISHU_SPACE_ID（可选，指定知识空间 ID；不指定则遍历所有可访问空间）

name = "feishu"
direction = "pull"  # MVP 阶段只读
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings

from ..models import RawDoc
from .base import SourceAdapter
from ._feishu_auth import FeishuTokenManager

API_BASE = "https://open.feishu.cn/open-apis"


class FeishuAdapter:
    """飞书文档适配器：从知识空间拉取文档。

    name = "feishu"
    direction = "pull"  # MVP 阶段只读
    """

    name = "feishu"
    direction = "pull"

    def __init__(self, space_id: str = ""):
        self._auth = FeishuTokenManager()
        self._space_id = space_id or os.environ.get("FEISHU_SPACE_ID", "")

    # ── header 工具 ────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._auth.token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _get(self, path: str, params: dict = None, _retry: int = 1) -> dict:
        """GET 请求 + 自动重试（token 过期时刷新，最多 _retry 次）。"""
        url = f"{API_BASE}{path}"
        if params:
            qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
            url = f"{url}?{qs}"
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 999914 and _retry > 0:
                warnings.warn("Feishu token 过期，刷新后重试")
                try:
                    self._auth._refresh()  # 强制刷新
                except RuntimeError as refresh_err:
                    raise RuntimeError(
                        f"Feishu token 刷新失败: {refresh_err}") from refresh_err
                return self._get(path, params, _retry - 1)
            raise RuntimeError(f"Feishu HTTP {e.code}: {e.reason}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Feishu 请求失败: {e.reason}") from e

    # ── 知识空间遍历 ────────────────────────────────────────────────────

    def _list_spaces(self) -> list[dict]:
        """列出当前应用可访问的知识空间。"""
        items = []
        page_token = ""
        while True:
            params = {"page_size": "50"}
            if page_token:
                params["page_token"] = page_token
            data = self._get("/wiki/v2/spaces", params)
            resp_data = data.get("data", {})
            items.extend(resp_data.get("items", []))
            next_token = resp_data.get("page_token", "")
            if not resp_data.get("has_more", False) or not next_token:
                break
            page_token = next_token
            time.sleep(0.3)
        return items

    def _list_space_nodes(self, space_id: str) -> list[dict]:
        """递归遍历知识空间中的 wiki 节点（文档）。"""
        nodes = []
        page_token = ""
        while True:
            params = {"page_size": "50"}
            if page_token:
                params["page_token"] = page_token
            data = self._get(f"/wiki/v2/spaces/{space_id}/nodes", params)
            resp_data = data.get("data", {})
            items = resp_data.get("items", [])
            for item in items:
                nodes.append(item)
                if item.get("has_child", False):
                    children = self._list_node_children(space_id, item["node_token"])
                    nodes.extend(children)
            next_token = resp_data.get("page_token", "")
            if not resp_data.get("has_more", False) or not next_token:
                break
            page_token = next_token
            time.sleep(0.3)
        return nodes

    def _list_node_children(self, space_id: str, node_token: str) -> list[dict]:
        """递归获取子节点。"""
        children = []
        page_token = ""
        while True:
            params = {"page_size": "50"}
            if page_token:
                params["page_token"] = page_token
            data = self._get(
                f"/wiki/v2/spaces/{space_id}/nodes/{node_token}/children",
                params,
            )
            resp_data = data.get("data", {})
            items = resp_data.get("items", [])
            for item in items:
                children.append(item)
                if item.get("has_child", False):
                    sub = self._list_node_children(space_id, item["node_token"])
                    children.extend(sub)
            next_token = resp_data.get("page_token", "")
            if not resp_data.get("has_more", False) or not next_token:
                break
            page_token = resp_data.get("page_token", "")
            time.sleep(0.3)
        return children

    # ── 文档内容拉取 ────────────────────────────────────────────────────

    def _fetch_doc_content(self, doc_token: str) -> str:
        """拉取飞书文档内容并转为纯文本（MVP 阶段使用 raw_content API）。"""
        data = self._get(f"/docx/v1/documents/{doc_token}/raw_content")
        return data.get("data", {}).get("content", "")

    def _fetch_sheet_content(self, sheet_token: str) -> str:
        """拉取电子表格内容（简化为 CSV 格式嵌入）。"""
        try:
            data = self._get(f"/sheets/v3/spreadsheets/{sheet_token}/sheets/query")
            sheets = data.get("data", {}).get("sheets", [])
            lines = []
            for sheet in sheets:
                sheet_id = sheet.get("sheet_id", "")
                title = sheet.get("title", "")
                lines.append(f"## 表格: {title}")
                cell_data = self._get(
                    f"/sheets/v3/spreadsheets/{sheet_token}/values/"
                    f"{sheet_id}!A1:Z100"
                )
                values = cell_data.get("data", {}).get("value_range", {}).get("values", [])
                for row in values:
                    lines.append("| " + " | ".join(str(c) for c in row) + " |")
                lines.append("")
            return "\n".join(lines)
        except Exception as exc:
            warnings.warn(f"Feishu 表格 {sheet_token} 拉取失败: {exc}")
            return f"[表格 {sheet_token}：内容拉取失败]"

    # ── SourceAdapter 接口 ──────────────────────────────────────────────

    def pull(self) -> list[RawDoc]:
        """遍历知识空间并返回 RawDoc 列表。"""
        docs = []
        spaces = self._list_spaces()

        if self._space_id:
            spaces = [s for s in spaces if s.get("space_id") == self._space_id]

        for space in spaces:
            sid = space.get("space_id", "")
            space_name = space.get("name", "")
            nodes = self._list_space_nodes(sid)
            for node in nodes:
                obj_type = node.get("obj_type", "")
                node_token = node.get("node_token", "")
                title = node.get("title", "")
                if not node_token:
                    continue

                if obj_type in ("doc", "wiki"):
                    content = self._fetch_doc_content(node_token)
                elif obj_type == "sheet":
                    content = self._fetch_sheet_content(node_token)
                elif obj_type == "file":
                    continue
                else:
                    content = f"[不支持的飞书节点类型: {obj_type}]"

                doc = RawDoc(
                    id=f"{sid}/{node_token}",
                    title=title,
                    content=content,
                    format="markdown",
                    updated_at=node.get("edit_time", ""),
                    etag=node.get("edit_time", ""),
                    metadata={
                        "space_id": sid,
                        "space_name": space_name,
                        "node_token": node_token,
                        "obj_type": obj_type,
                    },
                )
                docs.append(doc)
                time.sleep(0.2)

        return docs

    def push(self, doc_id: str, content: str, title: str) -> "SyncResult":
        raise NotImplementedError("飞书适配器 MVP 阶段不支持推送")

    def delete(self, source_id: str) -> "SyncResult":
        raise NotImplementedError("飞书适配器 MVP 阶段不支持删除")

    def normalize(self, raw: RawDoc) -> "CanonicalDoc":
        from ..models import CanonicalDoc
        return CanonicalDoc(
            canonical_id=f"feishu:{raw.id}",
            title=raw.title,
            content=raw.content,
            source="feishu",
            source_id=raw.id,
            origin="feishu",
            format="markdown",
            updated_at=raw.updated_at,
            hash=raw.etag,
            attachments=raw.attachments,
            note=str(raw.metadata) if raw.metadata else "",
        )
