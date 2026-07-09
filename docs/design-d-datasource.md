# 数据源扩展设计规格

> 作者：designer-d
> 日期：2026-07-09
> 项目：khub (个人知识中枢)

---

## 目录

1. [现有架构分析](#1-现有架构分析)
2. [统一适配器接口](#2-统一适配器接口)
3. [飞书文档适配器](#3-飞书文档适配器)
4. [适配器注册与 CLI 集成](#4-适配器注册与-cli-集成)
5. [实现计划](#5-实现计划)
6. [未来扩展](#6-未来扩展)

---

## 1. 现有架构分析

### 1.1 当前数据源接入方式对比

| 维度 | Quip (`quip.py`) | Obsidian (`obsidian.py`) | IMA (`ima.py`) |
|---|---|---|---|
| 接口风格 | 模块自由函数 | 模块自由函数 | 自由函数 + `sync_adapter()` 工厂 |
| 返回类型 | `(ingested, skipped)` 元组 | `(ingested, skipped)` 元组 | `dict{ingested, skipped}` |
| 入库方式 | 函数内直接 `store.store_document()` | 函数内直接 `store.store_document()` | 函数内直接入库，或通过 `TwoWaySyncAdapter` 间接入库 |
| 使用 TwoWaySyncAdapter | 否 | 否 | 是（`sync_adapter()` 返回动态适配器） |
| API 依赖 | `urllib` | 无（本地文件） | `urllib` |
| CLI 入口 | `khub quip-sync` | `khub obsidian-import` | `khub ima-sync` |

### 1.2 关键已存在类型

`models.py` 中已有三个可以直接复用的数据类：

- **`RawDoc`** — 源文档原始表示（`id`, `title`, `content`, `format`, `updated_at`, `etag`, `attachments`, `metadata`）
- **`CanonicalDoc`** — 归一化文档，直接入库（`canonical_id`, `title`, `content`, `source`, `source_id`, `origin`, `format`, `hash`, ...）
- **`SyncResult`** — 推送/删除结果（`status`, `doc_id`, `version_id`, `message`）

### 1.3 当前 `TwoWaySyncAdapter` 接口

```python
class TwoWaySyncAdapter:
    name: str = ""
    direction: str = "pull"  # pull / push / both

    def pull(self, store: Store) -> list:      # → [{source_id, title, content, hash}]
    def push(self, store, doc_id, content, title) -> str:  # → remote source_id
    def delete(self, store, source_id):         # → None
```

特点：pull 返回 `list[dict]`（无类型约束），push/delete 均接收 `store` 参数。此接口混合了"数据传输"和"存储写入"，不够正交。

---

## 2. 统一适配器接口

### 2.1 设计目标

- **向后兼容**：现有 Quip/Obsidian 模块不做接口迁移，保持独立运行路径
- **新适配器统一**：所有新数据源（飞书、语雀等）实现 `SourceAdapter` 协议
- **TwoWaySyncAdapter 继承**：保留 `TwoWaySyncAdapter` 作为 `SourceAdapter` 子类，现有 `sync_engine.py` 不受影响
- **最少接口原则**：只定义必需的契约方法，不提前抽象未来可能需要的功能

### 2.2 `SourceAdapter` 协议

新建 `khub/adapters/base.py`：

```python
# khub/adapters/base.py
"""数据源适配器基础接口。"""

from dataclasses import dataclass
from typing import Optional, Protocol
from ..models import RawDoc, CanonicalDoc, SyncResult


class SourceAdapter(Protocol):
    """数据源适配器协议。
    
    每个远端数据源（飞书、语雀、Confluence 等）实现此协议。
    注意：这是 Protocol（结构子类型），不强制继承，满足接口即可。
    """

    # 适配器名称标识，如 "feishu", "yuque"；用作 source 字段写入文档
    name: str

    # 支持的同步方向：pull / push / both
    direction: str = "pull"

    def pull(self) -> list[RawDoc]:
        """从远端拉取所有文档（含增量）。
        
        Returns:
            RawDoc 列表。注意：此方法只负责数据获取，不负责入库。
            入库由调用方（SourceEngine / CLI）统一处理。
        """
        ...

    def push(self, doc_id: str, content: str, title: str) -> SyncResult:
        """推送一篇文档到远端。
        
        Args:
            doc_id: 本地 canonical_id。
            content: 文档内容（markdown）。
            title: 文档标题。
        
        Returns:
            SyncResult，其中 doc_id 为远端服务侧 ID。
        """
        ...

    def delete(self, source_id: str) -> SyncResult:
        """删除远端一篇文档。
        
        Args:
            source_id: 远端服务侧文档 ID。
        """
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
```

### 2.3 `TwoWaySyncAdapter` 的兼容策略

保持 `sync_engine.py` 中的 `TwoWaySyncAdapter` 不变。新增的 `SourceAdapter` 与其关系：

```
SourceAdapter (Protocol)
    ↑ 结构子类型（不需要显式继承）
    │
TwoWaySyncAdapter (class in sync_engine.py，保持不变)
    ↑ 只需要 pull 返回类型对齐
```

对齐方式：在 `khub/adapters/base.py` 中添加一个桥接函数，供现有代码使用：

```python
def rawdoc_to_sync_item(raw: RawDoc) -> dict:
    """将 RawDoc 转为 TwoWaySyncAdapter.pull() 期望的 dict 格式。"""
    return {
        "source_id": f"{raw.id}",
        "title": raw.title,
        "content": raw.content,
        "hash": raw.etag,
    }
```

**不需要** 将现有 Quip/Obsidian 迁移到 `SourceAdapter` 接口。它们保持独立函数形式，通过 CLI 直接调用。新适配器全部走 `SourceAdapter` 协议。

### 2.4 数据流

```
远端 API
   ↓ pull()
RawDoc[]
   ↓ normalize()        ← 每个适配器提供
CanonicalDoc[]
   ↓ store.store_document()
入库完成
```

```
本地修改
   ↓ sync_push() 查找差异
CanonicalDoc
   ↓ adapter.push()     ← 适配器负责序列化
远端 API 调用
   ↓
SyncResult
```

---

## 3. 飞书文档适配器

### 3.1 飞书开放平台 API 概览

飞书文档 API 使用 OAuth 2.0 客户端凭证模式（tenant_access_token），需要：

1. 在[飞书开放平台](https://open.feishu.cn)创建应用，获取 `app_id` / `app_secret`
2. 开通"文档"、"知识空间"、"电子表格"等权限
3. 发布应用后，获取 `tenant_access_token`（有效期 2 小时）

### 3.2 认证模块

```python
# khub/adapters/_feishu_auth.py（内部模块，不对外暴露）

import os
import time
import json
import urllib.request

_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"


class FeishuTokenManager:
    """管理飞书 tenant_access_token 的获取与缓存。
    
    策略：
    - token 缓存到内存，过期前 5 分钟自动刷新
    - 首次获取若无 env，使用 app_id/app_secret 请求
    """
    
    def __init__(self):
        self._token = ""
        self._expires_at = 0.0
    
    @property
    def token(self) -> str:
        if time.time() >= self._expires_at - 300:
            self._refresh()
        return self._token
    
    def _refresh(self):
        app_id = os.environ.get("FEISHU_APP_ID", "")
        app_secret = os.environ.get("FEISHU_APP_SECRET", "")
        if not app_id or not app_secret:
            raise RuntimeError("需要设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET 环境变量")
        
        body = json.dumps({
            "app_id": app_id,
            "app_secret": app_secret,
        }).encode()
        req = urllib.request.Request(
            _TOKEN_URL, data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        
        self._token = data.get("tenant_access_token", "")
        expire_sec = data.get("expire", 7200)
        self._expires_at = time.time() + expire_sec
```

### 3.3 `FeishuAdapter` 实现

```python
# khub/adapters/feishu.py

import json
import time
import urllib.request
import warnings

from ..models import RawDoc
from .base import SourceAdapter
from ._feishu_auth import FeishuTokenManager


API_BASE = "https://open.feishu.cn/open-apis"


class FeishuAdapter:
    """飞书文档适配器：从知识空间拉取文档。
    
    配置方式（环境变量）：
    - FEISHU_APP_ID
    - FEISHU_APP_SECRET
    - FEISHU_SPACE_ID（可选，指定知识空间 ID；不指定则遍历所有可访问空间）
    
    name = "feishu"
    direction = "pull"  # MVP 阶段只读
    """
    
    name = "feishu"
    direction = "pull"
    
    def __init__(self, space_id: str = ""):
        self._auth = FeishuTokenManager()
        self._space_id = space_id  # 可选，指定单个知识空间
    
    # ── header 工具 ────────────────────────────────────────────────────
    
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._auth.token}",
            "Content-Type": "application/json; charset=utf-8",
        }
    
    def _get(self, path: str, params: dict = None) -> dict:
        """GET 请求 + 自动重试（5 秒退避）。"""
        url = f"{API_BASE}{path}"
        if params:
            qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
            url = f"{url}?{qs}"
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 999914:  # token 过期
                warnings.warn("Feishu token 过期，刷新后重试")
                self._auth._refresh()  # 强制刷新
                return self._get(path, params)
            raise RuntimeError(f"Feishu HTTP {e.code}: {e.reason}")
    
    def _post(self, path: str, body: dict) -> dict:
        """POST 请求。"""
        url = f"{API_BASE}{path}"
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Feishu HTTP {e.code}: {e.reason}")
    
    # ── 知识空间遍历 ────────────────────────────────────────────────────
    
    def _list_spaces(self) -> list[dict]:
        """列出当前应用可访问的知识空间。"""
        # GET /open-apis/wiki/v2/spaces?page_size=50
        items = []
        page_token = ""
        while True:
            params = {"page_size": "50"}
            if page_token:
                params["page_token"] = page_token
            data = self._get("/wiki/v2/spaces", params)
            resp_data = data.get("data", {})
            items.extend(resp_data.get("items", []))
            if not resp_data.get("has_more", False):
                break
            page_token = resp_data.get("page_token", "")
            time.sleep(0.3)
        return items
    
    def _list_space_nodes(self, space_id: str) -> list[dict]:
        """递归遍历知识空间中的 wiki 节点（文档）。"""
        # GET /open-apis/wiki/v2/spaces/{space_id}/nodes?page_size=50
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
                # 如果有子节点，递归
                if item.get("has_child", False):
                    children = self._list_node_children(space_id, item["node_token"])
                    nodes.extend(children)
            if not resp_data.get("has_more", False):
                break
            page_token = resp_data.get("page_token", "")
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
            if not resp_data.get("has_more", False):
                break
            page_token = resp_data.get("page_token", "")
            time.sleep(0.3)
        return children
    
    # ── 文档内容拉取 ────────────────────────────────────────────────────
    
    def _fetch_doc_content(self, doc_token: str) -> str:
        """拉取飞书文档内容并转为 Markdown。
        
        使用飞书文档 V2 API：
        GET /open-apis/docx/v1/documents/{doc_token}/raw_content
        → 返回 blocks 结构，由 _blocks_to_markdown 转换。
        """
        data = self._get(f"/docx/v1/documents/{doc_token}/raw_content")
        content = data.get("data", {}).get("content", "")
        return content
    
    def _fetch_sheet_content(self, sheet_token: str) -> str:
        """拉取电子表格内容（简化为 CSV 格式嵌入）。"""
        # GET /open-apis/sheets/v3/spreadsheets/{sheet_token}/sheets/query
        try:
            data = self._get(f"/sheets/v3/spreadsheets/{sheet_token}/sheets/query")
            sheets = data.get("data", {}).get("sheets", [])
            lines = []
            for sheet in sheets:
                sheet_id = sheet.get("sheet_id", "")
                title = sheet.get("title", "")
                lines.append(f"## 表格: {title}")
                # 取前 100 行
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
        
        # 如果指定了 space_id，只处理该空间
        if self._space_id:
            spaces = [s for s in spaces if s.get("space_id") == self._space_id]
        
        for space in spaces:
            sid = space.get("space_id", "")
            space_name = space.get("name", "")
            nodes = self._list_space_nodes(sid)
            for node in nodes:
                obj_type = node.get("obj_type", "")  # doc / sheet / wiki
                node_token = node.get("node_token", "")
                title = node.get("title", "")
                if not node_token:
                    continue
                
                if obj_type == "doc" or obj_type == "wiki":
                    content = self._fetch_doc_content(node_token)
                elif obj_type == "sheet":
                    content = self._fetch_sheet_content(node_token)
                elif obj_type == "file":
                    # 飞书云空间中的文件（非文档），跳过
                    continue
                else:
                    content = f"[不支持的飞书节点类型: {obj_type}]"
                
                doc = RawDoc(
                    id=f"{sid}/{node_token}",
                    title=title,
                    content=content,
                    format="markdown",
                    updated_at=node.get("edit_time", ""),
                    etag=node.get("edit_time", ""),  # 用编辑时间作为 etag
                    metadata={
                        "space_id": sid,
                        "space_name": space_name,
                        "node_token": node_token,
                        "obj_type": obj_type,
                    },
                )
                docs.append(doc)
                time.sleep(0.2)  # 频率控制
        
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
```

### 3.4 内容格式转换注意事项

飞书文档 V2 API 的 `raw_content` 返回的是纯文本（已去格式）。这是 MVP 阶段可以接受的做法——内容可检索，但丢失了标题层级、列表、表格等富文本结构。

**后续优化方向**（不在 MVP 范围内）：
- 使用 `GET /docx/v1/documents/{doc_token}/blocks` 拉取块级结构
- 自行实现块结构 → Markdown 转换器（处理 heading / bullet / code_block / table / image 等块类型）

### 3.5 CLI 命令

```bash
# 完整命令
khub feishu-sync [--space-id <space_id>]

# 也可以从环境变量 FEISHU_SPACE_ID 读取
FEISHU_SPACE_ID=xxx khub feishu-sync
```

### 3.6 config.yaml 配置段

```yaml
# ~/.khub/tasks.yaml
tasks:
  - name: feishu-docs
    interval: 3600   # 每小时同步一次
    command: khub feishu-sync --space-id xxx_xxx
  
  - name: feishu-docs-all
    interval: 86400  # 每天同步一次所有空间
    command: khub feishu-sync
```

### 3.7 认证凭据配置

只在环境变量中配置（不写入 config.yaml，避免泄露）：

```bash
export FEISHU_APP_ID=cli_xxxxxxxxxxxx
export FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## 4. 适配器注册与 CLI 集成

### 4.1 适配器工厂

新建 `khub/adapters/__init__.py`，提供适配器工厂函数：

```python
# khub/adapters/__init__.py
"""适配器工厂：按 type 名懒加载适配器实例。"""

_ADAPTER_REGISTRY: dict[str, str] = {
    # type_name → 模块路径（惰性导入用）
    "feishu": "khub.adapters.feishu",
    # "yuque": "khub.adapters.yuque",      # future
    # "confluence": "khub.adapters.confluence",  # future
}


def list_adapters() -> list[str]:
    """返回所有注册的适配器名称。"""
    return list(_ADAPTER_REGISTRY.keys())


def create_adapter(source_type: str, **kwargs) -> "SourceAdapter":
    """按 type 名创建适配器实例。
    
    惰性导入：只在首次使用时加载对应模块。
    
    Args:
        source_type: 适配器名称，如 "feishu"。
        **kwargs: 透传给适配器构造函数的参数。
    
    Returns:
        SourceAdapter 实例。
    
    Raises:
        ValueError: 未知的 source_type。
    """
    if source_type not in _ADAPTER_REGISTRY:
        raise ValueError(
            f"未知数据源类型：{source_type}。"
            f"已注册：{', '.join(list_adapters())}"
        )
    
    import importlib
    mod_path = _ADAPTER_REGISTRY[source_type]
    mod = importlib.import_module(mod_path)
    
    # 约定：适配器类名为 {Type}Adapter，如 FeishuAdapter
    cls_name = f"{source_type.capitalize()}Adapter"
    cls = getattr(mod, cls_name, None)
    if cls is None:
        # 兜底尝试最后一个单词大写 + Adapter
        parts = source_type.split("_")
        cls_name = "".join(p.capitalize() for p in parts) + "Adapter"
        cls = getattr(mod, cls_name, None)
    
    if cls is None:
        raise ValueError(f"模块 {mod_path} 中未找到适配器类")
    
    return cls(**kwargs)
```

### 4.2 CLI 集成

在 `cli.py` 中添加两个新子命令：

```python
# 在 build_parser() 中添加

p_feishu = sub.add_parser("feishu-sync", help="从飞书知识空间拉取文档到本地库")
p_feishu.add_argument("--space-id", default="",
                      help="指定知识空间 ID（不指定则遍历所有可访问空间）")
```

```python
# 在 main() 的 if-elif 链中添加

elif args.cmd == "feishu-sync":
    from .adapters import create_adapter
    from .sync_engine import TwoWaySyncEngine
    
    adapter = create_adapter("feishu", space_id=args.space_id)
    raw_docs = adapter.pull()
    engine = TwoWaySyncEngine(store)
    items = []
    for raw in raw_docs:
        canonical = adapter.normalize(raw)
        store.store_document(canonical)
        items.append({
            "source_id": canonical.canonical_id,
            "title": canonical.title,
            "content": canonical.content,
            "hash": canonical.hash,
        })
    result = engine.sync_pull("feishu", items)
    print(f"飞书同步完成：入库 {result['ingested']} 篇")
```

注意：这里没有直接调用 `engine.sync()`，因为 FeishuAdapter 的 pull() 返回 `RawDoc[]` 而非 `TwoWaySyncAdapter.pull()` 要求的 `list[dict]` 格式。需要做一次适配转换（`normalize` + 格式化）。

可以后续为 `SourceEngine`（与 `TwoWaySyncEngine` 对齐但接受 `SourceAdapter`）单独抽取逻辑，但不作为 MVP。

### 4.3 与 scheduler 的集成

scheduler 通过子进程执行 CLI 命令 (`subprocess.run("khub feishu-sync ...")`)，现有的 `_run_cmd` 机制已经足够。不需要修改 scheduler.py。

用户只需在 `tasks.yaml` 中配置：

```yaml
tasks:
  - name: feishu-sync
    interval: 3600
    command: /path/to/khub feishu-sync
```

---

## 5. 实现计划

### 5.1 第一步：基础接口层重构

**目标**：建立 `adapters/` 包和 `SourceAdapter` 协议，不影响现有代码。

| 操作 | 文件 | 说明 |
|---|---|---|
| 新建 | `khub/adapters/__init__.py` | 适配器工厂 + 注册表（~35 行） |
| 新建 | `khub/adapters/base.py` | `SourceAdapter` Protocol + 工具函数（~60 行） |

**代码量**：约 95 行，零依赖变更。

**验证**：
```bash
python -c "from khub.adapters import list_adapters; print(list_adapters())"
# 输出：[]（尚无注册的适配器）
```

### 5.2 第二步：飞书适配器 MVP

**目标**：实现飞书知识空间文档的只读拉取。

| 操作 | 文件 | 说明 |
|---|---|---|
| 新建 | `khub/adapters/_feishu_auth.py` | Token 管理（~50 行） |
| 新建 | `khub/adapters/feishu.py` | FeishuAdapter 实现（~230 行） |
| 修改 | `khub/adapters/__init__.py` | 注册 `"feishu"` 适配器（+1 行） |
| 修改 | `khub/cli.py` | 添加 `feishu-sync` 子命令（~25 行） |
| 新建 | `khub/adapters/__init__.py` | 已有（前面创建），此处注册 |

**代码量**：约 306 行；零新增 pip 依赖（stdlib only）。

**依赖 API**：
- `urllib.request` / `urllib.error` / `urllib.parse`（stdlib）
- `json` / `os` / `time` / `warnings`（stdlib）

**验证**：
```bash
# 需要先设置环境变量
export FEISHU_APP_ID=xxx
export FEISHU_APP_SECRET=xxx
khub feishu-sync --space-id xxx
```

### 5.3 第三步：后续适配器（预留设计）

#### 语雀适配器 (future)

```python
# khub/adapters/yuque.py
class YuqueAdapter:
    name = "yuque"
    direction = "pull"
    
    def __init__(self, repo_id: str = ""):
        self._token = os.environ.get("YUQUE_TOKEN", "")
        # 语雀 API：GET https://www.yuque.com/api/v2/repos/{repo}/docs
        # 认证：X-Auth-Token header
    
    def pull(self) -> list[RawDoc]: ...
    def push(self, doc_id, content, title) -> SyncResult: ...
    def delete(self, source_id) -> SyncResult: ...
    def normalize(self, raw) -> CanonicalDoc: ...
```

#### Confluence 适配器 (future)

```python
# khub/adapters/confluence.py
class ConfluenceAdapter:
    name = "confluence"
    direction = "pull"
    
    def __init__(self, space_key: str = ""):
        # Confluence REST API 使用 Basic Auth 或 Personal Access Token
        # GET /rest/api/content?spaceKey={key}&expand=body.storage
        pass
```

**注册方式**：只需在 `_ADAPTER_REGISTRY` 中添加一行，CLI 同理。

---

## 6. 设计决策记录

### 6.1 为什么不是 TwoWaySyncAdapter 的下推

当前 `TwoWaySyncAdapter` 的 pull() 接收 `store` 参数并在方法内完成入库，这与"适配器只负责传输，不负责存储"的原则不符。新设计的 `SourceAdapter` 将数据获取与存储解耦。

但现有模块（Quip/Obsidian/IMA）已经深度依赖 `store` 参数，迁移代价高且无实际收益，故保留不动。**仅新适配器使用 SourceAdapter 协议**。

### 6.2 为什么 pull() 不接收 store

- 适配器应只关注"如何从远端获取数据"，不关心"数据存到哪里"
- 入库逻辑统一由 CLI/main 处理，避免每个适配器重复实现去重、索引等
- 便于测试：pull() 可以直接在 mock 环境中调用，不需要构造 Store

### 6.3 为什么使用 Protocol 而非 ABC

- Protocol 允许鸭子类型：只要对象实现了 `pull() / push() / delete() / normalize()`，它就是 `SourceAdapter`，不需要显式继承
- 减少 import 依赖：适配器文件可以不 import base.py
- 向后兼容：`TwoWaySyncAdapter` 可以在不修改的情况下满足 Protocol（只需注意返回类型）

### 6.4 频率控制策略

飞书 API 有频率限制（基础版 100 次/分钟）。采取以下措施：
- 每次请求间隔 200-300ms（见代码中的 `time.sleep(0.2)`）
- HTTP 429 时退避重试（当前 5 秒）
- token 过期自动刷新重试
- 后续可增加可配置的 API 延迟参数

---

## 附录：飞书 API 参考

| 用途 | 端点 | 方法 |
|---|---|---|
| 获取 tenant_access_token | `/open-apis/auth/v3/tenant_access_token/internal` | POST |
| 列出知识空间 | `/open-apis/wiki/v2/spaces` | GET |
| 获取空间节点列表 | `/open-apis/wiki/v2/spaces/{space_id}/nodes` | GET |
| 获取子节点 | `/open-apis/wiki/v2/spaces/{space_id}/nodes/{node_token}/children` | GET |
| 获取文档纯文本 | `/open-apis/docx/v1/documents/{doc_token}/raw_content` | GET |
| 获取文档块结构 | `/open-apis/docx/v1/documents/{doc_token}/blocks` | GET |
| 查询表格 | `/open-apis/sheets/v3/spreadsheets/{sheet_token}/sheets/query` | GET |
| 读取表格范围 | `/open-apis/sheets/v3/spreadsheets/{sheet_token}/values/{range}` | GET |

权限需求（飞书开放平台应用配置）：
- `wiki:wiki:readonly` — 知识空间只读
- `docx:document:readonly` — 文档只读
- `sheets:spreadsheet:readonly` — 电子表格只读
