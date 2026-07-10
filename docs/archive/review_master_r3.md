# 第 3 轮（终审）代码评审 — master

## 评审范围

| 文件 | 评审重点 |
|------|----------|
| `pyproject.toml` | 依赖完整性，optional-dependencies 链式引用 |
| `khub/llm/rag.py` | 空上下文守卫，内部字段泄露防护，流式/非流式 exception handling |
| `Dockerfile` | pip install .[all] 替换手工列表（R2 修复） |

## 评审结果

### pyproject.toml — 通过

- `[project.optional-dependencies]` 各项（dev/pdf/ann/crypto/s3）引用正确
- `all = ["khub[pdf,ann,crypto,s3]"]` 合理聚合子集
- `requires-python = ">=3.11"` 与 Dockerfile python:3.12-slim 兼容
- 包发现通过 `[tool.setuptools].packages` 显式声明，无遗漏

### khub/llm/rag.py — 通过

- `ask()` line 56 / `ask_stream()` line 83 均在调用 `_assemble_context` 前做了空 sources 守卫
- `_assemble_context()` 自身也有 `if not sources: return ""` 双重防护
- `_clean_sources()` 在 `_content` 使用完毕后及时移除，防止内部字段泄露：
  - `ask()`: complete → clean → return ✓
  - `ask_stream()`: assemble → clean → yield sources ✓
- `_build_prompt()` 使用 `.replace()` 而非 `.format()`，避免了文档/问题中含 `{}` 时抛 KeyError
- 流式/非流式均含异常捕获与日志记录

### Dockerfile — ❌ **P0: 构建阻塞**

**位置**: `Dockerfile:15`

**问题**: 行末多了一个 `&& \`，续行后无实际命令：

```dockerfile
RUN pip install --no-cache-dir ".[all]" && \
                                                                  ← 空行
# === 4. 复制源码并安装 ===
```

bash 收到 `pip install --no-cache-dir ".[all]" &&`，末尾 `&&` 缺少右侧操作数，导致 **shell 语法错误**，`docker build` 必然失败。

**修复**: 去掉末尾的 `&& \`，改为单行 RUN：

```dockerfile
RUN pip install --no-cache-dir ".[all]"
```

**验证**: R2 在 85b8ec7 中将手工列表替换为 `.[all]` 是正确的方向，但替换后未移除前次版本遗留的 `&& \` 行续符，导致构造性错误。

## 总体结论

| 项目 | 状态 |
|------|------|
| pyproject.toml | ✅ 通过 |
| khub/llm/rag.py | ✅ 通过 |
| Dockerfile | ❌ **P0 — 需修复** |

**建议**: 修复 Dockerfile 行 15 的悬挂 `&& \` 后即可签发 master 版本。
