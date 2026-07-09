# RAG 知识问答模块 — 详细设计规格

> 设计版本：v1.0  
> 对应分支：feature/rag-qa  
> 设计者：designer-a

---

## 目录

1. [新增 API 端点](#1-新增-api-端点)
2. [RAGEngine 类设计](#2-ragengine-类设计)
3. [前端对话框](#3-前端对话框)
4. [流式 SSE 链路](#4-流式-sse-链路)
5. [实现计划](#5-实现计划)

---

## 1. 新增 API 端点

### 1.1 `POST /ask` — 非流式问答

```
POST /ask
Content-Type: application/json

{
  "question": "小青龙汤的组成是什么？",
  "k": 5,
  "stream": false
}
```

**响应 200：**

```json
{
  "answer": "小青龙汤由麻黄、芍药、细辛、干姜、甘草、桂枝、五味子、半夏组成。",
  "sources": [
    {"id": "doc-001", "title": "方剂学·小青龙汤", "score": 0.92, "snippet": "小青龙汤：麻黄、芍药、细辛、干姜、甘草...、半夏各三两..."},
    {"id": "doc-002", "title": "伤寒论·太阳病篇", "score": 0.85, "snippet": "伤寒表不解，心下有水气，干呕发热而咳..."}
  ]
}
```

**Request 参数：**

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `question` | string | (必填) | 用户问题 |
| `k` | integer | 5 | 检索参考文档数，范围 1–20 |
| `stream` | boolean | false | 是否 SSE 流式输出 |

**Response 字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `answer` | string | LLM 生成的回答 |
| `sources` | array | 检索到的参考文档片段列表 |
| sources[].id | string | 文档 canonical_id |
| sources[].title | string | 文档标题（来自 documents.title） |
| sources[].score | number | 向量相似度 [0, 1] |
| sources[].snippet | string | 匹配段落摘要（前 200 字） |

### 1.2 `POST /ask` — 流式 SSE

```
POST /ask
Content-Type: application/json

{
  "question": "小青龙汤的组成是什么？",
  "k": 5,
  "stream": true
}
```

**响应 200** with `Content-Type: text/event-stream`：

```
event: sources
data: {"sources": [{"id":"doc-001","title":"方剂学·小青龙汤","score":0.92,"snippet":"..."}, ...]}

event: token
data: {"token": "小"}

event: token
data: {"token": "青"}

event: token
data: {"token": "龙"}

...

event: done
data: {"finish_reason": "stop"}
```

**SSE 事件类型：**

| 事件名 | 触发时机 | data 格式 | 说明 |
|--------|----------|-----------|------|
| `sources` | 检索完成、LLM 开始输出前 | `{"sources": [...]}` | 一次性推送所有来源 |
| `token` | LLM 每生成一个 token | `{"token": "..."}` | 逐 token 推送，前端逐字渲染 |
| `done` | LLM 输出完毕 | `{"finish_reason": "stop"}` | 标记流结束 |
| `error` | 任何阶段出错 | `{"error": "..."}` | 错误事件，流将关闭 |

### 1.3 错误响应

```json
// 400 - 参数校验失败
{"error": "question 必填"}
// 503 - LLM/检索不可用
{"error": "LLM service unavailable: <detail>"}
```

---

## 2. RAGEngine 类设计

### 2.1 文件位置

```
khub/llm/
├── __init__.py      # LLMProvider 协议 + RemoteLLMProvider（已有）
└── rag.py           # <-- 新增：RAGEngine
```

### 2.2 类签名

```python
class RAGEngine:
    def __init__(self, store: Store, retriever: Optional[Retriever] = None,
                 llm: Optional[LLMProvider] = None):
        self.store = store
        self.retriever = retriever or Retriever(store)
        self.llm = llm or get_provider()
```

### 2.3 核心方法

#### `def ask(question: str, k: int = 5) -> tuple[str, list[dict]]`

完整同步 RAG 管道，返回 `(answer_text, sources_list)`。

```python
def ask(self, question: str, k: int = 5) -> tuple[str, list[dict]]:
    # 1. 向量检索
    hits = self.retriever.search_similar(question, k=k)
    
    # 2. 取文档内容与标题
    sources = self._fetch_sources(hits)
    
    # 3. 组装 context + prompt
    context = self._assemble_context(sources)
    prompt = self._build_prompt(question, context)
    
    # 4. LLM 生成回答
    answer = self.llm.complete(prompt, temperature=0.3)
    
    return answer, sources
```

#### `def ask_stream(question: str, k: int = 5) -> Generator[dict, None, None]`

流式版本，逐事件 yield。

```python
def ask_stream(self, question: str, k: int = 5) -> Generator[dict, None, None]:
    # 1. 检索
    hits = self.retriever.search_similar(question, k=k)
    sources = self._fetch_sources(hits)
    
    # 2. 先 yield sources 事件
    yield {"event": "sources", "data": {"sources": sources}}
    
    # 3. 组装 prompt
    context = self._assemble_context(sources)
    prompt = self._build_prompt(question, context)
    
    # 4. 流式 LLM 调用（需要 RemoteLLMProvider 新增 complete_stream）
    for token in self.llm.complete_stream(prompt, temperature=0.3):
        yield {"event": "token", "data": {"token": token}}
    
    yield {"event": "done", "data": {"finish_reason": "stop"}}
```

### 2.4 辅助方法

#### `_fetch_sources(hits) -> list[dict]`

将 `[(doc_id, score)]` 转换为包含标题和摘要的富来源列表。

```python
def _fetch_sources(self, hits: list[tuple[str, float]]) -> list[dict]:
    sources = []
    for doc_id, score in hits:
        doc = self.store.get_document(doc_id)
        vers = self.store.get_versions(doc_id)
        content = vers[-1]["content"] if vers else ""
        
        # 截取前 200 字作为 snippet（中文字符）
        snippet = content[:200].strip()
        # 去空、去换行
        snippet = " ".join(snippet.split())
        
        sources.append({
            "id": doc_id,
            "title": doc["title"] if doc else doc_id,
            "score": round(score, 4),
            "snippet": snippet,
        })
    return sources
```

#### `_assemble_context(sources, max_chars=6000) -> str`

将多篇文档拼成 LLM context 文本。**按相似度降序排列**，优先保留高相关文档。

截断策略（三层）：

1. **按文档截断**：每篇文档截取前 `max_chars // len(sources)` 字符，保证每篇都能贡献参考
2. **整体截断**：如果拼接后超过 `max_chars`，从得分最低的文档开始逐步缩短其截断长度
3. **底线保护**：至少保留每篇文档的前 100 字符，避免完全丢失低分文档

```python
def _assemble_context(self, sources: list[dict], max_chars: int = 6000) -> str:
    per_doc = max(400, max_chars // max(len(sources), 1))
    parts = []
    for src in sources:
        # 从文档内容截取（实际需从 Store 重新取全文）
        vers = self.store.get_versions(src["id"])
        content = vers[-1]["content"] if vers else ""
        truncated = content[:per_doc].strip()
        parts.append(f"--- 文档：{src['title']} (相似度: {src['score']}) ---\n{truncated}")
    return "\n\n".join(parts)
```

> **说明**：现有依赖中没有 tokenizer，使用字符数作为估算。6,000 中文字符 ≈ 8,000–12,000 tokens（中文 LLM 经验值），主流本地模型（如 Qwen2.5-7B）的 context window 至少 32k，此处留有余量。

#### `_build_prompt(question, context) -> str`

```python
PROMPT_TEMPLATE = """你是一个知识问答助手。请根据以下参考文档，用中文回答用户的问题。

如果参考文档不足以回答，请如实说"资料中未找到相关信息"，不要编造。

参考文档：
{context}

用户问题：{question}

请给出准确、简洁的回答："""

def _build_prompt(self, question: str, context: str) -> str:
    return PROMPT_TEMPLATE.format(question=question, context=context)
```

### 2.5 RemoteLLMProvider 扩展：流式补全

在 `khub/llm/__init__.py` 的 `RemoteLLMProvider` 中新增：

```python
def complete_stream(self, prompt: str, **kwargs):
    """流式补全，逐 token yield。使用 SSE 协议解析 /v1/chat/completions 的流式响应。"""
    endpoint = self.url + "/v1/chat/completions"
    body = {
        "model": self.model or "default",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": kwargs.get("temperature", 0.3),
        "stream": True,
    }
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if self.api_key:
        headers["Authorization"] = f"Bearer {self.api_key}"
    req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
    
    with urllib.request.urlopen(req, timeout=self.timeout) as resp:
        buffer = ""
        while True:
            chunk = resp.read(1).decode("utf-8", errors="replace")
            if not chunk:
                break
            buffer += chunk
            if buffer.endswith("\n\n"):
                for line in buffer.strip().split("\n"):
                    if line.startswith("data: "):
                        payload = line[6:]
                        if payload.strip() == "[DONE]":
                            return
                        obj = json.loads(payload)
                        delta = obj.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                buffer = ""
```

> **设计理由**：OpenAI 兼容的 LLM API（llama.cpp、vLLM、Ollama 等）统一使用 SSE 协议返回流式结果，以 `data:` 前缀传输 JSON。逐字节读取确保不 miss 边界。这里也可以改用 `resp.readline()` 逐行读取，效率更高且代码更简洁。实现时优先使用 `readline()` 方式。

### 2.6 LLMProvider 协议扩展

在 `LLMProvider` Protocol 中新增可选方法，避免破坏现有 NoOpProvider：

```python
@runtime_checkable
class LLMProvider(Protocol):
    def complete(self, prompt: str, **kwargs) -> str:
        ...
    
    def complete_stream(self, prompt: str, **kwargs):
        """流式补全，返回 Generator[str, None, None]；非流式 Provider 可以不实现。"""
        ...
        if False:  # 仅满足语法
            yield ""
    
    def embed(self, text: str) -> list[float]:
        ...
```

NoOpProvider 的 `complete_stream` 实现为空 generator。

---

## 3. 前端对话框

### 3.1 交互方式

在现有页面右下角增加一个 **浮动气泡按钮**，点击展开/收起对话框，类似 ChatGPT 侧边栏。

### 3.2 UI 布局

```
┌─────────────────────────────────────────────────┐
│  kHUB · 个人知识中枢          [按钮区域]        │
├─────────────────────────────────┬───────────────┤
│                                 │ ┌───────────┐ │
│  主内容区域（搜索/文档列表）     │ │ ✨ AI 助手 │ │
│                                 │ │           │ │
│                                 │ │ ┌───────┐ │ │
│                                 │ │ │用户问题│ │ │
│                                 │ │ ├───────┤ │ │
│                                 │ │ │AI 回答 │ │ │
│                                 │ │ │ + 来源 │ │ │
│                                 │ │ └───────┘ │ │
│                                 │ │           │ │
│                                 │ │ [输入框][发送]│
│                                 │ └───────────┘ │
│                                 │               │
│                       [🤖 浮动按钮]            │
└─────────────────────────────────┴───────────────┘
```

### 3.3 CSS 样式

- **浮动按钮**：固定在右下角（`position: fixed; bottom: 24px; right: 24px`），圆形，背景色 `#2563eb`
- **对话框面板**：固定在右下角（`position: fixed; bottom: 88px; right: 24px`），宽度 380px（移动端 100vw），高度 560px（移动端 70vh），白色背景，圆角 12px，阴影
- **消息气泡**：用户消息右对齐（蓝色背景 `#2563eb`），AI 消息左对齐（灰色背景 `#f3f4f6`），引用来源用小字灰色横向排列
- **输入区**：底部固定，flex row（输入框 + 发送按钮）
- **流式输出**：AI 消息气泡中用一个 `<span id="streaming-text">` 动态追加内容

### 3.4 JavaScript 逻辑

```javascript
// 全局状态
const state = { open: false, streaming: false, abortController: null };

// 切换对话框显示
function toggleDialog() { state.open = !state.open; render(); }

// 发送消息
async function ask() {
  const q = input.value.trim();
  if (!q || state.streaming) return;
  
  // 添加用户消息气泡
  addBubble('user', q);
  input.value = '';
  
  // 创建 AI 消息气泡，预留流式容器
  const aiBubble = addBubble('ai', '', true); // {streaming: true}
  
  if (useStreaming) {
    // 流式模式：fetch + ReadableStream
    state.streaming = true;
    try {
      const resp = await fetch('/ask', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({question: q, k: 5, stream: true}),
      });
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      
      while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, {stream: true});
        
        // 解析 SSE 事件
        const events = buffer.split('\n\n');
        buffer = events.pop() || '';
        for (const block of events) {
          const lines = block.split('\n');
          const eventLine = lines.find(l => l.startsWith('event: '));
          const dataLine = lines.find(l => l.startsWith('data: '));
          if (!dataLine) continue;
          
          const event = eventLine ? eventLine.slice(7).trim() : '';
          const data = JSON.parse(dataLine.slice(6));
          
          if (event === 'sources') {
            renderSources(data.sources);
          } else if (event === 'token') {
            appendToStreaming(data.token);
          } else if (event === 'done') {
            // 流结束
          } else if (event === 'error') {
            appendToStreaming('[错误: ' + data.error + ']');
          }
        }
      }
    } finally {
      state.streaming = false;
    }
  } else {
    // 非流式模式
    const resp = await fetch('/ask', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question: q, k: 5, stream: false}),
    });
    const data = await resp.json();
    aiBubble.querySelector('.answer-text').textContent = data.answer;
    renderSources(data.sources);
  }
}
```

### 3.5 来源引用渲染

在 AI 消息气泡底部增加引用行：

```html
<div class="sources" style="margin-top:8px;font-size:12px;color:#666">
  📖 参考来源：
  <a href="#" onclick="loadDoc('doc-001');return false" title="方剂学·小青龙汤">doc-001</a>
  <span style="color:#999">(0.92)</span>
  ...
</div>
```

点击来源链接，在主内容区域加载该文档详情（复用已有的 `loadDoc` 函数）。

### 3.6 移动端适配

- `<meta name="viewport">` 已在 header 中
- `@media (max-width: 640px)` 时对话框宽度 `calc(100vw - 32px)`、高度 `70vh`
- 浮动按钮尺寸 48px → 40px
- 消息字体 14px → 13px

---

## 4. 流式 SSE 链路

### 4.1 端到端数据流

```
浏览器 <--SSE-- http.server.Handler <--Generator-- RAGEngine <--SSE-- RemoteLLMProvider <--HTTP-- LLM API
```

每一层都保持流特性：

1. **RemoteLLMProvider.complete_stream()**：逐字节读取 LLM API 的 SSE 响应，逐 token yield
2. **RAGEngine.ask_stream()**：先 yield sources 事件，然后委托给 LLM 的流式 generator
3. **HTTP Handler**：逐事件写入 `self.wfile.flush()`，保持 SSE 连接不缓冲
4. **浏览器**：`fetch()` + `ReadableStream` 解析 SSE，逐字追加 DOM

### 4.2 HTTP Handler SSE 实现

在 `api.py` 的 Handler 中新增 SSE 写入方法：

```python
def _send_sse(self, app, body):
    """处理 SSE 流式请求。body: dict"""
    from .llm.rag import RAGEngine
    engine = RAGEngine(app.store)
    
    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream")
    self.send_header("Cache-Control", "no-cache")
    self.send_header("Connection", "keep-alive")
    self.send_header("Access-Control-Allow-Origin", "*")
    self.end_headers()
    
    for event in engine.ask_stream(body["question"], k=body.get("k", 5)):
        ev = event["event"]
        data = json.dumps(event["data"], ensure_ascii=False)
        self.wfile.write(f"event: {ev}\ndata: {data}\n\n".encode("utf-8"))
        self.wfile.flush()
```

### 4.3 超时与中断

- API handler 层不主动超时（依赖底层 LLM API 的超时，默认 30s）
- 前端 `AbortController` 可中断 fetch（点击"停止"按钮时 `controller.abort()`）
- Handler 捕获 `BrokenPipeError`/`ConnectionResetError` 时静默结束流

---

## 5. 实现计划

### 第 1 步：RAGEngine 核心（非流式）

**文件修改：**
- `khub/llm/rag.py` — 新建，约 120 行
- `khub/llm/__init__.py` — 协议扩展约 5 行（`complete_stream` protocol 声明）

**测试策略：**
- 单元测试 `tests/test_rag.py`，mock `Retriever` + `LLMProvider`
- 验证 context 组装逻辑（空 sources、单篇、多篇、超长截断）
- 验证 prompt 模板输出格式

### 第 2 步：POST /ask 端点（非流式）

**文件修改：**
- `khub/api.py` — `dispatch()` 中新增 POST /ask 路由，约 15 行

**测试策略：**
- `test_api.py` 中新增 `test_post_ask`，mock RAGEngine
- 验证 200/400 响应格式
- 使用 `test_api_systems.py` 做集成测试（有真实 DB）

### 第 3 步：RemoteLLMProvider 流式补全

**文件修改：**
- `khub/llm/__init__.py` — `RemoteLLMProvider.complete_stream()` 新增，约 40 行
- `NoOpProvider.complete_stream()` 约 5 行

**测试策略：**
- mock `urllib.request.urlopen` 返回预定义的 SSE payload，验证 yield 出的 token 顺序
- 覆盖 `[DONE]` 终止、异常断开、空响应

### 第 4 步：RAGEngine 流式 + POST /ask SSE

**文件修改：**
- `khub/llm/rag.py` — 新增 `ask_stream()` 约 15 行
- `khub/api.py` — Handler 中新增 `_send_sse()` 约 30 行，dispatch 中 SSE 路由约 5 行

**测试策略：**
- mock `complete_stream` generator，验证 SSE 输出格式
- 集成测试：启动 http.server，`urllib.request` 发 POST 读流式响应

### 第 5 步：前端对话框

**文件修改：**
- `khub/api.py` — `_html_page()` 中新增 CSS/HTML/JS，约 200 行

**测试策略：**
- 纯前端逻辑，手动验证浏览器交互
- 确认流式逐字渲染不卡顿
- 确认移动端布局正确

### 依赖图

```
Step 1 (RAGEngine 核心)
    │
    ├── Step 2 (POST /ask 非流式) ───── 可独立发布 v1
    │
    ├── Step 3 (LLM 流式补全)
    │       │
    │       └── Step 4 (RAGEngine 流式 + SSE 端点)
    │
    └── Step 5 (前端对话框) ─────────── 依赖 Step 2 或 Step 4
```

建议迭代顺序：1 → 2 → 5（先出 v1 可用），然后 3 → 4（叠加流式能力）。

### 代码量估算

| 步骤 | 文件 | 新增行数 |
|------|------|---------|
| 1 | `khub/llm/rag.py` | ~120 |
| 1 | `khub/llm/__init__.py` | ~5 |
| 2 | `khub/api.py` | ~15 |
| 3 | `khub/llm/__init__.py` | ~45 |
| 4 | `khub/llm/rag.py` | ~15 |
| 4 | `khub/api.py` | ~35 |
| 5 | `khub/api.py` (`_html_page()`) | ~200 |
| **合计** | | **~435** |

### 测试文件

| 测试文件 | 测试内容 | 预估行数 |
|----------|---------|---------|
| `tests/test_rag.py` | RAGEngine 单元测试 | ~100 |
| `tests/test_rag_stream.py` | 流式相关测试 | ~80 |

> **不新增依赖**：stdlib `urllib` + `http.server` + `json` 已满足全部需求。
> **不修改 pyproject.toml**：`sqlite-vec` 和 `PyYAML` 是已有依赖，不使用新包。

---

## 附录

### A. 环境变量（全部已存在，无需新增）

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `KHUB_LLM_URL` | LLM API 地址 | (空，使用 NoOpProvider) |
| `KHUB_LLM_API_KEY` | LLM API 密钥 | (空) |
| `KHUB_LLM_MODEL` | LLM 模型名 | (空，由服务端默认) |
| `KHUB_EMBEDDING_URL` | 嵌入 API 地址 | (空，使用本地 n-gram) |
| `KHUB_EMBED_DIM` | 向量维度 | (自动检测) |
| `KHUB_EMBED_API_KEY` | 嵌入 API 密钥 | (空) |
| `KHUB_EMBED_MODEL` | 嵌入模型名 | (空) |

### B. 现有 /semantic 端点与 /ask 的关系

- `/semantic` 仅返回 `(doc_id, score)`，是纯检索
- `/ask` 在内部调用 `/semantic` 相同的 `search_similar`，但多出：取文档内容、组装 context、调用 LLM 生成回答
- 两个端点保持独立，`/semantic` 不改动

### C. 安全考虑

- SSE 端点不做鉴权（继承项目现有模式）
- 输入长度限制：`question` 最大 2000 字符，`k` 最大 20
- LLM prompt 注入：用户问题作为 prompt 的一部分输入 LLM，这是 RAG 的正常使用方式。不做额外 sanitize
