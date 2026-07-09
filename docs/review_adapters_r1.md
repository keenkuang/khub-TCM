# 数据源扩展模块第 1 轮代码评审报告

**评审范围**：`khub/adapters/` 全部 4 个文件 + `khub/cli.py` 中 `feishu-sync` 子命令变更  
**Commit**: `ba7eac1` (branch `m1`)  
**评审日期**: 2026-07-09  
**评审人**: code-reviewer-6

---

## 严重度分级说明

| 级别 | 标签 | 含义 |
|------|------|------|
| **C3** | 必须修复 | 生产安全/数据正确性风险，上线前必须修复 |
| **C2** | 必须修复 | 功能正确性或可靠性缺陷，应在本迭代修复 |
| **C1** | 建议修复 | 按节奏安排修复，不阻塞上线 |
| **L1** | 仅供参考 | 代码风格/最佳实践，长期改进方向 |

---

<!-- markdownlint-disable MD029 -->

## 1. C3 — 必须修复（安全/数据正确性）

### 1.1 飞书同步 CLI 中每篇文档重复入库两次

**文件**: `khub/cli.py:326-343`  
**严重度**: C3 — 数据正确性

**问题**:

```python
raw_docs = adapter.pull()
for raw in raw_docs:
    canonical = adapter.normalize(raw)
    store.store_document(canonical)   # ← 第一次入库
    items.append({...})
result = engine.sync_pull("feishu", items)  # ← sync_pull 内部调用 store_document() 第二次入库
```

每篇文档在 `for` 循环中通过 `store.store_document(canonical)` 入库一次，随后 `engine.sync_pull()` 内部再次调用 `self.store.store_document(doc)` 入库第二次。

**后果**: 取决于 `store_document` 实现——如果是 `INSERT` 则产生重复文档；如果是 `UPSERT` 则浪费一倍 API 开销（`_fetch_doc_content` 已执行过的内容再次写入）。

**修复建议**: 二选一：

- **方案 A**（推荐）：去掉循环中的 `store.store_document`，只保留 `sync_pull` 的入库逻辑，利用 `sync_engine` 的已存在跳过机制（`get_document` 判重）。

- **方案 B**：去掉 `sync_pull` 调用，直接用循环入库，然后用 `rawdoc_to_sync_item()` 桥接函数上报同步状态。

### 1.2 Token 刷新无锁，非线程安全

**文件**: `khub/adapters/_feishu_auth.py:25-29`  
**严重度**: C3 — 并发安全

**问题**:

```python
@property
def token(self) -> str:
    if time.time() >= self._expires_at - 300:
        self._refresh()
    return self._token
```

无任何锁保护。当 `token` 在多个线程（或异步协程）中被并发访问且恰好在过期窗口内时：

1. 两个线程都可能进入 `_refresh()`，发起重复的 API 请求
2. 写 `self._token` / `self._expires_at` 存在数据竞争

**修复建议**：加 `threading.Lock`，或使用双重检查锁定模式：

```python
import threading

class FeishuTokenManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._token = ""
        self._expires_at = 0.0

    @property
    def token(self) -> str:
        if time.time() >= self._expires_at - 300:
            with self._lock:
                if time.time() >= self._expires_at - 300:  # 二次检查
                    self._refresh()
        return self._token
```

---

## 2. C2 — 必须修复（功能可靠性）

### 2.1 `_get` Token 过期重试无限制，可能无限递归

**文件**: `khub/adapters/feishu.py:61-65`  
**严重度**: C2

**问题**:

```python
except urllib.error.HTTPError as e:
    if e.code == 999914:  # token 过期
        self._auth._refresh()
        return self._get(path, params)  # ← 递归重试，无次数限制
```

如果 `_refresh()` 刷新后获取的新 token 也立即过期（时钟偏差、网络问题等），会导致无限递归，最终 Python 递归栈溢出。

**修复建议**: 加入最大重试次数：

```python
_MAX_RETRIES = 2

def _get(self, path: str, params: dict = None, _retry: int = _MAX_RETRIES) -> dict:
    ...
    except urllib.error.HTTPError as e:
        if e.code == 999914 and _retry > 0:
            self._auth._refresh()
            return self._get(path, params, _retry=_retry - 1)
        raise RuntimeError(f"Feishu HTTP {e.code}: {e.reason}")
```

### 2.2 `_get` 不处理网络级异常（`URLError`）

**文件**: `khub/adapters/feishu.py:58-66`  
**严重度**: C2

**问题**:

```python
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())
except urllib.error.HTTPError as e:
    if e.code == 999914:
        ...
    raise RuntimeError(...)
```

`urllib.error.URLError`（DNS 解析失败、连接被拒绝、超时）未捕获，会直接 propagete 到 `pull()` 调用方。

**后果**: 在知识空间遍历中途遇到网络闪断，整个 `pull()` 终止，已遍历的部分全部丢失。

**修复建议**: 捕获 `urllib.error.URLError`，根据上下文决定重试或包裹更友好的异常：

```python
except urllib.error.URLError as e:
    raise RuntimeError(f"Feishu API 网络错误: {e.reason}") from e
```

### 2.3 `_list_spaces` 未处理 API 分页不存在 `has_more` 的边界情况

**文件**: `khub/adapters/feishu.py:70-85`  
**严重度**: C2

**问题**: 飞书某些 API 在大结果集下可能返回 `has_more: true` 但 `page_token` 为空字符串。此时 `break` 条件永不满足，循环持续用空 `page_token` 请求同一页，导致死循环。

**修复建议**: 同时检查 `page_token` 非空：

```python
if not resp_data.get("has_more", False) or not resp_data.get("page_token", ""):
    break
```

### 2.4 `edit_time` 同时用作 `updated_at` 和 `etag`

**文件**: `khub/adapters/feishu.py:199-200`  
**严重度**: C2

**问题**:

```python
updated_at=node.get("edit_time", ""),
etag=node.get("edit_time", ""),
```

`etag` 用编辑时间字符串替代，精度可能只到秒。同秒内的两次编辑无法区分为不同版本。

**后果**: 增量同步时可能遗漏同秒内的更新。应使用 Feishu API 返回的 `version` 字段（如果存在）作为 `etag`。

### 2.5 `--space-id` 过滤发生在拉取全部空间之后

**文件**: `khub/adapters/feishu.py:170-172`  
**严重度**: C2 — 性能/效率

**问题**:

```python
spaces = self._list_spaces()
if self._space_id:
    spaces = [s for s in spaces if s.get("space_id") == self._space_id]
```

当用户指定 `--space-id` 时，仍然先调用 `_list_spaces()` 抓取所有可访问空间列表。对于有大量空间的租户，这是不必要的 API 调用和网络传输。

**修复建议**: 当 `self._space_id` 已设置时，跳过 `_list_spaces()`，直接用指定 space_id 遍历节点：

```python
if self._space_id:
    spaces = [{"space_id": self._space_id, "name": ""}]
else:
    spaces = self._list_spaces()
```

---

## 3. C1 — 建议修复

### 3.1 `_list_space_nodes` 与 `_list_node_children` 大量重复代码

**文件**: `khub/adapters/feishu.py:87-132`  
**严重度**: C1

两个方法仅在 API 路径和子节点调用上不同，分页逻辑、错误处理完全重复。可统一为：

```python
def _list_nodes(self, path: str) -> list[dict]:
    """通用分页节点遍历，返回 item 列表（不递归子节点）。"""
    items = []
    page_token = ""
    while True:
        params = {"page_size": "50"}
        if page_token:
            params["page_token"] = page_token
        data = self._get(path, params)
        resp_data = data.get("data", {})
        items.extend(resp_data.get("items", []))
        if not resp_data.get("has_more", False) or not resp_data.get("page_token", ""):
            break
        page_token = resp_data.get("page_token", "")
        time.sleep(0.3)
    return items
```

然后 `_list_space_nodes` 和 `_list_node_children` 只负责拼路径 + 递归遍历子节点。

### 3.2 `FeishuAdapter.normalize()` 是 `SourceAdapter.normalize()` 的完全重复

**文件**: `khub/adapters/feishu.py:219-233` vs `khub/adapters/base.py:43-62`  
**严重度**: C1

`FeishuAdapter.normalize()` 的 15 行实现与 `SourceAdapter.normalize()` 的默认实现完全一致（唯一的区别是硬编码 `"feishu"` 而非 `self.name`，但 `self.name = "feishu"` 所以结果相同）。

**修复建议**: 删除 `FeishuAdapter.normalize()` 覆盖，直接使用 Protocol 提供的默认实现。

### 3.3 `rawdoc_to_sync_item` 桥接函数定义了但未使用

**文件**: `khub/adapters/base.py:65-72`  
**严重度**: C1

`rawdoc_to_sync_item` 函数存在但 CLI 代码手动构造了 dict。应统一使用该函数。

### 3.4 硬编码 sleep 时间

**文件**: `khub/adapters/feishu.py:84, 106, 131, 209`  
**严重度**: C1

`time.sleep(0.3)` 和 `time.sleep(0.2)` 是硬编码魔数。应考虑：

- 提取为类常量 `_RATE_LIMIT_SLEEP = 0.3`
- 或通过构造函数参数可配置

### 3.5 `push` / `delete` 返回类型不匹配 Protocol 签名

**文件**: `khub/adapters/feishu.py:213, 216`  
**严重度**: C1

```python
def push(self, ...) -> "SyncResult":
    raise NotImplementedError(...)

def delete(self, ...) -> "SyncResult":
    raise NotImplementedError(...)
```

标注返回 `SyncResult` 但实际从不返回——方法体始终抛异常。静态类型检查器（mypy、pyright）会报错。建议：

- 变更为 `-> NoReturn`（或保持 `None`，因 `NotImplementedError` 继承自 `Exception`，类型系统会推断为 `NoReturn`）
- 或注释标注 `# pragma: no cover`

### 3.6 `_fetch_sheet_content` 异常处理捕获范围过宽

**文件**: `khub/adapters/feishu.py:160`  
**严重度**: C1

```python
except Exception as exc:
```

捕获所有异常，包括 `KeyboardInterrupt`、`SystemExit` 等，可能隐藏严重错误。应缩小到 `urllib.error.URLError` + `json.JSONDecodeError`。

### 3.7 `pull()` 方法无上下文管理器/资源清理

**文件**: `khub/adapters/feishu.py:166-211`  
**严重度**: C1

`pull()` 是入口方法，如果中途异常退出，没有任何回滚或清理逻辑（虽然当前实现无副作用，但未来若加入状态标记则可能留下不一致状态）。建议保持无状态设计，或加入文档级别的 try/finally。

---

## 4. L1 — 仅供参考

### 4.1 `Protocol` 与 `FeishuAdapter` 无显式继承关系

**文件**: `khub/adapters/base.py:14` / `feishu.py:29`  
**严重度**: L1

`FeishuAdapter` 不继承 `SourceAdapter`，依赖 Python Protocol 的结构子类型。这是有意为之的设计（docstring 已注明），但对于不熟悉 Protocol 的维护者可能造成困惑。

如果团队偏好显式契约，可以考虑 `FeishuAdapter(SourceAdapter)` 并使用 `abc.ABC` + `@abstractmethod`。当前 Protocol 方案在 MVP 阶段可接受。

### 4.2 `_list_spaces` 可能在非 wiki 场景下返回意外数据

**文件**: `khub/adapters/feishu.py:70`  
**严重度**: L1

当前 `/wiki/v2/spaces` 仅返回"知识空间"。如果未来扩展业务场景，建议在 API 路径前加上明确的作用域前缀。

### 4.3 所有文档的 `format` 被写死为 `"markdown"`

**文件**: `khub/adapters/feishu.py:198`  
**严重度**: L1

飞书文档的 raw_content 并非严格 Markdown（可能有自定义块级元素）。未来可能需要根据 `obj_type` 区分格式（如 `"feishu_doc"` / `"feishu_sheet"`）而非统称 `"markdown"`。

### 4.4 CLI 中 import 在函数体内延迟导入

**文件**: `khub/cli.py:326-327`  
**严重度**: L1

```python
from .adapters import create_adapter
from .sync_engine import TwoWaySyncEngine
```

这是合理的惰性导入模式（适配器模块可能依赖较大），但与其他子命令风格一致，无需修改。

---

## 5. 测试覆盖分析

模块当前零测试。以下为推荐的测试套件结构和可测试边界：

### 5.1 单元测试（可完全隔离）

| 测试目标 | 测试内容 | 模拟需求 |
|----------|----------|----------|
| `FeishuTokenManager` | 过期前自动刷新、并发安全 | 模拟 `urllib.request.urlopen` 返回 token JSON |
| `rawdoc_to_sync_item()` | 输入 RawDoc → 输出正确 dict | 纯函数，无需模拟 |
| `SourceAdapter.normalize()` | 默认实现正确填充 `canonical_id`、`source` 等 | 构造 `RawDoc` fixture 即可 |
| `create_adapter()` | 已知 type → 正确实例化；未知 type → `ValueError` | 无 |
| `_list_spaces` pagination | `has_more=true` 时继续请求、`has_more=false` 时停止 | 模拟 `_get` 返回不同分页响应 |
| `_list_nodes` pagination | 同上 | 同上 |
| `_get` error handling | 999914 触发 token 刷新后重试；非 999914 抛 `RuntimeError` | 模拟 `urlopen` 抛出 `HTTPError` |

### 5.2 集成测试（需真实 token 或录制响应）

| 测试目标 | 测试内容 |
|----------|----------|
| `FeishuAdapter.pull()` | 对指定 space_id 实际拉取并断言返回 `RawDoc` 列表 |
| CLI `feishu-sync --space-id X` | 端到端验证入库流程 |
| 增量同步 | 同一 space 第二次 `pull()` 应跳过未变更文档 |

### 5.3 推荐测试文件名

- `tests/test_adapter_base.py` — Protocol 默认实现、`rawdoc_to_sync_item`、factory
- `tests/test_feishu_auth.py` — `FeishuTokenManager` 单元测试
- `tests/test_feishu_adapter.py` — `FeishuAdapter` 各方法单元测试（mock `_get`）
- `tests/test_feishu_integration.py` — 端到端测试（`pytest.mark.slow`，需要飞书凭据）

---

## 6. 汇总

| 级别 | 数量 | 关键项 |
|------|------|--------|
| C3 | 2 | 双重复入库、Token 刷新线程安全 |
| C2 | 5 | Token 重试无限制、URLError 传递、分页死循环边界、etag 精度不足、space_id 过滤时机 |
| C1 | 8 | 重复代码（2处）、未使用函数、硬编码 sleep、返回类型、异常捕获过宽、无资源清理 |
| L1 | 4 | Protocol 设计、format 硬编码、导入时机 |

**最优先修复**: C3#1（双重复入库）——直接影响数据正确性，在真实的飞书同步之前必须修复。
