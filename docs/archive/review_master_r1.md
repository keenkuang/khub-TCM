# khub master 第1轮代码评审报告

> 评审日期: 2026-07-10
> 评审范围: master 分支（merge commit 924e3b5，自 m1）
> 评审人: general-purpose-42
> 评审焦点: 阻止 master 发布的阻塞性问题

---

## 摘要

本次评审覆盖 5 个关键文件（RAG引擎、API 层、Dockerfile、docker-compose、测试计划），外加 `pyproject.toml`、`llm/__init__.py`、`cli.py`、nginx 配置。

**共发现问题 13 项：P0 × 2（必须修复后方可发布）| P1 × 4 | P2 × 4 | P3 × 3**

---

## P0 — 必须修复（阻止发布）

### P0-1. `pyproject.toml` 依赖声明严重不完整

**文件**: `pyproject.toml:5`

```toml
dependencies = ["PyYAML>=6.0"]
```

`pyproject.toml` 仅声明了 `PyYAML>=6.0` 一个运行时依赖。但 `Dockerfile:15` 以及代码中实际依赖以下包：

| 包 | 用途 | 来源 |
|------|------|--------|
| `pypdf` | PDF 提取 | `Dockerfile:15` |
| `sqlite-vec` | 向量检索引擎 | `Dockerfile:15` |
| `cryptography` | PII 加密 | `Dockerfile:15` |
| `boto3` | S3 备份 | `Dockerfile:15` |

Dockerfile 用 `pip install --no-cache-dir PyYAML pypdf sqlite-vec cryptography boto3` 手动安装，但这些依赖未进入项目元数据。任何 `pip install khub` 或 `pip install -e .`（从源码安装）都会因为缺少这些包在运行时抛 `ModuleNotFoundError`。

**建议**：将以上 4 个包移入 `pyproject.toml` 的 `dependencies`，Dockerfile 删除手动 pip 安装，改为 `pip install ".[pdf,ann]"` 或直接 `pip install .`（如果全部列为必选）。如果某些包是可选组件，用 `[project.optional-dependencies]` 分组。

**风险**: 新部署 / CI 环境 100% 必现，无规避手段。

---

### P0-2. RAGEngine 空上下文时仍调用 LLM，捏造回答风险

**文件**: `khub/llm/rag.py` — `ask:50-62` 和 `ask_stream:66-96`

当检索结果为空时，`_assemble_context()` 返回 `""`。此时 prompt 模板被渲染为：

```
参考文档：


用户问题：小青龙汤的组成是什么？

请给出准确、简洁的回答：
```

模板中的"如果参考文档不足以回答，请如实说'资料中未找到相关信息'"依赖 LLM 完全遵从。**临床/TCM 场景下，LLM 可能捏造方剂组成或诊疗建议，存在患者安全风险。**

当前 `ask` 和 `ask_stream` 均未保护空上下文路径。

**建议**：在调用 `self.llm.complete()`/`self.llm.complete_stream()` 前检查 `context.strip()` 是否为空，若空则直接返回/ yield "资料中未找到相关信息"，不进 LLM。

```python
# 示例（非流式）：
if not context.strip():
    return "资料中未找到相关信息。", sources
```

---

## P1 — 严重问题（强烈建议发布前修复）

### P1-1. SSE 流式端点绕过 `dispatch` 鉴权架构

**文件**: `khub/api.py:546-547`

```python
# 流式 RAG 问答：不走 dispatch（SSE 需直接写 wfile）
if body and body.get("stream") and self.path == "/ask":
    return self._send_sse(body)
```

`_send_sse()` 有自己的鉴权实现（第 480-482 行），与 `dispatch()` 的鉴权（第 52-54 行）**逻辑重复**。若后续：
- `dispatch` 鉴权升级（如增加 IP 白名单、角色鉴权）
- 新增 SSE 端点

则 `_send_sse` 或新端点容易遗漏鉴权。

**建议**：
- 方案 A：`_send_sse` 内部也调用 `app.dispatch()` 做鉴权，根据返回值决定是否发送 SSE
- 方案 B（推荐）：将鉴权提前到 `do_POST` 中统一处理，再分派 dispatch/SSE

---

### P1-2. Docker 部署测试覆盖为 0

**文件**: `docs/test_plan.md:40-41`

```
| **新增：Docker 部署** | — | 0 | P1 |
```

发布 master 后用户第一接触面就是 `docker compose up`。零测试意味着：
- Dockerfile 构建断裂不会被自动捕获
- docker-compose 依赖关系（nginx→khub health check）未经 CI 验证
- 资源限制、网络配置等变更缺乏回归

**建议**：至少添加一个 shell 测试脚本（可手动执行），覆盖：
1. `docker compose build khub` 成功
2. `docker compose up -d` 后 `/health` 返回 200
3. `docker compose down` 正常停止

可选：用 `pytest-testinfra` 或简单 `subprocess` 跑 Python 测试。

---

### P1-3. `GET /documents` 无分页，大数据量风险

**文件**: `khub/api.py:162-166`

```python
if method == "GET" and path == "/documents":
    rows = self.store.conn.execute(
        "SELECT canonical_id, title, updated_at, source_ids FROM documents "
        "ORDER BY updated_at DESC").fetchall()
    return 200, [dict(r) for r in rows]
```

无 `LIMIT`/`OFFSET`。在 10 万+ 文档时：
- 全量 `fetchall()` 会将全部行加载到内存
- `[dict(r) for r in rows]` 二次复制
- 下游 WebUI 列表渲染也会卡顿

**建议**：至少加 `LIMIT 1000` 默认值，支持 `?page=&per=` 参数（与 `/search` 一致）。

---

### P1-4. `_send_sse()` 在 auth 失败后仍可能覆写响应头

**文件**: `khub/api.py:497-503`

```python
self.send_response(200)
# ... 设置 SSE 响应头 ...
self.end_headers()
```

若 auth 失败，`self._send(401, ...)` 已被调用（写入了 401 响应）。但 `_send_sse` 的调用路径是 `do_POST` 第 546-547 行——仅当 `stream=True` 时进入。**Auth 已在 `_send_sse` 内部第 480-482 行检查并提前返回**，所以 `self.send_response(200)` 仅当 auth 通过后才执行。当前逻辑在运行时是正确的，但代码看起来像有一个竞态窗口。

**建议**：将 auth 提前到 `_send_sse` 入口处，明确返回 + return，不在方法体中段设置响应头。

---

## P2 — 重要问题（建议修复）

### P2-1. `do_PUT` / `do_DELETE` 与 `do_POST` 大量重复代码

**文件**: `khub/api.py`
- `do_POST`: 第 528-558 行（30 行）
- `do_PUT`: 第 571-595 行（24 行）
- `do_DELETE`: 第 598-622 行（24 行）

三者的请求体读取、Content-Length 校验、JSON parse、异常处理逻辑完全相同，仅在最终调用的 `app.dispatch(method, ...)` 上不同。任何安全修复（如 Content-Type 校验、请求体编码检查）都得改 3 个地方。

**建议**：提取公共方法，例如 `_read_body(method)` 统一返回 body dict，复用错误处理。

---

### P2-2. `Transfer-Encoding: chunked` 拒绝不优雅

**文件**: `khub/api.py:528-529,571-572,598-599`

```python
if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
    return self._send(411, {"error": "请使用 Content-Length，不接受 Transfer-Encoding: chunked"})
```

HTTP 411（Length Required）的语义是"服务端拒绝接受没有 `Content-Length` 的请求"。`chunked` 本身是有长度表示的（通过分块编码）。更合理的做法是用 501 Not Implemented 或 400 Bad Request。同时，Python 标准库 `http.server` 原生支持 `chunked` 读取（`self.rfile.read()` 会正确处理分块编码）。

**建议**：移除 chunked 拒绝逻辑，或改用 501 + 更准确的错误信息。若必须拒绝，用 400 而非 411。

---

### P2-3. 测试计划的数量声明与实测不一致

**文件**: `docs/test_plan.md:85`

```
| phase-1 | `pytest -q` | 238 passed / 2 skipped |
```

实测 `pytest --collect-only -q` 返回 **240 个测试用例**（未跳过）。测试计划可能在文档编写时引用了旧版计数，或者跳过的 2 个已不存在。

另外，测试计划中列出了 30+ 个模块，但实际测试目录有 45 个文件（多了 `test_llm_provider.py`, `test_llm.py`, `test_normalizer.py`, `test_stats.py`, `test_storage.py`, `test_watch.py` 等），这些新增测试未在文档中登记。

**建议**：在 CI 中自动采集测试计数，避免手动声明与实际情况产生偏差。

---

### P2-4. Dockerfile HEALTHCHECK 没有 `start_period`

**文件**: `Dockerfile:27-28`

```
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD python -c ...
```

没有设置 `--start-period`。首次启动时，SQLite 数据库初始化、LLM 提供器配置等可能需要时间。没有 start_period 会导致容器在初始化期间就被视为不健康，被编排器重启。

对比 `docker-compose.yml:42` 中设置了 `start_period: 15s`，但 Dockerfile 层面的 healthcheck 是独立配置的。当用户直接 `docker run` 而不走 compose 时，Dockerfile healthcheck 会立即生效。

**建议**：Dockerfile 添加 `--start-period=15s`（或更大，如 30s），与 compose 保持一致。

---

## P3 — 次要问题（建议记录，不需阻止发布）

### P3-1. RAG `_assemble_context` 按字符截取，极端情况可能切分代理对

**文件**: `khub/llm/rag.py:132`

```python
truncated = content[:per_doc].strip()
```

Python 的 `str[:n]` 按 Unicode Code Point 截取。BMP 内的 CJK 字符（U+4E00–U+9FFF）是单个 code point，安全。但对于补充平面中的罕见汉字（如 U+2A6DF），一个字符由两个 surrogate code units 组成。Python 3 内部使用 UCS-4/UTF-32 或 UCS-2，取决于编译选项。在 PEP 393（Python 3.3+）中，窄构建（UCS-2）会切分 surrogate pair。

实际上 Python 3.12（Dockerfile 镜像）使用灵活字符串表示（flexible string representation），BMP 字符用 1 个 code unit，非 BMP 用 2 个。非 BMP 字符在窄构建下 `str[:n]` 可能分开 surrogate pair → 生成无效字符。

**概率极低**（中医文档罕见补充平面汉字），无需立即修复，但可加 `content.encode('utf-8')[:max_bytes].decode('utf-8', errors='ignore')` 确保截断安全。

---

### P3-2. 静态文件 `application/octet-stream` 未列在 MIME 映射中

**文件**: `khub/api.py:70-71`

```python
ctype = _MIME.get(os.path.splitext(filename)[1].lower(), "application/octet-stream")
```

对 `_MIME` 中未列出的扩展名返回 `application/octet-stream`。这是安全的，但如果 WebUI 使用了 `.woff2`、`.wasm` 等现代格式，浏览器可能无法正确处理。建议补充常见 web 资源 MIME 映射。

---

### P3-3. `start_period: 15s` 对于冷启动可能不足

**文件**: `docker-compose.yml:42`

```yaml
start_period: 15s
```

首次启动时：pip 层已缓存（Dockerfile 层缓存），但：
- SQLite 数据库初始化 + 向量表创建需要时间
- 如果启用了真实 LLM/Embedding 提供器，网络连接超时可能 30s+

1500+ 文档的数据库打开可能也需要若干秒。15s 偏紧。

**建议**：提升至 `30s` 或 `60s`，或改为 `disabled`（仅由 nginx `condition: service_healthy` 控制）。

---

## 其他观察

### 正面发现
- **安全响应头全面**：X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy, CSP（HTML），HSTS 齐备
- **路径穿越防御到位**：静态文件服务用 `os.path.realpath` 双校验（api.py:64-66）
- **SSE 断连处理正确**：`_send_sse` 捕获 `BrokenPipeError`/`ConnectionResetError` 静默退出
- **HTML XSS 净化**：format=html 时正则剥离 script/style/iframe/事件处理器/javascript: href（api.py:207-212）
- **RAG 内部字段保护**：`_clean_sources` 在数据传出前擦除 `_content`（rag.py:140-143）
- **nginx 限流配置到位**：30r/m + burst 20 防止 API 滥用
- **SSL 证书就绪**：`ssl/` 目录包含 khub.crt / khub.key
- **45 个测试文件，240 个测试用例**：覆盖率广泛

### 首次提交建议
- **不要**一次性修复所有 P1–P3 问题。建议先修 P0，然后排序 P1。
- `pyproject.toml` 修复后需要同步更新 `pyproject.toml` 中的包列表和 Dockerfile 的 pip 行。
- `rag.py` 空上下文守卫可以单独提交，不影响其他模块。
