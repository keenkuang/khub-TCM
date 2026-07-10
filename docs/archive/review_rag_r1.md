# RAG 问答模块第 1 轮代码评审报告

> 评审范围：commit `f6b7c93` — `khub/llm/rag.py`, `khub/llm/__init__.py`, `khub/api.py`（RAG 相关）、`tests/test_rag.py`、`tests/test_rag_stream.py`、`tests/test_api.py`（Ask 相关）
>
> 评审日期：2026-07-09
>
> 分级：🔴 BLOCKER / 🟠 MAJOR / 🟡 MINOR / 🔵 SUGGESTION

---

## 一、khub/llm/rag.py — RAGEngine

### 🔴 RAG-01 `_build_prompt` 使用 `str.format()` 存在格式字符串冲突

`PROMPT_TEMPLATE.format(question=question, context=context)` — 如果用户问题或文档原文包含 `{` 或 `}` 字符（如 LaTeX 公式 `\frac{a}{b}`、Python 代码 `{x: y}`、JSON），`str.format()` 会抛出 `KeyError`。

```python
# 当前代码（rag.py:116）
@staticmethod
def _build_prompt(question: str, context: str) -> str:
    return PROMPT_TEMPLATE.format(question=question, context=context)
```

**修复建议**：改用 `str.replace()` 或 `string.Template`：

```python
@staticmethod
def _build_prompt(question: str, context: str) -> str:
    return (PROMPT_TEMPLATE
            .replace("{question}", question)
            .replace("{context}", context))
```

---

### 🟠 RAG-02 `_fetch_sources` + `_assemble_context` 重复查询数据库（N+1 + 2N）

管道中存在严重的数据库查询浪费：

| 方法 | 每次调用查询次数 |
|---|---|
| `_fetch_sources` | `get_document` × k + `get_versions` × k |
| `_assemble_context` | `get_versions` × k |

对于 `k=5` 单次 RAG 调用 → **15 次 SQL 查询**（`ask`）+ **15 次**（`ask_stream`）。对于 `k=20` → **60 次 SQL 查询**。

更严重的是 `_assemble_context` 重新查询了 `_fetch_sources` 已经取过的 `get_versions`，但只为了取 `content` 字段。

**修复建议**：让 `_fetch_sources` 把 `(content, snippet)` 一起返回，`_assemble_context` 复用之。或做一个批量 `get_documents(ids)` 方法：

```python
def _fetch_sources(self, hits):
    """返回富来源（含全文 content 供 context 组装使用）。"""
    sources = []
    for doc_id, score in hits:
        doc = self.store.get_document(doc_id)
        vers = self.store.get_versions(doc_id)
        content = vers[-1]["content"] if vers else ""
        snippet = content[:200].strip()
        snippet = " ".join(snippet.split())
        sources.append({
            "id": doc_id,
            "title": doc["title"] if doc else doc_id,
            "score": round(score, 4),
            "snippet": snippet,
            "_content": content,       # ← 保留给 _assemble_context
        })
    return sources

def _assemble_context(self, sources, max_chars=6000):
    per_doc = max(400, max_chars // max(len(sources), 1))
    parts = []
    for src in sources:
        content = src.get("_content", "")  # ← 复用，不再查 DB
        truncated = content[:per_doc].strip()
        parts.append(
            f"--- 文档：{src['title']} (相似度: {src['score']}) ---\n"
            f"{truncated}"
        )
    return "\n\n".join(parts)
```

同时对 `ask_stream`，`_fetch_sources` 已经被调用了，后续 `_assemble_context` 不应再次查询。

---

### 🟡 RAG-03 `ask()` 非流式路径未捕获 LLM 异常

`rag.py:52` — `answer = self.llm.complete(prompt, temperature=0.3)` 没有 try/except 包围。若 `RemoteLLMProvider.complete()` 遇到网络错误或 API 返回异常格式，异常会直接传播给调用方，导致 HTTP 500。

`ask_stream()` 有 try/except 覆盖 LLM 部分，但 `ask()` 没有。

**修复建议**：添加异常处理：

```python
def ask(self, question: str, k: int = 5) -> tuple[str, list[dict]]:
    hits = self.retriever.search_similar(question, k=k)
    sources = self._fetch_sources(hits)
    context = self._assemble_context(sources)
    prompt = self._build_prompt(question, context)
    try:
        answer = self.llm.complete(prompt, temperature=0.3)
    except Exception as exc:
        logger.error("LLM complete failed: %s", exc)
        return f"（回答生成失败：{exc}）", sources
    return answer, sources
```

---

### 🟡 RAG-04 `ask_stream()` 中 `_fetch_sources` / `_assemble_context` 的异常未捕获

`rag.py:64-69` — 管道前两步（检索、组装）在 try 块之外。如果 `search_similar()` 或 `_fetch_sources()` 抛出异常（如 DB 连接问题、序列化错误），不会生成 error 事件，而是直接抛出。

```python
# 当前代码：64-76 行
hits = self.retriever.search_similar(question, k=k)   # ← 未保护
sources = self._fetch_sources(hits)                    # ← 未保护
yield {"event": "sources", ...}

context = self._assemble_context(sources)              # ← 未保护
prompt = self._build_prompt(question, context)
try:
    for token in self.llm.complete_stream(...):
```

**修复建议**：全部包进 try/except 或检查返回：

```python
def ask_stream(self, question: str, k: int = 5):
    try:
        hits = self.retriever.search_similar(question, k=k)
        sources = self._fetch_sources(hits)
        yield {"event": "sources", "data": {"sources": sources}}
        context = self._assemble_context(sources)
        prompt = self._build_prompt(question, context)
    except Exception as exc:
        yield {"event": "error", "data": {"error": f"检索/组装失败: {exc}"}}
        return
    try:
        for token in self.llm.complete_stream(prompt, temperature=0.3):
            yield {"event": "token", "data": {"token": token}}
    except Exception as exc:
        yield {"event": "error", "data": {"error": str(exc)}}
        return
    yield {"event": "done", "data": {"finish_reason": "stop"}}
```

---

### 🟡 RAG-05 `ask()` / `ask_stream()` 缺少对 `question` 的参数校验

`api.py` 在 dispatch 层验证了 question 非空且 ≤2000 字符，但 `RAGEngine` 是公共 API，可以直接被其他模块调用（考试、问诊子系统的 issue 模板中提到了"未来考试/问诊/病历模块依赖"）。若 question 为空字符串，`search_similar("", k=5)` 的行为依赖于 `Retriever` 实现（可能返回全量文档）。

**修复建议**：

```python
def ask(self, question: str, k: int = 5) -> tuple[str, list[dict]]:
    if not question or not question.strip():
        return "", []
    # ...
```

---

## 二、khub/llm/__init__.py — LLM Provider

### 🟠 LLM-01 `NoOpProvider.complete_stream` 使用 `if False: yield` hack

```python
def complete_stream(self, prompt: str, **kwargs) -> Generator[str, None, None]:
    if False:
        yield ""
```

这是让空 generator 函数类型正确的常见 hack，但没有注释说明意图，容易被误删或 lint 工具标记为 dead code。

**修复建议**：使用显式 `return` + `yield` 模式更清晰：

```python
def complete_stream(self, prompt: str, **kwargs) -> Generator[str, None, None]:
    """流式占位：不 yield 任何值（空 generator）。"""
    return
    yield  # 使函数成为 generator
```

---

### 🟠 LLM-02 `RemoteLLMProvider.complete()` 异常处理缺失

```python
# __init__.py:64-71
try:
    with urllib.request.urlopen(req, timeout=self.timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
except urllib.error.URLError as exc:
    raise      # ← 裸 raise，无日志
except Exception as exc:
    raise      # ← 裸 raise，无日志
```

两个 catch 块只做了 `raise`，完全没有日志记录。API 返回 200 但 body 是错误 JSON 时（如 `{"error": "rate limited"}`），`payload["choices"][0]["message"]["content"]` 会抛出 `KeyError`（未被 catch，最终 HTTP 500）。

**修复建议**：

```python
try:
    with urllib.request.urlopen(req, timeout=self.timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
except urllib.error.URLError as exc:
    logger.error("LLM request failed: %s", exc)
    raise
payload = payload.get("choices", [])
if not payload:
    raise RuntimeError(f"LLM returned no choices: {resp_body}")
content = payload[0].get("message", {}).get("content", "")
return str(content)
```

---

### 🟠 LLM-03 `complete_stream()` 未处理 JSON 解析错误或 SSE 异常

`__init__.py:92-93` — `payload = line[6:]` 后直接 `json.loads(payload)`。如果远端返回格式异常的 SSE 行（如代理返回 HTML 错误页面），会抛出 `json.JSONDecodeError`。由于 `rag.py:71` 的 try/except 在 `for token in self.llm.complete_stream(...)` 外层，异常会被捕获为 error 事件，但不会记录日志。

同时，`for raw_line in resp` 依赖 `urllib` 的逐行读取，当响应体超大时（如模型流式输出持续数分钟），`timeout=self.timeout` 仅限制连接超时，**不限制读取超时**。长时间无 token 的场景将 hang 住。

**修复建议**：使用 `resp.readline()` 传入超时逻辑，并增加 JSON 解析的 try/except 和日志。

---

### 🟡 LLM-04 `get_provider()` 环境变量缺失时静默返回 NoOpProvider

`__init__.py:127` — `return NoOpProvider()` 没有日志。上线后如果环境变量配置错误，用户会看到空回答而不知原因。

**修复建议**：

```python
KHUB_LLM_URL = os.environ.get("KHUB_LLM_URL", "")
if KHUB_LLM_URL:
    ...
else:
    logger.warning("KHUB_LLM_URL 未设置，使用 NoOpProvider（返回空回答）")
    return NoOpProvider()
```

---

### 🔵 LLM-05 `RemoteLLMProvider` 签名中 `model` 默认值为空字符串

`__init__.py:46` — `model: str = ""`，然后 line 55 使用 `self.model or "default"`。如果用户设置 `KHUB_LLM_MODEL=""`（空字符串），会发送 `model: "default"` 给远端 API，但远端可能不认识这个 model 名。更好做法是留空时不发送 model 字段、或默认值更清晰。

---

## 三、khub/api.py — HTTP 端点

### 🟠 API-01 `_send_sse()` 中 `k` 参数类型安全不足

```python
# api.py:547
k = int(body.get("k", 5))
```

如果 body 中的 `k` 是 `None`（JSON `null`），`int(None)` 抛出 `TypeError`；如果是 float `5.5`，`int(5.5)` 正常但行为可能不符合预期。`dispatch` 中 `/ask` 路径使用 `_safe_int` 做了保护，但 `_send_sse` 没有。

**修复建议**：

```python
k = body.get("k", 5)
if not isinstance(k, (int, float)):
    k = 5
k = max(1, min(int(k), 20))
```

---

### 🟡 API-02 SSE 端点缺少 `Access-Control-Allow-Headers` / `Access-Control-Allow-Methods`

前端 JS 发送 POST 到 `/ask` 时，Content-Type: application/json 属于 non-simple 请求头，浏览器会先发 OPTIONS preflight。当前没有 `do_OPTIONS` 方法，跨域访问时 preflight 会失败。

```python
# 添加：
def do_OPTIONS(self):
    self.send_response(204)
    self.send_header("Access-Control-Allow-Origin", "*")
    self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
    self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
    self.end_headers()
```

---

### 🟡 API-03 `_send_sse` 中 auth 校验与 `dispatch` 重复

认证逻辑在 `dispatch()`（line 36-38）和 `_send_sse()`（line 538-540）各有一份。虽然增加了安全性，但两份代码在 token 校验逻辑上需要同步维护。建议集中在 `dispatch` 或 `Handler` 的 `do_POST` 入口统一处理。

---

### 🟡 API-04 SSE 响应缺少 `X-Accel-Buffering: no` 头

如果 khub 部署在 nginx 反向代理后（生产常见），nginx 默认会 buffer SSE 响应，破坏流式效果。

```python
self.send_header("X-Accel-Buffering", "no")
```

虽然当前 `serve()` 绑定 `127.0.0.1` 默认仅本地使用，但作为生产代码应预置。

---

### 🟡 API-05 前端 AI 对话框没有防抖 / 请求取消

`aiAsk()` 函数在流式请求进行时通过 `aiState.streaming` 防止重复发送，但 `useStream=false`（非流式）路径中，没有设置 `streaming=true` 的状态锁。如果用户快速连点发送，非流式路径会触发多个并发请求。

同时，`AbortController` 被定义了（`abortController:null`）但从未使用——流式请求中途无法取消。

---

### 🟡 API-06 硬编码 HTML 页面

`_html_page()` 返回 230+ 行的硬编码 HTML/CSS/JS 字符串。维护困难、无法做 HTML 转义检查、CSP 头难配置。

**修复建议**：抽取为独立文件 `khub/web/index.html`，用 `open().read()` 加载。

---

## 四、tests/test_rag.py — 单元测试

### 🟠 TST-01 `TestAskStream.test_stream_events_sequence` 使用了真实 Retriever（未 mock）

```python
# test_rag.py:178-181
engine = RAGEngine(s, llm=llm)  # 没有传 mock retriever！
events = list(engine.ask_stream("什么汤？", k=5))
```

由于 `_make_store_with_docs()` 没有调用 `index_ebook()`，向量索引表为空。`retriever.search_similar()` 返回空列表。测试看似通过（token 事件序列正确），但实际未测试带 context 的真实管道——LLM 收到了空 context。

`TestAsk.test_ask_returns_answer_and_sources` 正确 mock 了 Retriever，但本测试没有。

**修复建议**：统一注入 mock Retriever 或确保 `_make_store_with_docs` 也做索引。

---

### 🟠 TST-02 `test_rag_stream.py` mock 使用猴子补丁（monkey-patch）全局类

```python
# test_rag_stream.py:208-219
original_init = RAGEngine.__init__
original_stream = RAGEngine.ask_stream
RAGEngine.__init__ = mock_init
RAGEngine.ask_stream = mock_ask_stream
```

这种方式：
1. 影响同一进程中所有 RAGEngine 实例（包括 `app_and_server` fixture 中运行的 HTTP 线程）
2. 如果测试异常时 `finally` 没执行到，补丁残留会导致后续测试不可预测

**修复建议**：使用 `unittest.mock.patch.object` 上下文管理器替代。

---

### 🟡 TST-03 缺失关键测试场景

| 缺失场景 | 风险 |
|---|---|
| `ask()` 中 LLM 抛出异常 | 非流式错误路径从未测试 |
| `_assemble_context` 超长 max_chars（6000 上限） | 边界条件未覆盖 |
| 问题包含特殊字符（`{`、`}`、`<script>`） | 格式字符串冲突 / XSS 未验证 |
| `k` 参数为 0 或负数 | 参数校验遗漏 |
| 并行调用 `ask_stream` | 无并发安全测试 |
| 空 content（文档已删除但向量残留） | `vers[-1]` 在 vers 为空时已规避，但测试仅覆盖了 missing doc |
| `_send_sse` 中 `k` 为 `null` / string / negative | 类型安全未测试 |

---

### 🔵 TST-04 `test_max_chars_honored` 的断言有 500 字符余量

```python
# test_rag.py:132
assert len(ctx) <= 2500  # 有余量（换行符等）
```

max_chars=2000，断言 2500 有 25% 余量。虽然考虑到标题和分隔符，但可以收紧到 `<= 2200` 让测试更精准。

---

## 五、综合问题

### 🟠 SEC-01 未做 prompt 注入防护

LLM prompt 中直接拼接了用户问题和文档原文。虽然 prompt template 中有"不要编造"的指令，但没有对用户输入做注入检测。恶意用户可以通过问题注入覆盖系统指令。建议考虑：

```python
# 在 _build_prompt 中，对 question 做注入标记
question_safe = question.replace("\\n", " ").replace("\\r", " ")
# 或使用分隔符标记用户输入
```

---

### 🟡 PERF-01 `_assemble_context` 中 `per_doc` 对大 k 不合理

当 `len(sources) = 20` 时：`per_doc = max(400, 6000 // 20) = 400`，每篇取 400 字符，共 ~8000 字符（含标题和分隔符）。如果 LLM 的上下文窗口有限（如 4K tokens），context 可能会被截断。当前无任何截断后的告警或日志。

---

## 评审总结

| 级别 | 数量 | 关键风险点 |
|---|---|---|
| 🔴 BLOCKER | 1 | `str.format()` 在含 `{}` 内容时会崩溃 |
| 🟠 MAJOR | 7 | N+1 查询、重复 DB 查询、异常处理缺失、mock 脆弱、prompt 注入、类型安全 |
| 🟡 MINOR | 11 | 日志缺失、CORS preflight、测试覆盖不足、参数校验、并发安全 |
| 🔵 SUGGESTION | 2 | 代码可读性、断言精度 |

**总体评价**：代码结构清晰、接口设计合理、流式 SSE 实现正确。需要在**异常处理完备性、数据库查询优化、输入安全性**三个方向加强。建议优先修复 BLOCKER 和 MAJOR 级别的所有问题后再合入主分支。
