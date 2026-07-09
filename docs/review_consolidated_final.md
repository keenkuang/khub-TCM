# ACD 三模块综合最终评审报告

> 评审日期：2026-07-10
> 评审范围：A (RAG) `2114b35` · C (WebUI) `1611d79` · D (数据源) `39ad6fd` — branch `m1`
> 基准：3 轮逐模块审核已覆盖的 7 份审查报告 + 最终交叉分析

---

## 目录

1. [关键发现（阻止合入）](#1-关键发现阻止合入)
2. [跨模块交叉问题](#2-跨模块交叉问题)
3. [各模块遗留可修复项](#3-各模块遗留可修复项)
4. [测试覆盖缺口](#4-测试覆盖缺口)
5. [生产部署检查清单](#5-生产部署检查清单)
6. [评审总结](#6-评审总结)

---

## 1. 关键发现（阻止合入）

### 🔴 CROSS-1 `ask_stream()` 中 `_clean_sources` 在 `_assemble_context` 前执行（流式 RAG 回答无文档内容）

**文件**：`khub/llm/rag.py:78`
**严重度**：**BLOCKER — 数据正确性**

**当前代码**（rag.py:75-81）：
```python
hits = self.retriever.search_similar(question, k=k)
sources = self._fetch_sources(hits)
self._clean_sources(sources)   # ← 第 78 行：移除 _content
yield {"event": "sources", ...}  # ← 第 79 行：发给客户端
context = self._assemble_context(sources)  # ← 第 80 行：_content 已消失！
prompt = self._build_prompt(question, context)
```

**问题**：
- `_clean_sources()` 在第 78 行移除每个 source dict 中的 `_content` 字段（内部文档全文）
- `_assemble_context()` 在第 80 行通过 `src.get("_content", "")` 获取内容——但因 `_content` 已被移除，内容为空字符串
- 最终 LLM 收到的 prompt 中 context 部分全为空：
  ```
  --- 文档：小青龙汤 (相似度: 0.95) ---

  --- 文档：桂枝汤 (相似度: 0.87) ---
  ```
  LLM 在无任何参考文档内容的情况下生成回答，完全依赖模型自身知识。

**对比**：非流式 `ask()` 正确——先 `_assemble_context()`（第 56 行），后 `_clean_sources()`（第 63 行）。

**影响评估**：
- 流式 RAG 问答（WebUI AI 助手）产生空上下文的回答，与直接调 LLM 无差异
- 若 LLM 无相关知识（如冷门方剂），将产生幻觉或"资料中未找到"——用户看到矛盾信息（sources 有引用但回答说没找到）

**修复方案**：将 `_clean_sources` 移至 `_assemble_context` 之后、之前或将 context 预组装再清洗：

```python
# 方案 A（推荐）：清洗前先完成组装
hits = self.retriever.search_similar(question, k=k)
sources = self._fetch_sources(hits)
# 先组装上下文（需要 _content）
context = self._assemble_context(sources)
prompt = self._build_prompt(question, context)
# 再清洗内部字段，然后发给客户端
self._clean_sources(sources)
yield {"event": "sources", "data": {"sources": sources}}
```

```python
# 方案 B：保存 content 副本后清洗
sources = self._fetch_sources(hits)
raw_content = {s["id"]: s.pop("_content", "") for s in sources}
yield {"event": "sources", "data": {"sources": sources}}
# 从副本恢复 context
context = self._assemble_context_from_copy(sources, raw_content)
```

**建议**：方案 A 改动最小（约移动 2 行），无回归风险。

---

### 🔴 CROSS-2 WebUI AJAX 请求不携带 Authorization 头

**文件**：`khub/web/script.js` 全部 `fetch()` 调用
**严重度**：**BLOCKER — 生产安全（条件触发）**

**问题**：当 `KHUB_API_TOKEN` 环境变量被配置时，所有 API 端点要求 `Authorization: Bearer <token>` 头。但 WebUI 前端的所有 `fetch()` 调用均不携带该头：

| 端点 | 函数 | 行号 |
|------|------|------|
| `GET /search` | `search()` | 102 |
| `GET /semantic` | `semantic()` | 117 |
| `GET /documents` | `loadAll()`, `semantic()` | 134, 121 |
| `GET /conflicts` | `loadConflicts()` | 145 |
| `GET /stats` | `loadStats()` | 155 |
| `GET /documents/{id}` | `loadDoc()`, `loadConflictView()` | 77, 211 |
| `GET /documents/{id}/versions` | `loadConflictView()` | 213 |
| `GET /documents/{id}/versions/{vid}` | `loadConflictView()` | 217-218 |
| `PUT /documents/{id}` | `saveDoc()` | 196 |
| `POST /documents/{id}/resolve` | `resolveVersion()` | 240 |
| `POST /ask` | `aiAsk()` | 288 |

**影响**：启用 API Token 鉴权后，WebUI 完全不可用（所有请求返回 401）。

**修复方案**：
1. 前端：在页面加载时从某个来源获取 token（如 `<meta>` 标签、内联脚本变量）
2. 服务端 `_html_page()`：将 token 注入页面，供 JS 读取

```python
# api.py — _html_page 返回带 token 的页面
@staticmethod
def _html_page():
    page_path = os.path.join(os.path.dirname(__file__), "web", "index.html")
    with open(page_path, encoding="utf-8") as f:
        content = f.read()
    token = os.environ.get("KHUB_API_TOKEN", "")
    if token:
        token_script = f'<script>const API_TOKEN = "{token}";</script>'
        content = content.replace("</head>", token_script + "</head>")
    return content

# script.js — 在 fetch 中添加 Authorization 头
async function fetchWithAuth(url, options = {}) {
    if (typeof API_TOKEN !== 'undefined' && API_TOKEN) {
        options.headers = options.headers || {};
        options.headers['Authorization'] = 'Bearer ' + API_TOKEN;
    }
    return fetch(url, options);
}
```

**未启用鉴权时无影响**。但这是一旦启用即全站瘫痪的硬伤。

---

### 🔴 CROSS-3 `ask_stream()` 无空问题守卫

**文件**：`khub/llm/rag.py:66`
**严重度**：**MAJOR**

**问题**：`ask()` 有 `if not question or not question.strip(): return "", []`（第 52 行），但 `ask_stream()` 没有（第 66 行）。空字符串直接传给 `search_similar("", k=5)`，底层行为取决于 `Retriever` 实现：可能返回全量文档（将知识库全部注入 LLM，消耗大量 token 和时间），也可能返回空结果。

**已在 R1-RAG-05ex 中报告，三轮未修复。**

**修复**：
```python
def ask_stream(self, question: str, k: int = 5):
    if not question or not question.strip():
        return
    ...
```

---

### 🔴 CROSS-4 飞书适配器零测试覆盖

**文件**：`tests/` 目录
**严重度**：**MAJOR — 质量风险**

**R1 评审建议创建的 3 个测试文件全部缺失**：
| 建议测试文件 | 测试目标 | 状态 |
|-------------|----------|------|
| `tests/test_adapter_base.py` | Protocol 默认实现、`rawdoc_to_sync_item`、factory | ❌ 不存在 |
| `tests/test_feishu_auth.py` | `FeishuTokenManager` 过期刷新、并发安全 | ❌ 不存在 |
| `tests/test_feishu_adapter.py` | `FeishuAdapter` 方法（mock `_get`） | ❌ 不存在 |

`FeishuAdapter` 作为生产级数据源适配器，约 240 行核心代码（含分页循环、token 管理、错误重试），零测试覆盖。

---

## 2. 跨模块交叉问题

### 🟠 CROSS-5 `.replace()` 顺序：先替换 `{context}` 后替换 `{question}`

**文件**：`khub/llm/rag.py:145-147`
**严重度**：**MINOR**

```python
return (PROMPT_TEMPLATE
        .replace("{context}", context)      # 先替换 context
        .replace("{question}", question))    # 后替换 question
```

若文档内容中包含子串 `{question}`（极低概率，但 LaTeX/代码文档中可能），`{question}` 会被误替换为用户问题。

**已在 R2-NEW-03 报告，未修复。**

**修复**：交换顺序：
```python
.replace("{question}", question)
.replace("{context}", context)
```

---

### 🟠 CROSS-6 `esc()` 不转义单引号，onclick 属性存在 XSS 风险

**文件**：`khub/web/script.js:9`
**严重度**：**MINOR**（条件触发）

```javascript
function esc(s) { return (s || '').replace(/[&<>]/g, ...); }
```

**问题**：`esc()` 不转义单引号 `'`，而多处以单引号包裹的 `onclick` 属性中拼接了 `esc()` 的输出：

```javascript
editDoc(\'' + esc(r.canonical_id) + '\')  // 行 83
loadDoc(\'' + esc(id) + '\',\'' + esc(title) + '\')  // 行 185
resolveVersion(\'' + esc(id) + '\',...  // 行 231, 232
```

若文档 `canonical_id` 或 `title` 包含英文单引号（如 `materia_medica's_note` 或 SQL 注入测试字符串），可突破属性边界。`canonical_id` 由系统生成（`feishu:sid/token` 格式），不会含单引号；但 `title` 由用户输入，存在理论风险。

**已在 R1 WebUI 报告（R14），未修复。**

**修复**：为 `esc()` 添加 `'` 转义：
```javascript
function esc(s) {
    return (s || '').replace(/[&<>']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;'
    }[c]));
}
```

---

### 🟡 CROSS-7 ThreadingHTTPServer 共享 SQLite 连接，`check_same_thread=False`

**文件**：`khub/db.py:31` + `khub/api.py:516`
**严重度**：**MINOR**（当前可控）

`Store` 使用单个 SQLite 连接（`check_same_thread=False`），被 `ThreadingHTTPServer` 的所有工作线程共享。虽有 `_lock`（RLock）保护写入，但：

1. SQLite 连接本身非完全线程安全——WAL 模式下并发读可能看到中间状态
2. `docs_fts` 的 `MATCH` 查询在 `_search_single_paged` 中可能抛出 `sqlite3.OperationalError`（已有 fallback 到 `_search_like`，防御到位）
3. `urllib.request.urlopen`（`RemoteLLMProvider` 用）阻塞线程池线程——大并发时线程池可能耗尽

**当前状态可接受**，但建议在规模化部署前转换为连接池（每个线程独立连接）。

---

## 3. 各模块遗留可修复项

### 3.1 A 模块 — RAG（剩余 3 项）

| 编号 | 问题 | 级别 | 已报告轮次 | 备注 |
|------|------|------|-----------|------|
| R1-SEC-01 | prompt 注入防护未实现 | 🟠 MAJOR | R1/R2 | 问题直接拼入 prompt template，无分隔/注入标记 |
| R1-RAG-05ex | `ask_stream()` 无空问题守卫 | 🟡 MINOR | R1/R2 | 见 CROSS-3 |
| R2-NEW-03 | `.replace()` 顺序 | 🔵 SUGGESTION | R2 | 见 CROSS-5 |
| R1-PERF-01 | 大 k 时 context 截断无告警 | 🔵 SUGGESTION | R1 | `per_doc=400` 时产出 ~8K 字符，无日志 |

### 3.2 C 模块 — WebUI（剩余 8 项）

| 编号 | 问题 | 级别 | 已报告轮次 | 备注 |
|------|------|------|-----------|------|
| CROSS-2 | WebUI 不携带 Auth 头 | 🔴 BLOCKER | — | 见上 |
| CROSS-6 | `esc()` 不转义单引号 | 🟡 MINOR | R1(R14) | 见上 |
| R6 | 冲突视图硬编码最后两版本 | 🟡 MINOR | R1/R2/R3 | 假设冲突在 `vers[-2]` 与 `vers[-1]` 之间 |
| R9 | `_html_page()` 每次读盘 | 🟡 MINOR | R1/R2/R3 | `@functools.lru_cache(maxsize=1)` 即可 |
| R10 | 无 AbortController 去重 | 🟡 MINOR | R1/R2/R3 | 快速点击搜索结果混乱 |
| NEW-5 | 前端 HTML 弱脚本过滤 | 🟡 MINOR | R2/R3 | 服务端已清理，此层冗余 |
| NEW-7 | `import re as _re` 在 if 分支内 | 🔵 SUGGESTION | R2/R3 | 应移至文件顶部 |
| NEW-8 | `/resolve` 边界路径空 ID | 🔵 SUGGESTION | R2/R3 | 路径无 `/documents/` 前缀时返回 404 而非 400 |

### 3.3 D 模块 — 数据源（剩余 4+ 项）

| 编号 | 问题 | 级别 | 已报告轮次 | 备注 |
|------|------|------|-----------|------|
| C2#4 | `edit_time` 同时作 `etag`（秒级精度） | 🟡 MINOR | R1/R2/R3 | 增量同步可能遗漏同秒内更新 |
| C2#5 | `--space-id` 设定后仍拉全量空间 | 🟡 MINOR | R1/R2/R3 | 浪费一次 API 调用 |
| C3#2 | Token 刷新无锁（deferred） | 🟡 MINOR | R1/R2/R3 | 当前单线程，标记 deferred |
| C1 7 项 | 代码重复、未用函数、硬编码 sleep 等 | 🔵 SUGGESTION | R1/R2/R3 | 详情见 R3 报告 |
| CROSS-4 | 适配器零测试 | 🟠 MAJOR | — | 见上 |

---

## 4. 测试覆盖缺口

### 4.1 适配器模块（最高优先级）

模块 `khub/adapters/` 约 300 行代码，测试文件数为 **0**：

| 目标 | 建议测试文件 | 关键场景 |
|------|-------------|---------|
| `FeishuTokenManager` | `test_feishu_auth.py` | 过期自动刷新、并发安全、凭证错误 |
| `FeishuAdapter.pull()` | `test_feishu_adapter.py` | 分页遍历、token 过期重试、`URLError`、`_list_spaces` 边界 |
| `create_adapter()` | `test_adapter_base.py` | 已知/未知 type、懒导入 |
| `SourceAdapter.normalize()` | `test_adapter_base.py` | 默认实现、`rawdoc_to_sync_item` |

### 4.2 RAG 模块（中优先级）

从 R1/R2 报告统计，以下场景仍缺测试：

| 缺失场景 | 风险说明 |
|---------|---------|
| `_assemble_context` 超长边界（k=20, max_chars=6000） | context 截断但无测试验证 |
| `k=0`/负值 | 代码层 `max(1, min(k, 20))` 已保护，但未测试 |
| 空 content（文档已删但向量残留） | `vers[-1]` 已保护，但未测试 |
| `_send_sse` 中 `k=null/string` | API-01 已保护但不在测试中 |
| 并行 `ask_stream` 调用 | 无并发安全测试 |

### 4.3 WebUI 后端（中优先级）

| 缺失场景 | 风险说明 |
|---------|---------|
| PUT 创建版本后清除冲突标记 | 已实现但无测试验证 |
| POST resolve 无效版本 ID | 400 响应但无断言 |
| HTML XSS 向量 | 服务端清理需要用测试向量验证 |
| SSE 400/401 响应 | 前端错误显示逻辑 |
| 编辑 HTML 格式 | format 字段传递 |

### 4.4 测试通过率

```
227 tests total — 确认全部通过
```

---

## 5. 生产部署检查清单

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| 1 | **CROSS-1 修复**：`ask_stream` 清洗顺序 | 🔴 未修复 | **合入前必须修** |
| 2 | **CROSS-2 修复**：WebUI Auth 头 | 🔴 未修复 | 启用 auth 即瘫痪 |
| 3 | **CROSS-3 修复**：`ask_stream` 空问题守卫 | 🔴 未修复 | 三轮未改 |
| 4 | **CROSS-4 修复**：适配器测试 | 🟠 未实现 | 零测试合入高风险 |
| 5 | CROSS-6 `esc()` 单引号转义 | 🟡 未修复 | 低风险 XSS |
| 6 | `KHUB_LLM_URL` 配置验证 | 🟢 有日志 | `get_provider()` 打印警告 |
| 7 | `KHUB_API_TOKEN` 配置验证 | 🟢 工作正常 | 除 WebUI 外 |
| 8 | 静态文件路径遍历保护 | 🟢 已验证 | `os.path.realpath` 检查 |
| 9 | HTML format XSS 清理 | 🟢 已验证 | 服务端多正则 + 前端冗余 |
| 10 | SQLite WAL 模式 | 🟢 已配置 | 并发读写安全 |
| 11 | SSE `X-Accel-Buffering` | 🟢 已添加 | Nginx 反代兼容 |
| 12 | CORS preflight (`OPTIONS`) | 🟢 已实现 | `do_OPTIONS` 方法 |
| 13 | 信号处理优雅关闭 | 🟢 已实现 | `SIGTERM`/`SIGINT` |
| 14 | WAL 归档窗口 | 🟢 已实现 | `prune_wal()` 按条数/天数 |
| 15 | 备机快照重建 | 🟢 已实现 | `make_snapshot_db` + `rebuild_fts` |
| 16 | 认证重复（dispatch + _send_sse） | 🟢 可接受 | 双重校验更安全 |
| 17 | 冲突视图忽略 version format 字段 | 🔵 可忽略 | 当前版本无 HTML 冲突 |
| 18 | `import re` 在 if 分支内 | 🔵 可忽略 | 功能正确 |

---

## 6. 评审总结

### 6.1 修复质量

三轮评审共识别 **~50 项** 问题，其中 **43 项已正确修复**。每轮修复通过率：

| 模块 | R1 修复 | R2 修复 | R3 修复 | 遗留 |
|------|---------|---------|---------|------|
| A(RAG) | 15/15 ✅ | — | — | 4 项（含 1 MAJOR + 3 SUGGESTION） |
| C(WebUI) | 7/7 ✅ | 3/3 ✅ | 3/3 ✅ | 8 项（含 2 BLOCKER + 5 MINOR + 1 SUGGESTION） |
| D(数据源) | 3/3 ✅ | 3/3 ✅ | 2/3 ⚠️ | 4+ 项（含 1 MAJOR + 2 MINOR + 7 SUGGESTION） |

### 6.2 本次新发现 vs 遗留累计

| 级别 | 新增（本次） | 遗留累计 | 最关键项 |
|------|-------------|---------|---------|
| 🔴 BLOCKER | **3** | 3 | `ask_stream` 空上下文、WebUI 无 Auth、空问题守卫 |
| 🟠 MAJOR | **1** | 3 | 适配器零测试、prompt 注入 |
| 🟡 MINOR | **0** | 10 | esc() 单引号、分页硬编码、_html_page 缓存等 |
| 🔵 SUGGESTION | **0** | 11+ | 代码风格/可维护性 |

### 6.3 合入建议

**不建议在当前状态合入**。以下 3 个 BLOCKER 必须在合入前修复：

1. **CROSS-1** 🔴 `ask_stream()` 中 `_clean_sources` 在 `_assemble_context` 之前执行 → 流式 RAG 回答无文档内容（1 行修复：调整顺序）
2. **CROSS-2** 🔴 WebUI 所有 `fetch()` 不携带 Authorization 头 → 启用鉴权则全站瘫痪（中等工作量：注入 token + 封装 `fetchWithAuth`）
3. **CROSS-3** 🔴 `ask_stream()` 缺少空问题守卫 → 空字符串可触发全量文档检索（1 行修复：添加守卫）

**BLOCKER 修复后**，建议将 CROSS-4（适配器测试）、R1-SEC-01（prompt 注入防护）纳入本迭代，其余 MINOR/SUGGESTION 项可安排至 0.3 系列迭代。

### 6.4 总体评价

代码整体质量 **中上**。架构清晰（Protocol 解耦、SSE 流式、分页搜索）、安全基线良好（路径遍历防护、HTML 清理、WAL 复制、快照恢复）。三轮修复验证显示团队响应积极、修复质量可靠。

**最大风险**来自本次新发现的 `ask_stream` 空上下文 bug（CROSS-1）——它是 R2 `_content` 泄露修复引入的回归。修复者将 `_clean_sources` 放置在流式路径中 `yield` 之前（为保护客户端不看到全文），但未意识到 `_assemble_context` 同样依赖 `_content`。这种"一个内部字段被两个消费者复用"的耦合是代码评审中典型的盲区。
