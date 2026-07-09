# 数据看板/统计图表 — 第1轮代码评审报告

> **评审人**: Code Reviewer  
> **提交**: e612f8b (`feat(dashboard): 数据看板/统计图表增强`)  
> **分支**: m1  
> **文件**: `khub/api.py`, `khub/web/script.js`, `khub/web/style.css`

---

## 总体评价

该提交为 kHUB 添加了数据看板（Dashboard）功能，包含统计端点增强和纯 SVG 前端图表，零外部依赖。整体设计合理，代码可读性良好。但发现 **1 个严重安全漏洞（XSS）** 和若干正确性/性能问题，需修复后再合并。

---

## 🔴 必须修复 (MUST FIX)

### 1. 严重 XSS：onclick 处理函数中的单引号注入

**文件**: `khub/web/script.js` 第 223 行  
**严重性**: 🔴 严重 — 存储型 XSS

```javascript
recentHtml += '<div ...><a href="#" onclick="loadDoc(\'' + esc(d.id) + '\',\'' + esc(d.title) + '\');return false"...>' + esc(d.title || d.id) + '</a> ...</div>';
```

**问题**: `esc()` 函数只转义了 `&`, `<`, `>` 三个字符（第 9 行），**未转义单引号 `'`**。当 `d.title` 或 `d.id` 包含单引号时（例如通过 WebUI 编辑写入恶意内容），会突破字符串边界，注入任意 JavaScript 代码。

**攻击示例**（若 `d.title` 为 `x'+alert(1)+'`）：
```html
onclick="loadDoc('doc123','x'+alert(1)+'');return false"
```
— `alert(1)` 将执行任意代码。

**修复方案（选一）**：

**方案 A**：改用 `addEventListener` 完全避免内联 handler（推荐）：

```javascript
// 构建 DOM 元素而非拼接 HTML
const link = document.createElement('a');
link.href = '#';
link.textContent = d.title || d.id;
link.style.cssText = 'color:var(--accent);text-decoration:none';
link.addEventListener('click', (e) => {
  e.preventDefault();
  loadDoc(d.id, d.title);
});
```

**方案 B**：扩展 `esc()` 转义单引号和双引号：

```javascript
function esc(s) {
  return (s || '').replace(/[&<>'"]/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[c]));
}
```

**方案 C**：对属性值使用 `encodeURIComponent`：

```javascript
onclick="loadDoc('${encodeURIComponent(d.id)}','${encodeURIComponent(d.title)}');return false"
```

---

### 2. 数据库表不存在时 /stats 端点返回 500

**文件**: `khub/api.py` 第 90-95 行  
**严重性**: 🔴 严重 — 生产可靠性

```python
version_count = cur.execute(
    "SELECT count(*) FROM document_versions").fetchone()[0]
embed_count = cur.execute(
    "SELECT count(*) FROM embeddings").fetchone()[0]
```

**问题**: `document_versions` 和 `embeddings` 表是可选/延迟初始化的。如果数据库迁移未完成或新实例首次启动时未建表，这些查询会抛出 `OperationalError`（表不存在），导致整个 `/stats` 端点返回 500 空响应，连带前端看板全部无法渲染。

**修复方案**：

```python
def _safe_count(cur, table, where=""):
    """安全统计行数，表不存在返回 0。"""
    try:
        sql = f"SELECT count(*) FROM {table}"
        if where:
            sql += f" WHERE {where}"
        return cur.execute(sql).fetchone()[0]
    except Exception:
        return 0

version_count = _safe_count(cur, "document_versions")
embed_count = _safe_count(cur, "embeddings")
conflict_count = _safe_count(cur, "documents", "conflict=1")
```

或者捕获 `OperationalError` 包裹整个 `/stats` 请求处理。

---

## 🟡 应该修复 (SHOULD FIX)

### 3. 来源统计使用 JSON 字符串匹配，语义脆弱

**文件**: `khub/api.py` 第 67-72 行  
**严重性**: 🟡 高 — 正确性

```python
ids = row["source_ids"] or "[]"
for src in ("obsidian", "ima", "imanote", "quip", "kzocr", "library", "feishu", "webui"):
    if f'"{src}"' in ids:
        sources[src] = sources.get(src, 0) + 1
        break
```

**问题**: `source_ids` 是 JSON 数组字符串（如 `["obsidian","kzocr"]`），代码用子串匹配判断来源。若某个 source ID 恰好包含另一个来源名称为子串（如 `"obsidian-extra"` 匹配 `"obsidian"`），会导致误统计。

虽然当前数据中不太可能出现这种命名冲突，但属于脆弱设计。

**修复方案**：

```python
ids = json.loads(row["source_ids"] or "[]")  # 或直接用 ast.literal_eval
for src in ("obsidian", ...):
    if src in ids:
        sources[src] = sources.get(src, 0) + 1
        break
```

### 4. 每周趋势：7 次独立 SQL 查询

**文件**: `khub/api.py` 第 80-87 行  
**严重性**: 🟡 中 — 性能

```python
for i in range(6, -1, -1):
    day = ...
    cnt = cur.execute(
        "SELECT count(*) FROM documents WHERE updated_at >= ? AND updated_at < ?",
        (day, ...)
    ).fetchone()[0]
```

**问题**: 每次请求执行 7 次 `SELECT count(*)`。对于小型数据库影响不大，但在数万/百万级文档时会产生不必要的开销。

**优化方案**：改为单次 GROUP BY 查询，后端填充零值日：

```python
seven_days_ago = (_dt.date.today() - _dt.timedelta(days=6)).isoformat()
rows = cur.execute(
    "SELECT DATE(updated_at) as day, count(*) as cnt "
    "FROM documents WHERE updated_at >= ? "
    "GROUP BY DATE(updated_at)",
    (seven_days_ago,)
).fetchall()
counts = {r["day"]: r["cnt"] for r in rows}
weekly = []
for i in range(6, -1, -1):
    day = (_dt.date.today() - _dt.timedelta(days=i)).isoformat()
    weekly.append({"date": day, "count": counts.get(day, 0)})
```

### 5. 来源统计全表扫描

**文件**: `khub/api.py` 第 67 行  
**严重性**: 🟡 中 — 性能

```python
for row in cur.execute("SELECT source_ids FROM documents").fetchall():
```

**问题**: 无 WHERE 条件，全表扫描 `source_ids` 列。数据库可能位于远端或数据量大时成为瓶颈。当前场景可接受，但建议未来加缓存（如定时刷新、存到元数据表）。

---

## 🟢 建议优化 (SHOULD CONSIDER)

### 6. `import datetime` 写在方法体内部

**文件**: `khub/api.py` 第 80 行

```python
import datetime as _dt
```

`datetime` 是标准库模块且会被每次 /stats 调用（约 7 次命中），应移至文件顶部。虽然 Python 会缓存 import，但风格上不符合 PEP 8。

### 7. 前端 `esc()` 函数可扩展为通用 HTML 属性安全转义

**文件**: `khub/web/script.js` 第 9 行

```javascript
function esc(s) { return (s || '').replace(/[&<>]/g, ...); }
```

当前设计意图是 HTML **内容**转义（`<`, `>`, `&`）。但该函数同时用于 **属性值**（onclick、dataset），属性值还需转义 `'` 和 `"`。建议分离为 `escHtml(text)` 和 `escAttr(value)` 两个函数，或在注释中明确标注适用范围。

### 8. SVG 折线图：Y 轴只显示最大值和 0

当数据值在 0~max 之间时，用户无法直观判断中间值。建议增加 1-2 个中间刻度（如 max/2）。

### 9. 条状图数值溢出问题

**文件**: `khub/web/script.js` 第 176 行

```html
<div style="width:...;min-width:fit-content">...数值...</div>
```

当条形宽度极窄（例如 maxVal 很大而某个来源只有 1 条，`pct` 可能低至 1%）时，`min-width:fit-content` 使数值文本溢出容器。考虑在条外（右侧）显示数值，或仅当宽度 > 40px 时才在条内显示。

### 10. 前端缺少加载/错误状态

**文件**: `khub/web/script.js` 第 228 行

```javascript
} catch (e) { /* stats optional */ }
```

`loadStats()` 的 catch 块完全静默吞异常。当 `/stats` 返回 500（如问题 2 所述）时，用户既看不到数据也看不到错误提示。建议至少显示简短提示或日志。

### 11. CSS `!important`

**文件**: `khub/web/style.css` 第 295 行

```css
#stats a:hover { text-decoration: underline !important; }
```

`!important` 虽简便但降低可维护性。可通过提升选择器优先级替代，例如与现有选择器联写。

---

## ✅ 已发现的良好实践

| 实践 | 位置 |
|------|------|
| `w.length - 1 \|\| 1` 防止除以零 | script.js:190 |
| `Math.max(1, ...)` 防止除以零 | script.js:188 |
| `esc()` 统一 HTML 转义入口 | script.js:9 |
| SVG viewBox 实现响应式缩放 | script.js:198 |
| `order by updated_at desc limit 5` 使用索引友好 | api.py:98 |
| 冲突数条件渲染（仅 >0 时显示红色卡片） | script.js:162 |
| 来源标签使用中文可读映射 | script.js:166 |
| 纯 SVG 零外部依赖，符合前端体积控制 | 全部图表 |

---

## 问题汇总

| # | 严重性 | 类别 | 文件 | 简述 |
|---|--------|------|------|------|
| 1 | 🔴 严重 | 安全 XSS | script.js:223 | `esc()` 未转义 `'`，onclick 可注入 |
| 2 | 🔴 严重 | 可靠性 | api.py:90-95 | 可选表不存在时 /stats 返回 500 |
| 3 | 🟡 高 | 正确性 | api.py:67-72 | JSON 字符串匹配可能存在误匹配 |
| 4 | 🟡 中 | 性能 | api.py:80-87 | 7 次独立 SQL 可合并为 GROUP BY |
| 5 | 🟡 中 | 性能 | api.py:67 | 全表扫描影响大数据量表 |
| 6 | 🟢 低 | 代码风格 | api.py:80 | import 应在文件顶部 |
| 7 | 🟢 低 | 安全/可维护 | script.js:9 | esc() 应区分内容和属性上下文 |
| 8 | 🟢 低 | UX | script.js:213 | Y 轴刻度不足 |
| 9 | 🟢 低 | UX | script.js:176 | 窄条数值溢出 |
| 10 | 🟢 低 | UX | script.js:228 | 静默吞异常 |
| 11 | 🟢 低 | CSS | style.css:295 | !important 可优化 |

---

## 建议修复优先级

1. **立即修复**: #1（XSS）和 #2（500 崩溃）  
2. **合入前修复**: #3（JSON 匹配）、#4（SQL 优化）、#5（全表扫描）  
3. **后续迭代**: #6-#11（代码风格、UX 增强）

---

*以上评审基于提交 e612f8b 生成。建议在下一轮修复后执行回归验证。*
