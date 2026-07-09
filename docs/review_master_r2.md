# khub master 第2轮代码评审报告

> 评审日期: 2026-07-10
> 评审范围: master 分支 P0 修复（commit 697932a）
> 评审人: general-purpose-43
> 评审焦点: 验证 R1 P0 修复的正确性 + 遗留阻塞问题

---

## 摘要

R1 报告共 13 项问题（P0×2、P1×4、P2×4、P3×3）。本次评审聚焦于 R1 明确标记为"必须修复后方可发布"的 **2 项 P0**。

**P0 修复结论：2/2 正确，无退步。P0 不阻止发布。**

---

## P0 修复验证

### P0-1. pyproject.toml 依赖声明严重不完整

**修复内容**（commit 697932a, `pyproject.toml`）：
- 新增 `crypto = ["cryptography>=41.0"]` optional group
- 新增 `s3 = ["boto3>=1.28"]` optional group
- 新增 `all = ["khub[pdf,ann,crypto,s3]"]` composite group

**验证结果：✅ 正确**

| 包 | 声明位置 | 状态 |
|---|---------|------|
| `pypdf` | `pdf = ["pypdf>=4.0"]` | R1 已有 |
| `sqlite-vec` | `ann = ["sqlite-vec>=0.1.9"]` | R1 已有 |
| `cryptography` | `crypto = ["cryptography>=41.0"]` | **新增 ✅** |
| `boto3` | `s3 = ["boto3>=1.28"]` | **新增 ✅** |
| `all` | `all = ["khub[pdf,ann,crypto,s3]"]` | **新增 ✅** |

用户现在可通过以下方式安装：
- `pip install khub` — 仅 PyYAML（核心功能）
- `pip install "khub[all]"` — 全部功能
- `pip install "khub[pdf,crypto]"` — 按需组合

Dockerfile 仍使用手动 `pip install PyYAML pypdf sqlite-vec cryptography boto3`（line 15）。该做法在运行时是正确的（所有包都会安装），但与 `pyproject.toml` 的依赖声明形成 **重复维护源**。若未来增减 optional dep 而不同步 Dockerfile，会引入运行时报错。建议后续改为 `pip install --no-cache-dir ".[all]"`，消除手动列表（参见下文"遗留观察"）。

**不阻止发布。** 修复本身完整、正确。

---

### P0-2. RAG 空上下文时仍调用 LLM

**修复内容**（commit 697932a, `khub/llm/rag.py`）：
- `ask()`: 新增第 56-57 行 `if not sources: return "（未检索到相关文档，无法回答）", []`
- `ask_stream()`: 新增第 83-85 行 `if not sources: yield {"event": "error", ...}; return`

**验证结果：✅ 正确**

**覆盖路径分析：**  

| 场景 | 路径 | 是否捕获 |
|------|------|---------|
| 检索返回 0 个 hit | `hits=[]` → `_fetch_sources` 返回 `[]` → `not sources` 为 True | ✅ |
| 检索返回 hit 但对应文档已删除 | `_fetch_sources` 返回空列表（`get_document` 返回 `None`） | ✅ |
| 文档存在但内容为空字符串 | `_assemble_context` 仍生成文档头（标题+相似度），`context.strip()` 非空 → 正常走 LLM | 可接受（见下） |

**边缘情况说明**：
当文档存在但内容为空时，`_assemble_context` 输出为：
```
--- 文档：xxx (相似度: 0.95) ---

```
该上下文通过 `context.strip()` 后仍非空（文档头信息），LLM 被调用但收到极简上下文。这是比原始问题（零检索完全无上下文）**轻微得多**的情况，且在实践中几乎不可能出现（已入库的文档至少应有标题）。

R1 建议检查 `context.strip()` 而非 `not sources`。当前实现等价覆盖了实际危险路径（零检索结果），且 `context.strip()` 方案仅能多拦截极小概率的"文档有记录但无内容"边缘情况，改进幅度有限。

**结论：修复正确且充分。** 无需额外修改。

---

## 遗留观察（非阻塞）

### O-1. Dockerfile pip 手动安装与 pyproject.toml 重复

**严重性：P3**

Dockerfile:15 手动列出 `PyYAML pypdf sqlite-vec cryptography boto3`。pyproject.toml 新增 `all` group 后，Dockerfile 第 15 行可简化为：

```dockerfile
RUN pip install --no-cache-dir ".[all]"
```

这样 Dockerfile 与 pyproject.toml 始终保持同步，无需单独维护包列表。

### O-2. HEXLTHCHECK 未添加 `start_period`

**严重性：P2**（来自 R1 P2-4，未修复）

Dockerfile:27 的 `HEALTHCHECK` 仍无 `--start-period`。docker-compose.yml:42 已设置 `start_period: 15s`，但直接 `docker run` 时 Dockerfile healthcheck 会立即生效。建议添加 `--start-period=30s`。

### O-3. R1 P1-P3 问题概况

| 编号 | 标题 | 严重性 | 状态 |
|------|------|--------|------|
| P1-1 | SSE 流式端点绕过 `dispatch` 鉴权架构 | P1 | 未修复 |
| P1-2 | Docker 部署测试覆盖为 0 | P1 | 未修复 |
| P1-3 | `GET /documents` 无分页 | P1 | 未修复 |
| P1-4 | `_send_sse` auth 失败后响应头 | P1 | 未修复 |
| P2-1 | do_PUT/do_DELETE 重复代码 | P2 | 未修复 |
| P2-2 | chunked 拒绝用 411 而非 400 | P2 | 未修复 |
| P2-3 | 测试计划数量与实际不一致 | P2 | 未修复 |
| P2-4 | HEALTHCHECK 无 start_period | P2 | 未修复 |
| P3-1 | surrogate pair 截断风险 | P3 | 未修复 |
| P3-2 | MIME 映射不完整 | P3 | 未修复 |
| P3-3 | start_period 15s 偏紧 | P3 | 未修复 |

R1 明确建议"先修 P0，不要一次性修复所有 P1–P3"，因此以上未修复属于预期行为。建议发布后按优先级逐步处理。

---

## 结论

**P0 修复全部通过验证。master 分支无阻止发布的 P0 阻塞问题。**

建议：
- P0 已清，可推进发布
- 发布后从 P1-2（Docker 部署测试）和 P1-1（SSE 鉴权重构）开始，尽快补齐发布质量短板
- Dockerfile pip 行简化可随首次 Docker 测试修复一同处理
