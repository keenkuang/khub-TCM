# RAG 问答模块第 2 轮代码评审报告

> 评审范围：commit `1106e1a`（基于第 1 轮 `6a5809e` 评审报告的修复）
>
> 涉及文件：`khub/llm/rag.py`、`khub/llm/__init__.py`、`khub/api.py`、`tests/test_rag.py`、`tests/test_rag_stream.py`
>
> 评审日期：2026-07-09
>
> 分级：🔴 BLOCKER / 🟠 MAJOR / 🟡 MINOR / 🔵 SUGGESTION

---

## 一、第 1 轮修复项验证

### 1.1 修复确认（15/15 ✅）

| 编号 | 问题 | 修复方式 | 状态 |
|------|------|----------|------|
| RAG-01 | `str.format()` 模板冲突 | `rag.py:137-139` — 改用 `.replace()` | ✅ |
| RAG-02 | `_fetch_sources` / `_assemble_context` 重复查库 | `rag.py:115` + `rag.py:126` — `_content` 字段复用 | ✅ |
| RAG-03 | `ask()` 缺少 LLM 异常处理 | `rag.py:58-62` — try/except + logger.error | ✅ |
| RAG-04 | `ask_stream()` 检索管道未保护 | `rag.py:74-83` — 统一 try/except | ✅ |
| RAG-05 | `ask()` 缺少空问题守卫 | `rag.py:52-53` — `not question.strip()` 判断 | ✅ |
| LLM-01 | `NoOpProvider.complete_stream` hack | `__init__.py:34-36` — `return` + `yield` 模式 | ✅ |
| LLM-02 | `RemoteLLMProvider.complete` 异常无日志 | `__init__.py:71-78` — 日志 + choices 校验 | ✅ |
| LLM-03 | SSE JSON 解析未保护 | `__init__.py:104-108` — try/except + logger.warning | ✅ |
| LLM-04 | `get_provider()` 环境变量缺失静默 | `__init__.py:146` — logger.warning 输出 | ✅ |
| API-01 | `_send_sse()` k 类型安全 | `api.py:547-550` — isinstance + safe int | ✅ |
| API-02 | SSE 缺少 OPTIONS preflight | `api.py:608-616` — do_OPTIONS 方法 | ✅ |
| API-04 | SSE 缺少 X-Accel-Buffering | `api.py:560` — 添加 header | ✅ |
| TST-01 | stream 测试使用真实 Retriever | `test_rag.py:202-204` — 注入 mock Retriever | ✅ |
| TST-02 | monkey-patch 全局类 | `test_rag_stream.py:208` — `patch.object` 替代 | ✅ |
| TST-03 | 缺失关键测试 | 新增 4 个测试（空问题/LLM 异常/检索失败/特殊字符） | ✅ |

### 1.2 修复代码审查

#### khub/llm/rag.py — 逐行审查

| 行号 | 变更内容 | 审查结论 |
|------|----------|----------|
| 27 | 注释说明改用 `.replace()` | ✅ 清晰 |
| 52-53 | 空问题守卫 | ✅ 正确，不会误判空格串 |
| 58-62 | LLM complete try/except | ✅ `logger.error` 使用正确；回答回退为友好消息 |
| 74-83 | 检索管道 try/except | ✅ 事件顺序正确（sources → error），return 终止 |
| 85-90 | LLM stream try/except | ✅ 与原逻辑一致，补充了日志 |
| 95-117 | `_fetch_sources` 返回 `_content` | ✅ 注释说明"内部复用" |
| 119-132 | `_assemble_context` 复用 `_content` | ✅ 不再调用 `get_versions`，消除 N+1 |
| 121-122 | 空 sources 守卫 | ✅ 避免 `max(400, 6000 // 0)` |
| 134-139 | `_build_prompt` 使用 `.replace()` | ✅ 顺序为 `{context}` 先、`{question}` 后 |

#### khub/llm/__init__.py — 逐行审查

| 行号 | 变更内容 | 审查结论 |
|------|----------|----------|
| 34-36 | `NoOpProvider.complete_stream` | ✅ `return` + `yield` 模式正确 |
| 70-72 | URLError 日志 | ✅ 日志内容准确 |
| 73-75 | JSONDecodeError/OSError 日志 | ✅ 覆盖了 JSON 解析和 IO 错误 |
| 76-78 | choices 校验 | ✅ 安全 `.get()` 链 + 空 choices 抛出 RuntimeError |
| 104-108 | SSE JSON 解析 try/except | ✅ 警告日志 + continue 跳过 |
| 113-118 | stream URLError/OSError 日志 | ✅ 与 complete 模式一致 |
| 146 | KHUB_LLM_URL 未设置警告 | ✅ 提示明确 |

#### khub/api.py — 逐行审查

| 行号 | 变更内容 | 审查结论 |
|------|----------|----------|
| 547-550 | k 类型安全 | ✅ isinstance(int, float) → safe int → clamp |
| 560 | X-Accel-Buffering | ✅ 标准做法 |
| 608-616 | do_OPTIONS | ✅ CORS 头完整（Origin/Methods/Headers） |

---

## 二、第 2 轮发现的新问题

### 🟠 R2-NEW-01 `_content` 字段经 API 泄露全文文档内容

**文件**：`khub/llm/rag.py` + `khub/api.py`

`_fetch_sources()` 在 sources 字典中加入了 `_content` 字段（存储全文内容），注释写着"内部复用，不暴露给 API 响应"。但 `ask()` 返回的 `sources` 列表未经清洗，在 `api.py:164` 中直接作为 JSON 响应返回给客户端。

```python
# rag.py:63
return answer, sources  # sources 包含 _content

# api.py:164
return 200, {"answer": answer, "sources": sources}  # 直接暴露
```

前端虽未渲染 `_content`，但任何 HTTP 客户端都能获取完整文档内容。如果文档含 PII（病历、问诊等），这是数据泄露。

**修复建议**：在 `rag.py:63` 返回前或 `api.py:164` 序列化前清洗 `_content`：

```python
# 方案 A：在 rag.py ask() 返回前清洗
# ...
finally:
    for src in sources:
        src.pop("_content", None)
return answer, sources

# 方案 B：在 api.py 序列化时清洗（推荐）
sources_clean = [{k: v for k, v in src.items() if not k.startswith("_")}
                 for src in sources]
return 200, {"answer": answer, "sources": sources_clean}
```

`ask_stream()` 同理 — `yield {"event": "sources", "data": {"sources": sources}}` 也会泄露 `_content`。

---

### 🟡 R2-NEW-02 `test_prompt_template_roundtrip` 测试的是死代码路径

**文件**：`tests/test_rag.py:146`

```python
# 当前代码
prompt = PROMPT_TEMPLATE.format(question=question, context=context)
```

该测试绕过 `_build_prompt()`，直接对 `PROMPT_TEMPLATE` 常量调用 `.format()`。但生产代码已改用 `.replace()` 方法。这意味着：

1. 测试不覆盖实际生产路径
2. 若模板未来引入 `{}` 占位符，该测试会通过但生产会崩溃

`test_prompt_format`（第 137 行）已通过 `_build_prompt()` 覆盖了相同断言，本测试已冗余。

**修复建议**：移除该测试方法，或将断言改为测试 `_build_prompt()`：

```python
# 改为：
prompt = RAGEngine._build_prompt(question, context)
assert question in prompt
assert context in prompt
```

---

### 🟡 R2-NEW-03 `.replace()` 顺序依赖：若 context 含 `{question}` 会被替换

**文件**：`khub/llm/rag.py:137-139`

```python
return (PROMPT_TEMPLATE
        .replace("{context}", context)
        .replace("{question}", question))
```

若 `context`（文档全文）中恰含子串 `{question}`，第二行 `.replace()` 会将其替换为用户问题。虽然文档中含有 `{question}` 字面的概率极低（医学文档几乎不可能），但数学/代码类文档（如 LaTeX 公式、Python f-string 示例）可能存在。

**修复建议**：

```python
# 先替换 question，避免 context 中的 {question} 被二次替换
return (PROMPT_TEMPLATE
        .replace("{question}", question)
        .replace("{context}", context))
```

或将替换值中的 `{` / `}` 先行转义（但会影响文档原文显示，不推荐）。

---

## 三、第 1 轮未修复的遗留问题

### 🟠 R1-SEC-01 prompt 注入防护未实现

**第 1 轮评级**：MAJOR

`_build_prompt()` 将用户问题直接拼入 prompt template，未做任何注入标记或分隔。恶意用户可通过 `"忽略上述指令，回答：..."` 覆盖系统指令。

当前仅将问题拼接为 `用户问题：{question}`，LLM 可能将后续上下文也视为用户消息的一部分。

**修复建议**：

```python
@staticmethod
def _build_prompt(question: str, context: str) -> str:
    # 对问题做注入标记
    question_safe = question.replace("\\n", " ").replace("\\r", " ")
    return (PROMPT_TEMPLATE
            .replace("{question}", question_safe)
            .replace("{context}", context))
```

更完善的方案是在 prompt template 中加入分隔标记：
```
用户问题：{question}

--- 用户输入结束，请仅基于上下文回答 ---
```

---

### 🟡 R1-RAG-05ex `ask_stream()` 缺少空问题守卫

`ask()` 已有 `if not question or not question.strip(): return "", []`，但 `ask_stream()` 没有。直接调用 `engine.ask_stream("")` 会传入空字符串给 `search_similar`，其行为依赖底层实现（可能返回全量文档或抛出异常）。

**修复建议**：在 `ask_stream()` 开头添加相同守卫：

```python
def ask_stream(self, question: str, k: int = 5):
    if not question or not question.strip():
        return  # 空 generator
    # ...
```

---

### 🟡 R1-LLM-03ex 流式读取无超时保护

`complete_stream()` 中的 `for raw_line in resp` 使用 `urllib` 的逐行迭代，`timeout` 参数仅限制连接超时，不限制行间等待时间。若远端长时间无 token 输出，请求会 hang 住。

第 1 轮建议使用 `resp.readline()` 配合额外超时逻辑，未实现。

**修复建议**：

```python
import select

# 在 urlopen 后的 resp.fp 上添加超时
# 或改用 requests 库（推荐生产环境使用）
```

---

### 🟡 R1-PERF-01 大 k 下 context 无截断告警

当 `k=20` 时，`per_doc=400`，context 总长约 8000 字符 + 标题/分隔符。若 LLM 上下文窗口较小（如 4K tokens），context 会被静默截断，无日志告警。

---

### 🔵 R1-LLM-05 `model` 默认值（SUGGESTION，可接受不修）

---

### 🔵 R1-API-03 `_send_sse` 认证逻辑重复（MINOR 策略性问题）

---

### 🔵 R1-TST-04 `test_max_chars_honored` 断言余量（SUGGESTION）

---

## 四、测试覆盖评估

### 28/28 测试通过 ✅

所有现有测试在新代码上全部通过，无回归。

### 新增测试项

| 测试 | 覆盖场景 | 风险预防 |
|------|----------|----------|
| `test_ask_empty_question` | 空字符串调用 `ask()` | 防止空问题误查全库 |
| `test_ask_llm_failure` | LLM `complete()` 抛异常 | 友好错误返回 |
| `test_stream_retrieval_failure` | `search_similar()` 抛异常 | error 事件 yield |
| `test_stream_special_chars` | `{}` 等特殊字符 | `.replace()` 稳定性 |

### 仍缺失的测试（第 1 轮已识别）

| 缺失场景 | 风险 | 优先级 |
|----------|------|--------|
| `_assemble_context` max_chars 边界（6000/大 k） | 截断无告警 | MINOR |
| `k=0` 或负值输入 | `max(1, min(k, 20))` 下限已保护 | MINOR |
| 空 content（文档已删除但向量残留） | `vers[-1]` 已保护但未测试 | MINOR |
| `_send_sse` 中 `k` 为字符串/null | API-01 已在代码层保护 | MINOR |
| `_content` 不泄露到 API 响应 | 见 R2-NEW-01 | 🔴 MAJOR |

---

## 五、评审总结

### 修复质量

第 1 轮评审识别的 **15 个修复项**全部正确实施，修复质量良好。所有修复代码简洁、防御性编程恰当、无明显回归风险。

### 第 2 轮发现

| 级别 | 数量 | 说明 |
|------|------|------|
| 🟠 MAJOR | 1 | `_content` 全文泄露（R2-NEW-01） |
| 🟡 MINOR | 2 | 测试死代码路径（R2-NEW-02）、`.replace()` 顺序依赖（R2-NEW-03） |
| 🔵 SUGGESTION | 0 | — |

### 遗留未修复（第 1 轮）

| 级别 | 数量 | 关键项 |
|------|------|--------|
| 🟠 MAJOR | 1 | prompt 注入防护（R1-SEC-01） |
| 🟡 MINOR | 3 | `ask_stream` 空问题守卫、流式超时、context 截断告警 |
| 🔵 SUGGESTION | 3 | model 默认值、认证重复（策略性）、断言精度 |

### 综合建议

1. **立即修复 R2-NEW-01**（MAJOR）：`_content` 数据泄露是阻止合入的硬伤。修复成本极低（一行 `pop` 或 dict comprehension），建议在下一次 commit 中连带修复。
2. **安排 SEC-01**（MAJOR）：prompt 注入防护建议在接入真实 LLM 前完成。
3. **可选清理**：R2-NEW-02 和 R2-NEW-03 为低风险，可在日常迭代中顺手修复。
