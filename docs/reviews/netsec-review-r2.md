# khub M1 — 网络安全审查（R2 修复验证）

- **日期：** 2026-07-09
- **范围：** R1 五项发现的修复情况验证（基于 M1 实现计划 2026-07-07）
- **方法：** 代码级比对（M1 计划中的实现代码 vs R1 建议）

---

## R1 Finding #4 — DB chmod 600

**Finding：** Store 在初始化时未限制数据库文件权限，同机器其他进程/用户可读取。

**Verdict：已修复 (fixed)**

`Store.__init__`（`db.py:166-168`）在创建文件后执行 `os.chmod(path, 0o600)`：
```python
if path != ":memory:":
    import os
    os.chmod(path, 0o600)
```
- `:memory:` 实例正确跳过。
- 文件权限在创建后立即设置，窗口期极小（SQLite `connect()` → `chmod()`）。

**Note：** 无。

---

## R1 Finding #6 — 内容大小限制

**Finding：** `store_document()` 无内容大小校验，超大数据可能导致数据库膨胀或 OOM。

**Verdict：已修复 (fixed)**

`db.py:154` 定义了上限常量，`store_document()` 入口处立即校验：
```python
MAX_DOC_SIZE = 10 * 1024 * 1024  # 10 MB

def store_document(self, doc, ...):
    if len(doc.content) > MAX_DOC_SIZE:
        raise ValueError(...)
```
- 上限 10 MB，与 R1 建议一致。
- 发生在数据写入前的早期阶段，避免无效 IO。

**Note：** 无。

---

## R1 Finding #6 — FTS5 搜索错误处理

**Finding：** FTS5 搜索词可触发语法异常或性能消耗；无长度限制。

**Verdict：已修复 (fixed)**

`db.py:266-275` 中 `search()` 同时实现了两项防护：
```python
def search(self, text: str):
    if len(text) > 200:
        text = text[:200]           # 长度限制
    try:
        rows = ... MATCH ?
    except sqlite3.DatabaseError:
        rows = []                   # 异常降级
```
- 搜索词长度上限 200 字符（静默截断而非报错）。
- `sqlite3.DatabaseError` 捕获 FTS5 语法错误，返回空结果（比抛给用户更友好）。
- R1 提议的 LIKE 回退未实现（当前降级为空结果，足够合理）。

**Note：** 静默截断而非报错是合理选择（CLI 场景）。若未来添加 Web UI，建议增加通知提示"搜索词已截断"。

---

## R1 Finding #1 — 凭据管理

**Finding：** 凭据仅环境变量，需明确文档化。

**Verdict：已修复 (fixed，R1 已认可无需代码变更)**

M1 计划维持原有方案：
- `config.py:949-950`：`secret()` 通过 `os.environ.get()` 读取，无变更。
- `config.yaml.example:965,969`：凭据项标注 `# 凭证走环境变量: IMA_TOKEN / QUIP_TOKEN`，不含实际值。

R1 明确表示 M1 阶段此方案可接受，需要的是文档化而非代码变更。当前实现保持了正确的凭据分离。

**Note：** M2+ 如有引入 `.env` 文件读取的计划，需确保文件权限 `600`。

---

## R1 Finding #3 — 路径穿越

**Finding：** `OcrAdapter` 的 `book_dir` 来自用户参数，无路径安全校验。

**Verdict：部分修复 (partial)**

`OcrAdapter.__init__`（`ocr.py:560-563`）新增了目录存在性校验：
```python
def __init__(self, book_dir: str):
    self.book_dir = Path(book_dir)
    if not self.book_dir.is_dir():
        raise ValueError(f"OCR book_dir 不存在或非目录：{book_dir}")
```

但 R1 建议的额外措施**未**包含：
- `os.path.abspath()` 标准化路径解析。
- 限制路径在安全目录范围内（如白名单）。
- 预留校验函数的 TODO/docstring。

R1 将路径穿越列为 **low severity**，建议 M1 可暂缓、M2 Web UI 前必须修复。当前状态对 M1 可接受，但 M2 前需补齐。

**Note：** 建议在 `OcrAdapter.__init__` 中增加 `os.path.realpath(book_dir)` 调用并记录到 docstring，降低 M2 忘记修复的风险。

---

## 汇总

| # | Finding | 原始 Severity | Verdict | 说明 |
|---|---------|--------------|---------|------|
| 4 | DB chmod 600 | medium | **fixed** | `Store.__init__` 中已实现 `os.chmod(path, 0o600)` |
| 6 | 内容大小限制 | medium | **fixed** | `MAX_DOC_SIZE=10MB`，`store_document()` 入口校验 |
| 6 | FTS5 错误处理 | medium | **fixed** | 200 字符限制 + `sqlite3.DatabaseError` 捕获降级 |
| 1 | 凭据管理 | medium | **fixed** | 环境变量方案已文档化，无需代码变更 |
| 3 | 路径穿越 | low | **partial** | 目录存在性校验已添加，但缺 `abspath`/安全目录约束 |

### 未关闭项（M2 前需处理）

1. **路径穿越：** 补充 `os.path.realpath()` 和安全目录约束（M2 Web UI 前绑定）。
2. **凭据管理：** 若引入 `.env` 文件，必须设 `600` 权限。

---

*审查人：security-reviewer（CodeBuddy 自动审查，R2 修复验证）*
*审查依据：M1 实现计划（2026-07-07）与 R1 审查报告（netsec-review.md）*
