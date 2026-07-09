# 数据看板/统计图表 — 第2轮代码评审报告

> **评审人**: Code Reviewer (R2)
> **R1 报告**: `docs/review_dashboard_r1.md`（commit `70d2cf2`）
> **修复提交**: `7102842`（`fix(dashboard): R1 review 修复——XSS + 表不存在容错 + 来源统计`）
> **分支**: m1
> **文件**: `khub/api.py`, `khub/web/script.js`

---

## 总体评价

R1 指出的 3 个严重/高优问题中，**2 个已正确修复**，1 个部分修复但仍有残留子串匹配缺陷。未引入新的严重安全漏洞。R1 中的多项 SHOULD FIX / SHOULD CONSIDER 建议未在此轮处理，属于正常迭代节奏。

---

## 一、R1 修复验证

### ✅ 1.1 XSS：esc() 转义单引号和双引号 — 已正确修复

**文件**: `khub/web/script.js:9`

```javascript
// 修复前
function esc(s) { return (s || '').replace(/[&<>]/g, ...); }

// 修复后
function esc(s) { return (s || '').replace(/[&<>"']/g, c => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c])); }
```

- `'` → `&#39;`：防止单引号突破 HTML 属性值边界
- `"` → `&quot;`：防止双引号突破 HTML 属性值边界

**验证结果**: 所有内联 onclick handler 中的用户数据（`d.id`、`d.title`、`r.canonical_id`、`s.id`、`s.title`）均已通过 `esc()` 转义。攻击向量 `x'+alert(1)+'` 在 esc() 处理后变为 `x&#39;+alert(1)+&#39;`，不会突破字符串边界。✅

---

### ✅ 1.2 /stats 表不存在容错 — 已正确修复

**文件**: `khub/api.py:83-104`

**修复策略**: 将 weekly 趋势计算 + 可选表查询（`document_versions`、`embeddings`）整体包裹在 `try/except Exception: pass` 中。所有值在 try 之前初始化为安全默认值（`weekly=[]`、`count=0`）。

```python
weekly = []
version_count = 0
embed_count = 0
conflict_count = 0
try:
    import datetime as _dt
    for i in range(6, -1, -1):
        ...
    version_count = cur.execute(
        "SELECT count(*) FROM document_versions").fetchone()[0]
    embed_count = cur.execute(
        "SELECT count(*) FROM embeddings").fetchone()[0]
    conflict_count = cur.execute(
        "SELECT count(*) FROM documents WHERE conflict=1").fetchone()[0]
except Exception:
    pass
```

**验证结果**: 当 `document_versions` 或 `embeddings` 表不存在时，返回 `{"versions": 0, "embeddings": 0, "conflicts": 0, "weekly": []}`，不会再抛 500。✅

**设计折中说明**:
- 此实现使用统包（blanket）try/except 而非 R1 建议的 `_safe_count()` 函数
- 若 `SELECT count(*) FROM documents`（weekly 部分）失败也会被吞掉，但 `documents` 表在函数前段已被成功查询（`total = cur.execute(... documents ...)`），所以不会发生
- `_safe_count()` 的粒度更细，但当前实现对于"可选表"场景已足够安全

---

### ⚠️ 1.3 来源统计改用 json.loads — 部分修复

**文件**: `khub/api.py:67-76`

```python
# 修复后代码
try:
    parsed = json.loads(ids)
    first = parsed[0] if isinstance(parsed, list) and parsed else None
except (json.JSONDecodeError, IndexError, TypeError):
    first = None
for src in ("obsidian", "ima", "imanote", "quip", "kzocr", "library", "feishu", "webui"):
    if first and src in str(first):
        sources[src] = sources.get(src, 0) + 1
        break
```

**已修复的部分**: ✅ `json.loads()` 正确解析 JSON 数组，不再对原始 JSON 字符串做子串匹配。JSON 解码错误也有异常处理。

**残留缺陷**: ❌ 第 75 行 `src in str(first)` 仍是**子串匹配**，而非精确匹配。当 `first = "imanote"` 时：

| 迭代 | `src` | `src in "imanote"` | 结果 |
|------|-------|--------------------|------|
| 1 | `"obsidian"` | `False` | 跳过 |
| 2 | `"ima"` | `True` | ⚠️ 误统计为 `ima` |
| 3 | `"imanote"` | — | break，不会再检查 |

**R1 推荐的正确方案**（使用了列表精确匹配）：

```python
ids = json.loads(row["source_ids"] or "[]")
for src in ("obsidian", ...):
    if isinstance(ids, list) and src in ids:
        sources[src] = sources.get(src, 0) + 1
        break
```

**或**精确匹配第一个元素：

```python
first = parsed[0] if isinstance(parsed, list) and parsed else None
if first:
    for src in (...):
        if src == first:    # 精确匹配
            sources[src] = sources.get(src, 0) + 1
            break
```

**实际影响评估**: 极低。当前数据中不存在 `"imanote"` 被误判为 `"ima"` 的场景。但作为正确性修复，建议跟进。

---

## 二、剩余 XSS 向量排查

### 2.1 所有内联 onclick handler — 均已覆盖 ✅

| 位置 | handler | 注入参数 | esc() 保护 |
|------|---------|---------|-----------|
| L79 | `loadAll()` | 无参数 | — |
| L83 | `editDoc(id)` | `r.canonical_id` | ✅ |
| L223 | `loadDoc(id, title)` | `d.id`, `d.title` | ✅ |
| L247 | `saveDoc(id)` | `id` | ✅ |
| L248 | `loadDoc(id, title)` | `id`, `title` | ✅ |
| L283 | `loadConflicts()` | 无参数 | — |
| L294-295 | `resolveVersion(id, vid)` | `id` ✅, `vid` 为整数 | ✅ |
| L340 | `loadDoc(s.id, s.title)` | `s.id`, `s.title` | ✅ |

### 2.2 其他 innerHTML 注入风险

所有通过 `innerHTML` 插入用户数据的位置均已使用 `esc()`。高风险路径已确认：

- **L42**: `card()` 函数 — `d.title`, `d.snippet`, `d.doc_id` 均经 `highlight()`（内部调 `esc()`）处理 ✅
- **L81-82**: `loadDoc()` 文档头 — `r.format`, `r.title`, `r.canonical_id` 均经 `esc()` ✅
- **L85**: HTML 内容渲染 — 前端仅剥离 `<script>` 标签，主要依赖后端 API 净化 ✅（见下方 2.3）
- **L88**: `esc(r.content)` 纯文本渲染 ✅
- **L125**: 语义搜索结果 `titles[d.doc_id]` 经 `esc()` ✅
- **L240**: 编辑标题输入框 `value` 属性经 `esc()` ✅
- **L288**: 冲突面板版本内容经 `esc(c.content)` ✅
- **L326-327**: AI 消息渲染经 `esc(text)` ✅

### 2.3 防御纵深：前端 HTML 内容净化较弱

**文件**: `khub/web/script.js:85`

```javascript
const safe = (r.content || '').replace(/<script[\s\S]*?<\/script>/gi, '');
html += '<div class="doc-content">' + safe + '</div>';
```

前端只剥离 `<script>` 标签，完全依赖后端 api.py:190-197 的 HTML 净化。后端正则存在**绕过可能**：

- 事件处理器正则 `r'\s+on\w+\s*=\s*["\'][^"\']*["\']'` 是**大小写敏感**的，`onCLICK=alert(1)` 可绕过
- 若通过其他 API 路径（非 `/documents/{id}`）入库的 HTML 内容包含 `onCLICK=`，后端不会剥离，前端也不会阻止

**修复建议**：前端也应做大小写不敏感的事件属性剥离，作为防御纵深：

```javascript
const safe = (r.content || '')
  .replace(/<script[\s\S]*?<\/script>/gi, '')
  .replace(/\s+on\w+\s*=\s*["'][^"']*["']/gi, '')
  .replace(/\s+on\w+\s*=\S+/gi, '');
```

**严重性**: 🟢 低 — 需要后端绕过 + 特定 API 路径。非紧急。

---

## 三、新引入的问题

### 3.1 来源匹配语义变更

**文件**: `khub/api.py:68-76`

**旧行为**：遍历所有 `source_ids` JSON 字符串，按 source 顺序匹配第一个出现的来源名。例如 `["kzocr","obsidian"]`，由于 `"obsidian"` 在迭代顺序中靠前 → 统计为 `obsidian`。

**新行为**：只取 JSON 数组的第一个元素，判断其子串包含哪个 source。例如 `["kzocr","obsidian"]`，`first = "kzocr"` → 统计为 `kzocr`。

**影响**: 对于包含多个来源的文档，统计归属可能发生变化。取决于实际数据分布，可能影响统计报表的历史连续性。

**评估**: 新语义（第一个来源为主来源）更符合直觉。但建议在后续统计分析时注意前后对比可能出现的偏移。

---

## 四、R1 未处理问题清单

以下为 R1 提出的但**本轮修复未覆盖**的问题：

| R1 # | 严重性 | 简述 | 是否处理 |
|------|--------|------|---------|
| 3 | 🟡 高 | 来源匹配子串问题（已部分修复，残余见 1.3） | ⚠️ 部分 |
| 4 | 🟡 中 | 7 次独立 SQL 未合并为 GROUP BY | ❌ |
| 5 | 🟡 中 | 全表扫描无缓存 | ❌ |
| 6 | 🟢 低 | `import datetime` 在函数体内（现已在 try 块内） | ❌ |
| 7 | 🟢 低 | `esc()` 未区分文本/属性上下文 | ❌ |
| 8 | 🟢 低 | Y 轴只有 max 和 0 两个刻度 | ❌ |
| 9 | 🟢 低 | 窄条数值溢出 | ❌ |
| 10 | 🟢 低 | `loadStats()` catch 静默吞异常 | ❌ |
| 11 | 🟢 低 | CSS `!important` | ❌ |

上述问题均非安全/可靠性阻断，建议放到后续迭代中处理。

---

## 五、结论

| 类别 | 数量 | 详情 |
|------|------|------|
| ✅ 正确修复 | 2 | esc() 引号转义、/stats try/except |
| ⚠️ 部分修复 | 1 | 来源统计子串匹配残留缺陷 |
| 🟢 新增防御纵深建议 | 1 | 前端 HTML 事件属性大小写不敏感剥离 |
| ❌ 未处理（低优先级） | 9 | R1 #3 残余 + #4-#11 |

**建议**: 修复 1.3 节中的来源匹配子串问题后即可合入。防御纵深建议（2.3 节）可选跟进。

---

*以上评审基于提交 7102842 生成，在 commit 70d2cf2（R1 报告）基础上进行回归验证。*
