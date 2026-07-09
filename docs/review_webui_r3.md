# WebUI 第 3 轮代码评审报告

**评审范围**: commit `38dc3de` — R2 轮修复验证  
**评审日期**: 2026-07-10  
**评审方式**: 人工静态分析（修复验证 + 剩余问题扫描）

---

## 严重等级说明

| 标记 | 含义 | 行动建议 |
|------|------|----------|
| 🔴 **必须修复** | 安全漏洞 / 数据正确性问题 / 逻辑错误 | 合入前必须修复 |
| 🟡 **建议修复** | 边界情况 / 防御性编程缺失 / 性能隐患 | 建议本轮修复 |
| 🔵 **仅供参考** | 代码风格 / 可维护性 / 微优化 | 低优先级，下轮改进 |

---

## ✅ 修复验证：全部正确解决（3 项）

### NEW-1. PUT 无条件调用 `resolve_conflict` 导致版本翻倍

**文件**: `khub/api.py:196-201`

**修复**: 用直接 SQL 替代 `resolve_conflict()` 调用——仅当 `conflict=1` 时更新标记位，不创建新版本。

```python
version_id = self.store.store_document(doc)
self.store.conn.execute(
    "UPDATE documents SET conflict=0 WHERE canonical_id=? AND conflict=1",
    (cid,))
self.store.conn.commit()
return 200, {"status": "ok", "version_id": version_id}
```

**验证结果**: ✅ 正确。
- `WHERE conflict=1` 条件确保非冲突文档不会被触及
- `UPDATE` 不额外写入 `document_versions` 表，彻底消除了版本翻倍
- 返回的 `version_id` 与 `current_version` 一致（均为 `store_document` 创建的新版本）
- 提交时机紧跟在 SQL 之后，事务行为正确

---

### NEW-2. `resolve_conflict` 调用后 `current_version` 不一致

**修复**: 同 NEW-1，PUT 处理器不再调用 `resolve_conflict()`，因此不再发生 `current_version` 偏离。

**验证结果**: ✅ 已随 NEW-1 自动解决。

---

### NEW-3. HTML 正则吞掉非安全标签间文本

**文件**: `khub/api.py:160`

**修复**: 正则从 `.*?<` 改为 `[^>]*>`，只匹配单个标签：

```python
content = _re.sub(r"(?s)<(?!\/?(?:" + safe_tags + r")(?:\s[^>]*)?>)[^>]*>", "", content)
```

**验证结果**: ✅ 正确。
- `[^>]*>` 匹配到 `>` 即停止，不跨标签匹配文本内容
- 标签间的纯文本被完整保留
- 第二道安全清理（L161-164）不受影响

---

## 🟡 建议修复

### R6/NEW-4. PUT 编辑未携带 `format` 字段，HTML 文档无声丢格式

**文件**: `khub/web/script.js:195` + `khub/api.py:193`

**状态**: ⚠️ **三轮回仍未修复**（R1→R7, R2→NEW-4, R3→同一问题）

**复现步骤**:
1. 创建一个 HTML 格式文档（内容含 `<p>`、`<b>` 等标签）
2. 在前端 WebUI 中编辑该文档并保存
3. 重新加载：格式变为 `"plain"`，HTML 标签被 `esc()` 转义显示为纯文字

**根因链**:
- 前端 `saveDoc()` 仅发送 `{title, content}`，未携带 `format`（L195）
- 服务端 `PUT` 默认 `format=body.get("format", "plain")`（L193）
- 编辑时 `editDoc()` 提取 `contentEl.textContent`（L173）—— 对 HTML 文档，`textContent` 已丢失标签信息
- 即使 format 正确传递，HTML 内容经 `textContent` 提取后也已降级为纯文本

**影响**: 编辑任何 HTML 文档都会导致格式永久降级为纯文本。

**修复要点（两处）**:
1. **前端** `script.js`：`saveDoc()` 发送 `format` 字段
2. **前端** `script.js`：`editDoc()` 对 HTML 文档应使用 `innerHTML` 而非 `textContent`（或额外存储原始 HTML 源码）

---

### R6. 冲突视图硬编码取最后两个版本

**文件**: `khub/web/script.js:211`

```javascript
const v1 = vers[vers.length - 2], v2 = vers[vers.length - 1];
```

**状态**: ⚠️ **三轮回仍未修复**（R1→R6, R2→遗留, R3→同一问题）

**问题**: 假设冲突发生在最后两个版本之间。如果 `resolve_conflict` 曾被执行过（创建了解决版本），或文档经历了多次编辑后才进入冲突状态，冲突版本可能不是版本列表中最新的两个。

**影响**: 有误判风险（展示的版本并非实际冲突的两个版本），但当前业务场景中冲突检测在同步阶段标记，通常对应最近两个版本，实际影响有限。

---

### R9. `_html_page()` 每次请求读盘

**文件**: `khub/api.py:362-365`

**状态**: ⚠️ **三轮回仍未修复**

```python
@staticmethod
def _html_page():
    page_path = os.path.join(os.path.dirname(__file__), "web", "index.html")
    try:
        with open(page_path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<!DOCTYPE html>..."
```

每次 GET `/` 都读盘。低流量时无影响，但修复成本低：可加 `@functools.lru_cache(maxsize=1)` 或 `_html_content` 模块级变量。

---

### R10. 无并发请求去重 / AbortController

**文件**: `khub/web/script.js`（多处）

**状态**: ⚠️ **三轮回仍未修复**

**问题**: 快速点击搜索按钮/加载按钮时，先发出的请求尚未返回，后发出的请求触发新的 `fetch()`。由于无法保证响应顺序，先返回的旧响应可能覆盖后返回的新响应，导致展示结果与用户意图不符。

**建议**: 使用 `AbortController` 在发起新同类请求时取消上一个未完成的请求，或在请求中嵌入递增序列号并忽略旧序列号响应。

---

### NEW-5. 前端 HTML 内容弱脚本过滤（防御深层加固）

**文件**: `khub/web/script.js:84-86`

```javascript
if (r.format === 'html') {
    const safe = (r.content || '').replace(/<script[\s\S]*?<\/script>/gi, '');
    html += '<div class="doc-content">' + safe + '</div>';
}
```

**状态**: 仍为仅删 `<script>` 标签的简单正则。服务端有完整清理，此处的过滤是冗余防御层。如担心防御纵深，可引入 DOMPurify（CDN 加载）。

---

## 🔵 仅供参考

### NEW-6. `resolve_conflict` 中变量 `title_row` 类型复用

**文件**: `khub/db.py:305-308`

```python
title_row = self.conn.execute(...).fetchone()   # → sqlite3.Row
title_row = title_row["title"] if title_row else ""  # → str
```

**状态**: 未修复。功能正确但可读性不佳。建议 `title_text`。

---

### NEW-7. `import re as _re` 位于 if 分支内部

**文件**: `khub/api.py:158`

```python
if fmt == "html":
    import re as _re
```

**状态**: 未修复。功能正确，但不符合 `import` 在文件顶部的惯例，且每次 HTML 请求都有 import 开销。

---

### NEW-8. POST `/resolve` 端点在边界路径下返回空 ID

**文件**: `khub/api.py:205-206`

```python
if method == "POST" and path.endswith("/resolve"):
    cid = unquote(path[len("/documents/"):-len("/resolve")])
```

**状态**: 未修复。当请求路径为 `/resolve`（无 `/documents/` 前缀）时，`cid` 为空字符串。后续 `resolve_conflict("", keep_id)` 因找不到版本抛出 ValueError，转 400。不崩溃但响应语义不正确（应为 404）。可在解析前补充 `path.startswith("/documents/")` 校验。

---

### 冲突视图忽略版本 `format` 字段

**文件**: `khub/web/script.js:221-222`

```javascript
pane.innerHTML = '<div class="pane-header">版本 ' + c.version_id + ' · ' + (c.updated_at || '') + '</div>' +
    '<div class="pane-content">' + esc(c.content) + '</div>';
```

**问题**: 冲突版本视图始终使用 `esc()` 转义内容。版本 API 返回 `format` 字段（`c.format`），但未使用。若冲突版本为 HTML 格式，HTML 标签会被转义显示为文字而非渲染展示。

**影响**: 极小——目前冲突版本通常来自同步产生的文本版本，不含 HTML。但若未来支持 HTML 文档冲突解决，此处需按 format 条件渲染。

---

## 已关闭（不再适用的 R1/R2 问题）

| ID | 问题 | 等级 | 关闭原因 |
|----|------|------|----------|
| R12 | PUT 创建新版本后没有处理冲突标记 | 🟡 | 已在 NEW-1 修复方案中一并解决——不再调用 `resolve_conflict` |
| NEW-1 | 版本翻倍 | 🔴 | 已修复——直接 SQL 清除冲突标记 |
| NEW-2 | current_version 不一致 | 🔴 | 已随 NEW-1 修复 |
| NEW-3 | 正则吞文本 | 🟡 | 已修复——`[^>]*>` 替代 `.*?<` |

---

## 总结

| 类别 | 数量 | 关键项 |
|------|------|--------|
| ✅ 正确修复 | 3 | NEW-1（版本翻倍）、NEW-2（current_version）、NEW-3（正则吞文本） |
| 🟡 **建议修复·遗留** | **5** | PUT 丢格式(R6/NEW-4)、冲突视图硬编码最后两版本(R6)、_html_page 未缓存(R9)、无 AbortController(R10)、前端弱过滤(NEW-5) |
| 🔵 **仅供参考·遗留** | 3+1 | 变量命名(NEW-6)、import 位置(NEW-7)、边界 path(NEW-8)、冲突视图忽略 format |
| 🔵 关闭（已修复/不再适用） | 4 | R12, NEW-1, NEW-2, NEW-3 |

**核心风险**: 本轮两个 🔴 问题（NEW-1 版本翻倍、NEW-2 current_version 不一致）已正确修复。

**最值得优先处理的遗留问题**: **PUT 丢格式（R6/NEW-4）**——该问题已连续三轮未修复，直接影响用户编辑 HTML 文档的体验。修复涉及前端 `saveDoc()` 传递 format、`editDoc()` 对 HTML 内容使用 innerHTML 保存源码两条改动。其余 🟡 问题（R6 冲突视图、R9 缓存、R10 AbortController）建议在功能迭代间隙分批修复。
