# 最终修复验证报告

> **评审范围**: commit `1dbedfe` (branch m1) — `khub/llm/rag.py`
> **评审类型**: 聚焦验证 · 修复 commit 回查
> **评审日期**: 2026-07-10
> **被审修复**: CROSS-1 (_clean_sources 位置) + CROSS-3 (空问题守卫)

---

## 1. ask_stream() — `_clean_sources` 放置验证

### 位置评估

当前代码（rag.py:78-85）：

```python
try:
    hits = self.retriever.search_similar(question, k=k)
    sources = self._fetch_sources(hits)
    context = self._assemble_context(sources)          # (1) 首次组装：有 _content ✅
    self._clean_sources(sources)                       # (2) 清洗：移除 _content ✅
    yield {"event": "sources", "data": {"sources": sources}}  # (3) yield：已清洗 ✅
    context = self._assemble_context(sources)           # (4) 二次组装：_content 已消失 ❌
    prompt = self._build_prompt(question, context)      # (5) prompt：context 为空字符串 ❌
```

**结论：修复不完整 — CROSS-1 被误认为已修复，但 `context` 变量被二次覆盖。**

| 步骤 | 结果 |
|------|------|
| (1) 首次 `_assemble_context` 在 `_clean_sources` 之前 | ✅ **正确** — `_content` 存在 |
| (2) `_clean_sources` 移除了 `_content` | ✅ **正确** — 防止 API 泄露 |
| (3) `yield sources` | ✅ **正确** — 无 `_content` |
| **(4) 二次 `_assemble_context`** | ❌ **错误** — 此时 `_content` 已被移除，返回 `""` |
| (5) `prompt` 使用空 context | ❌ **错误** — LLM 仍收到无文档内容的 prompt |

**根因分析**：commit `1dbedfe` 在 `_clean_sources` 之前插入了第 (1) 行 `context = _assemble_context(sources)`，但**遗漏删除**原有的第 (4) 行（原代码中唯一的 `_assemble_context` 调用点）。变量被二次赋值覆盖。

### 修复方案

删除第 84 行的冗余调用，直接复用第 81 行已正确的 `context`：

```python
            context = self._assemble_context(sources)
            self._clean_sources(sources)
            yield {"event": "sources", "data": {"sources": sources}}
            # ← 删除此处的 context = self._assemble_context(sources)
            prompt = self._build_prompt(question, context)
```

---

## 2. ask_stream() — 空问题守卫验证

当前代码（rag.py:75-77）：

```python
if not question or not question.strip():
    yield {"event": "error", "data": {"error": "问题不能为空"}}
    return
```

### 逐项评估

| 检查项 | 结果 |
|--------|------|
| 空字符串 `""` `not question` 触发 | ✅ |
| 纯空白 `"   "` `not question.strip()` 触发 | ✅ |
| `None`（虽然 typed as str, 防御性兜底） | ✅ |
| `yield error` 后 `return` 不继续执行 | ✅ — generator 正常终止 |
| `yield` 在 `return` 之前，事件被消费 | ✅ — generator 在 `return` 前 yield 出的值有效 |
| 事件格式与文档一致 | ✅ — `{"event": "error", "data": {"error": "..."}}` |

**结论：CROSS-3 已正确修复，无遗留问题。**

---

## 3. ask() — `_clean_sources` 放置验证

当前代码（rag.py:50-64）：

```python
def ask(self, question: str, k: int = 5) -> tuple[str, list[dict]]:
    if not question or not question.strip():
        return "", []
    hits = self.retriever.search_similar(question, k=k)
    sources = self._fetch_sources(hits)
    context = self._assemble_context(sources)     # 有 _content ✅
    prompt = self._build_prompt(question, context)
    try:
        answer = self.llm.complete(prompt, ...)
    except Exception as exc:
        ...
    self._clean_sources(sources)                  # LLM 完成后清洗 ✅
    return answer, sources
```

| 检查项 | 结果 |
|--------|------|
| 顺序：fetch → assemble_context → clean_sources → return | ✅ **完全正确** |
| `_clean_sources` 在 `llm.complete` 之后 | ✅ |
| 空问题守卫在早期 return | ✅ |

**结论：`ask()` 无问题，CROSS-1 仅影响 `ask_stream()`。**

---

## 4. 回归风险扫描

| 项目 | 状态 | 说明 |
|------|------|------|
| `ask()` 不变 | ✅ | 未在本次 commit 中修改 |
| 异常路径（retrieval 失败） | ✅ | `_clean_sources` 在 try 块内，失败时不会执行到 |
| 异常路径（LLM stream 失败） | ✅ | 在单独的 try 块中，不受影响 |
| `_assemble_context` 被反复调用 | ⚠️ 存在但影响小 | 第 81 行 + 第 84 行 → 修复后只剩一次 |
| 测试未发现此回归 | ⚠️ 测试缺口 | 见第 6 节 |

---

## 5. `ask()` vs `ask_stream()` 顺序一致性

| 阶段 | `ask()` | `ask_stream()` (当前) | `ask_stream()` (修复后) |
|------|---------|----------------------|------------------------|
| fetch sources | ✅ | ✅ | ✅ |
| assemble_context | ✅ 第 56 行 | ✅ 第 81 行 | ✅ |
| clean_sources | ✅ 第 63 行 (LLM 完成后) | ✅ 第 82 行 (assemble 后, yield 前) | ✅ |
| yield/return sources | ✅ (cleaned) | ✅ (cleaned) | ✅ |
| build_prompt | ✅ (有上下文) | ❌ (空上下文) | ✅ (有上下文) |

`ask()` 和 `ask_stream()` 在 `clean_sources` 时机上本就不同：
- `ask()`：在 `llm.complete` 之后清洗 → API 响应中 sources 无内部字段
- `ask_stream()`：在 yield sources 之前清洗 → 流式发出去的 sources 已无内部字段，但 prompt 需要在此之前已组装完成

**修复后，两者都将正确使用文档上下文生成回答。**

---

## 6. 测试覆盖缺口

| 文件 | 测试 |
|------|------|
| `tests/test_rag.py` | 无 `ask_stream()` 的 prompt 内容断言 |

**当前 `TestAskStream` 覆盖的事件**：
- `test_stream_events_sequence` — 检查事件顺序，**不检查 prompt 内容**
- `test_stream_error_handling` — 检查 LLM 异常路径
- `test_stream_retrieval_failure` — 检查检索异常路径
- `test_stream_special_chars` — 检查 `{}` 不崩溃，**不检查 prompt 内容**

**缺口**：无测试验证 `ask_stream()` 生成的 prompt 中包含正确的文档上下文。
对比 `TestAsk.test_ask_invokes_llm_complete`，后者至少断言了 `question` 出现在 prompt 中。

**建议补充**（可选，非阻塞）：
```python
def test_stream_prompt_contains_context(self):
    """验证流式 prompt 包含文档内容，不会因提前 clean 导致空 context。"""
    s = _make_store_with_docs()
    llm = _make_fake_llm()
    ret = MagicMock(spec=Retriever)
    ret.search_similar.return_value = [("doc-001", 0.95)]
    engine = RAGEngine(s, retriever=ret, llm=llm)
    # 消费 generator
    list(engine.ask_stream("什么汤？", k=5))
    prompt_arg = llm.complete_stream.call_args[0][0]
    assert "麻黄" in prompt_arg, "prompt 中应有文档内容，而非空上下文"
    assert "方剂学" in prompt_arg
```

---

## 7. 总结

| 原始问题 | 严重度 | 修复状态 |
|----------|--------|----------|
| CROSS-1: `ask_stream()` context 为空 | **BLOCKER** | ⚠️ **未完全修复** — `_clean_sources` 位置修正了，但二次 `_assemble_context` 覆盖了正确的 context |
| CROSS-3: 空问题守卫 | LOW | ✅ **已修复** |
| `ask()` _clean_sources 顺序 | — | ✅ **原代码正确** |

**唯一剩余问题**：`rag.py:84` 的 `context = self._assemble_context(sources)` 应在修复中被删除。

**建议**：删除第 84 行，然后重新运行测试套件确认 `TestAskStream` 全部通过。
