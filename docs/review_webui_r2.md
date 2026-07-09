# WebUI 第 2 轮代码评审报告

**评审范围**: commit `ef6441a` — R1 轮修复验证  
**评审日期**: 2026-07-10  
**评审方式**: 人工静态分析（修复验证 + 潜在新问题扫描）

---

## 严重等级说明

| 标记 | 含义 | 行动建议 |
|------|------|----------|
| 🔴 **必须修复** | 安全漏洞 / 数据正确性问题 / 逻辑错误 | 合入前必须修复 |
| 🟡 **建议修复** | 边界情况 / 防御性编程缺失 / 性能隐患 | 建议本轮修复 |
| 🔵 **仅供参考** | 代码风格 / 可维护性 / 微优化 | 低优先级，下轮改进 |

---

## ✅ 修复验证：已正确解决（7 项）

以下 R1 轮发现的问题已正确修复，无需进一步处理：

### R1. `resolve_conflict` 忽略 `keep_version_id`

**文件**: `khub/db.py:279-312`

**修复验证**: ✅ 已正确实现。方法体现在：
1. 按 `keep_version_id` 读取所选版本内容（L282-284）
2. 未找到时抛出 `ValueError`（L286-287）
3. 以所选版本内容写入新版本，origin=`"webui-resolve"`，`parent_version` 指向所选版本（L289-295）
4. 将 `current_version` 更新为新版本，清除冲突标记（L297-300）
5. 同步 FTS 索引（L302-311）

**潜在注意点**: 写入了新版本，未选择直接覆盖原版本。版本历史的审计保留逻辑没问题，对于冲突频繁的文档版本数会增长较快，但属于正常行为。

---

### R3. `search()` 不重置 `currentPage`

**文件**: `khub/web/script.js:97`

```javascript
currentPage = 0;  // 新查询重置分页
```

**修复验证**: ✅ 正确。在读取查询参数后、发送请求前归零。

---

### R4. SSE 流式请求缺少 `resp.ok` 检查

**文件**: `khub/web/script.js:289-293`

```javascript
if (!resp.ok) {
    const errData = await resp.json().catch(() => ({ error: resp.statusText }));
    aiAppendToken(aiBubble, '[请求失败: ' + (errData.error || resp.status) + ']');
    return;
}
```

**修复验证**: ✅ 正确。非 200 响应时显示错误信息并提前返回，避免对错误响应调用 `getReader()`。

---

### R5. PUT `/documents/{id}` 未做路径深度校验

**文件**: `khub/api.py:177-180`

```python
rest = path[len("/documents/"):]
if "/" in rest:
    return 400, {"error": "invalid document id (path too deep)"}
```

**修复验证**: ✅ 正确。路径 `/documents/foo/bar` 等深层路径被拒绝。

---

### R8. `int(keep_id)` 未捕获 `ValueError`

**文件**: `khub/api.py:207-210`

```python
try:
    keep_id = int(keep_id)
except (TypeError, ValueError):
    return 400, {"error": "keep_version 必须是有效整数"}
```

**修复验证**: ✅ 正确。同时在 L211-214 额外捕获 `resolve_conflict` 可能抛出的 `ValueError`，返回 400。

---

### R11. 冲突解决时未并发加载两个版本

**文件**: `khub/web/script.js:212-215`

```javascript
const [c1, c2] = await Promise.all([
    fetch(`/documents/${encodeURIComponent(id)}/versions/${v1.version_id}`).then(x => x.json()),
    fetch(`/documents/${encodeURIComponent(id)}/versions/${v2.version_id}`).then(x => x.json()),
]);
```

**修复验证**: ✅ 正确。两个版本请求并行执行。

---

### R12. PUT 创建新版本后没有处理冲突标记

**文件**: `khub/api.py:198`

```python
self.store.resolve_conflict(cid, version_id)
```

**修复验证**: ⚠️ **已实现但过度修复** — 见下方 NEW-1。

---

## 🔴 必须修复

### NEW-1. PUT 无条件调用 `resolve_conflict` 导致版本翻倍（R12 过度修复）

**文件**: `khub/api.py:196-199`

```python
version_id = self.store.store_document(doc)         # 创建版本 v1
self.store.resolve_conflict(cid, version_id)          # 创建版本 v2（副本）
return 200, {"status": "ok", "version_id": version_id} # 返回 v1（不是当前版本）
```

**问题**: 
- `resolve_conflict` **无条件执行**，不论文档是否处于冲突状态
- `resolve_conflict` **始终创建新版本**（db.py L289-295，以所选内容写入新行）
- 每次 PUT 因此产生 **2 个版本**：`store_document` 创建 v1，`resolve_conflict` 创建内容完全相同的 v2
- `resolve_conflict` 执行后将 `current_version` 改为 v2，但 API 返回的是 v1

**后果**: 每次编辑产生双倍版本（编辑 10 次 → 20 个版本），数据和 FTS 内容完全重复。长期使用导致版本表膨胀，前端版本列表变长。

**修复方案**: 仅在文档确实处于冲突状态时清除标记，不创建新版本：

```python
version_id = self.store.store_document(doc)
# 若文档处于冲突状态，仅清除冲突标记（不创建新版本）
doc_record = self.store.get_document(cid)
if doc_record and doc_record["conflict"]:
    self.store.mark_conflict(cid, False)
return 200, {"status": "ok", "version_id": version_id}
```

或为 `Store` 增加一个轻量的 `clear_conflict_flag()` 方法，仅 `UPDATE documents SET conflict=0`。

---

### NEW-2. `store_document` 后调用 `resolve_conflict` 未恢复 `current_version`

**文件**: `khub/api.py:196-199`

**问题**（与 NEW-1 相关）: 即使忽略版本翻倍问题，`resolve_conflict` 将 `current_version` 更新为 it 创建的新版本（v2），而非 `store_document` 创建的 v1。API 返回 `version_id` 为 v1，但数据库中当前版本为 v2（v1 的副本）。`version_id` 响应值与实际 `current_version` 不一致。

**修复**: 同 NEW-1 方案，或用 `store_document` 返回的版本号直接更新文档：

```python
version_id = self.store.store_document(doc)
self.store.conn.execute(
    "UPDATE documents SET conflict=0 WHERE canonical_id=? AND conflict=1",
    (cid,))
self.store.conn.commit()
```

---

## 🟡 建议修复

### NEW-3. HTML 文本内容在过滤非安全标签时可能丢失

**文件**: `khub/api.py:160`

```python
content = _re.sub(r"(?s)<(?!\/?(?:" + safe_tags + r")(?:\s[^>]*)?>).*?<", "<", content)
```

**问题**: 此正则用于移除非安全标签（不在 `safe_tags` 白名单内的标签）。它通过 `.*?<` 从非安全标签的 `<` 一直匹配到下一个 `<`（即紧接的下一标签），然后替换为一个 `<`。

当非安全标签和下一个标签之间存在文本内容时，该文本会被吞掉。例如：

```html
<img src="photo.jpg">请看下图说明<p>正文</p>
```

`<img` 触发非安全匹配，`.*?<` 从 `img src="photo.jpg">请看下图说明<` 全部捕获替换为 `<`。结果"请看下图说明"丢失。

**影响**: 对于常见 `<img>`、`<hr>`、`<br>`（br 在 safe_tags 内不触发此问题）等自闭合标签，若其后紧跟文本再跟一个安全标签，文本被吞掉。

**修复方案**: 使用更精确的标签过滤，仅移除标签本身，保留标签内容：

```python
content = _re.sub(r"<(?!\/?(?:" + safe_tags + r")(?:\s[^>]*)?>)[^>]*>", "", content)
```

当前的正则 `.*?<` 改为 `[^>]*>`，只匹配单个标签，不移除标签间内容。

> ⚠️ **安全提示**: 当前实现虽会丢失部分文本，但安全目标已达成（危险标签被移除、事件处理器被清除、javascript: URI 被替换）。此问题为内容完整性问题。

---

### NEW-4. PUT 编辑未携带 `format` 字段，HTML 文档无声丢失格式（R7 未修复）

**文件**: `khub/web/script.js:195` + `khub/api.py:193`

**问题**: R1 轮已报告此问题（R7：编辑 HTML 文档时丢失格式），本次未修复。

- 前端 `saveDoc()` 发送 `{title, content}`，未包含 `format` 字段
- 服务端 PUT 处理器默认 `format=body.get("format", "plain")`
- 编辑 HTML 文档后，格式被无声转换为 `"plain"`

**影响**: 用户编辑 HTML 格式的文档后，HTML 标签丢失、格式降级为纯文本。

**修复方案**: 前端保存时传递当前文档格式：

```javascript
// script.js saveDoc()
const currentFormat = r.format || 'plain'; // 需在 editDoc 时记录
body: JSON.stringify({ title: title, content: content, format: currentFormat })
```

或者前端在 `saveDoc` 时从当前文档上下文中读取 `format`。

---

### NEW-5. 前端 `loadDoc()` 中 HTML 内容仍使用弱脚本过滤（防御层可加固）

**文件**: `khub/web/script.js:84-86`

```javascript
if (r.format === 'html') {
    const safe = (r.content || '').replace(/<script[\s\S]*?<\/script>/gi, '');
    html += '<div class="doc-content">' + safe + '</div>';
}
```

**问题**: 服务端现已做全面清理，前端此处的 `<script>` 过滤已成为冗余防御层。但若未来服务端清理逻辑被绕过（或新增端点未清理），此弱过滤不足以防御 XSS。应升级为更完善的方案。

**建议**:
- 方案 A：移除前端过滤，完全信赖服务端清理（简化代码，但失去防御纵深）
- 方案 B（推荐）：引入 DOMPurify（可从 CDN 加载），作为安全底线：

```javascript
if (r.format === 'html') {
    const safe = DOMPurify.sanitize(r.content || '', {
        ALLOWED_TAGS: ['p','br','b','i','u','strong','em',
                       'h1','h2','h3','h4','h5','h6',
                       'ul','ol','li','div','span','pre','code',
                       'blockquote','table','tr','td','th','a'],
        ALLOWED_ATTR: ['class','style']
    });
    html += '<div class="doc-content">' + safe + '</div>';
}
```

---

## 🔵 仅供参考

### NEW-6. `resolve_conflict` 中变量 `title_row` 类型复用

**文件**: `khub/db.py:305-308`

```python
title_row = self.conn.execute(...).fetchone()   # → sqlite3.Row
title_row = title_row["title"] if title_row else ""  # → str（变量被复写为不同型）
```

虽然功能正确，但变量名 `title_row` 先表示 Row 对象后表示字符串，可读性不佳。建议改为：

```python
title_row = self.conn.execute(...).fetchone()
title_text = title_row["title"] if title_row else ""
```

---

### NEW-7. `import re as _re` 位于 if 分支内部

**文件**: `khub/api.py:158`

```python
if fmt == "html":
    import re as _re
```

标准 Python 惯例中 `import` 位于文件顶部。当前做法功能正确（Python 允许），但可能触发 lint 工具告警，也略微增加每次 HTML 请求时的 import 开销。建议移至文件顶部。

---

### NEW-8. `POST /resolve` 端点 path 解析在边界情况下返回空 ID

**文件**: `khub/api.py:202-203`

```python
if method == "POST" and path.endswith("/resolve"):
    cid = unquote(path[len("/documents/"):-len("/resolve")])
```

当请求路径为 `/resolve`（无 `/documents/` 前缀）时，`path[11:-8]` 返回空字符串。后续 `resolve_conflict("", keep_id)` 会因找不到版本而返回 400。功能无害（返回 400 而非崩溃），但可补充路径前缀校验提前返回 404。

---

## 未修复的 R1 轮建议

以下 R1 轮 🟡/🔵 问题本次未修复，供后续参考：

| ID | 问题 | 等级 | 当前状态 |
|----|------|------|----------|
| R6 | 冲突视图硬编码取最后两个版本 | 🟡 | 未修复 — `script.js:211` 仍为 `vers[length-2], vers[length-1]` |
| R7 | 编辑 HTML 文档丢失格式 | 🟡 | 未修复 — 即 NEW-4 |
| R9 | `_html_page()` 每次请求读盘 | 🟡 | 未修复 — `api.py:362-365` 未缓存 |
| R10 | 无并发请求去重 / AbortController | 🟡 | 未修复 — 快速点击仍可能并发 |
| R13 | 主题切换按钮无障碍 | 🔵 | 未修复 |
| R14 | `esc()` 不转义单引号 | 🔵 | 未修复 |
| R15 | `#stats` 内联样式未移至 CSS | 🔵 | 未修复 |
| R16 | 无 `<meta name="color-scheme">` | 🔵 | 未修复 |
| R17 | CSS `@media` 选择器可简化 | 🔵 | 未修复 |

---

## 总结

| 类别 | 数量 | 关键项 |
|------|------|--------|
| ✅ 正确修复 | 7 | R1, R3, R4, R5, R8, R11, R12（已实现但过度） |
| 🔴 **新问题·必须修复** | **2** | PUT 无条件 resolve_conflict 导致版本翻倍；current_version 不一致 |
| 🟡 **新问题·建议修复** | **3** | 正则吞非安全标签间文本(NEW-3)；PUT 未传 format 丢格式(NEW-4)；前端过滤可加固(NEW-5) |
| 🔵 **仅供参考** | 3 | 变量命名(NEW-6)；import 位置(NEW-7)；边界 path 解析(NEW-8) |
| 🔵 未修复（R1 遗留） | 7 | R6, R7, R9, R10, R13-R17 |

**核心风险**: NEW-1（版本翻倍）应优先修复。该问题导致每次编辑产生重复版本，长期运行显著放大 version 表体积。修复成本低：仅在文档确实处于冲突状态时才清除冲突标记，不调用 `resolve_conflict`。

**次要风险**: NEW-4（丢格式）影响用户编辑体验但无数据安全风险。NEW-3（文本丢失）在安全优先的权衡下可接受，但建议后续以更精确的正则替换。
