# WebUI 第 1 轮代码评审报告

**评审范围**: commit `eaabdcf` — C WebUI 升级  
**评审日期**: 2026-07-10  
**评审人**: code-reviewer-3  
**评审方式**: 人工静态分析 + 工具辅助

---

## 严重等级说明

| 标记 | 含义 | 行动建议 |
|------|------|----------|
| 🔴 **必须修复** | 安全漏洞 / 数据正确性问题 / 逻辑错误 | 合入前必须修复 |
| 🟡 **建议修复** | 边界情况 / 防御性编程缺失 / 性能隐患 | 建议本轮修复 |
| 🔵 **仅供参考** | 代码风格 / 可维护性 / 微优化 | 低优先级，下轮改进 |

---

## 🔴 必须修复

### R1. `resolve_conflict` 忽略 `keep_version_id`（数据丢失风险）

**文件**: `khub/db.py:279-285` + `khub/api.py:192`

```python
# db.py
def resolve_conflict(self, canonical_id: str, keep_version_id: int):
    """解决冲突：清除冲突标记。keep_version_id 表示用户选择保留的版本。"""
    with self._lock:
        self.conn.execute(
            "UPDATE documents SET conflict=0 WHERE canonical_id=?",
            (canonical_id,))
        self.conn.commit()
```

**问题**: 函数签名明确接受 `keep_version_id`，但方法体完全忽略该参数，仅清除了 `conflict=0` 标记。未将用户选择的版本内容写入为新版本，也未记录哪个版本被保留。若在冲突解决后需要回溯或审计，用户的选择历史永久丢失。

**修复方案**: 将所选版本的内容作为新版本写入，或在 `documents` 表额外记录 `resolved_version_id`：

```python
def resolve_conflict(self, canonical_id: str, keep_version_id: int):
    with self._lock:
        # 读取所选版本的内容
        ver = self.conn.execute(
            "SELECT * FROM document_versions WHERE version_id=? AND doc_id=?",
            (keep_version_id, canonical_id)).fetchone()
        if not ver:
            raise ValueError(f"version {keep_version_id} not found for doc {canonical_id}")
        # 创建新版本表示解决结果
        c = self.conn.execute(
            "INSERT INTO document_versions(doc_id, content, format, origin, author, "
            "updated_at, hash, parent_version, note) VALUES(?,?,?,?,?,?,?,?,?)",
            (canonical_id, ver["content"], ver["format"], "webui-resolve", "",
             _now(), compute_hash(ver["content"]), keep_version_id,
             f"conflict resolved, kept version {keep_version_id}"))
        vid = c.lastrowid
        self.conn.execute(
            "UPDATE documents SET conflict=0, current_version=?, updated_at=? "
            "WHERE canonical_id=?",
            (vid, _now(), canonical_id))
        # 同步 FTS
        self.conn.execute("DELETE FROM docs_fts WHERE doc_id=?", (canonical_id,))
        if ver["content"] and ver["content"].strip():
            title_row = self.conn.execute(
                "SELECT title FROM documents WHERE canonical_id=?",
                (canonical_id,)).fetchone()
            title = title_row["title"] if title_row else ""
            self.conn.execute(
                "INSERT INTO docs_fts(doc_id, title, content) VALUES(?,?,?)",
                (canonical_id, title, ver["content"]))
        self.conn.commit()
```

---

### R2. XSS：`format='html'` 路径过滤不完整（高危）

**文件**: `khub/web/script.js:85`

```javascript
const safe = (r.content || '').replace(/<script[\s\S]*?<\/script>/gi, '');
html += '<div class="doc-content">' + safe + '</div>';
```

**问题**: 仅过滤 `<script>` 标签，但以下 XSS 向量全部遗漏：
- `<img src=x onerror=alert(1)>` — 事件处理器
- `<svg onload=alert(1)>` — SVG 事件
- `<a href="javascript:alert(1)">` — `javascript:` URI
- `<iframe src="javascript:...">` — iframe
- `<details x="" open="" ontoggle=alert(1)>` — 其他事件属性
- `<body onload=alert(1)>` — body 事件

由于服务端 `store_document` 不验证内容是否含危险 HTML，且 `format='html'` 可在任何数据源设置，攻击面真实存在。

**修复方案（二选一）**:

方案 A — 服务端剥离（推荐）：在 `GET /documents/{id}` 返回时，若 `format='html'` 且来源不是受信任源（如本地导入），一律纯文本化或使用 DOMPurify 清理。

方案 B — 前端 DOMPurify：在 script.js 中引入 DOMPurify（可从 CDN 或内联加载）：

```javascript
const safe = DOMPurify.sanitize(r.content || '', {
    ALLOWED_TAGS: ['p','br','b','i','u','strong','em','h1','h2','h3','h4','h5','h6',
                   'ul','ol','li','div','span','pre','code','blockquote','table','tr','td','th'],
    ALLOWED_ATTR: ['class','style']
});
```

---

### R3. `search()` 不重置 `currentPage`（搜索失效）

**文件**: `khub/web/script.js:94-110`

```javascript
async function search(q, source) {
    if (q === undefined) q = document.getElementById('q').value.trim();
    if (!q) return;
    lastQuery = q;
    lastSource = source !== undefined ? source : document.getElementById('sourceFilter').value;
    renderSkeletons(3, 'list');
    try {
        const r = await fetch('/search?q=' + encodeURIComponent(q) + '&page=' + currentPage + ...);
```

**问题**: 当用户输入全新查询后点击"检索"按钮时，`currentPage` 未归零。若此前进行过分页导航（如第 5 页），新搜索直接从第 5 页开始请求，可能显示"第 5 页无结果"。

旧版（内联代码）在 `search()` 开头有 `currentPage=0`，新版本意外丢失此逻辑。

**修复**:

```javascript
async function search(q, source) {
    if (q === undefined) q = document.getElementById('q').value.trim();
    if (!q) return;
    currentPage = 0;  // ← 插入此行
    lastQuery = q;
    ...
```

---

### R4. SSE 流式请求缺少 `resp.ok` 检查（请求失败静默吞掉）

**文件**: `khub/web/script.js:286`

```javascript
const resp = await fetch('/ask', { method: 'POST', ... });
const reader = resp.body.getReader();  // 若 resp.ok=false，body 可能为空或非可读流
```

**问题**: 当服务器返回 400/401/500 等错误状态码时：
- `resp.body.getReader()` 可能抛出异常或返回空流
- 即使不抛异常，错误的 HTTP 状态码会跨过 `catch` 处理（`fetch` 仅在网络错误时 reject），最终用户看到空白的 AI 回复或 `[object Object]` 类型的错误内容

**修复**:

```javascript
const resp = await fetch('/ask', { method: 'POST', ... });
if (!resp.ok) {
    const errData = await resp.json().catch(() => ({ error: resp.statusText }));
    aiAppendToken(aiBubble, '[请求失败: ' + (errData.error || resp.status) + ']');
    return;
}
const reader = resp.body.getReader();
```

---

## 🟡 建议修复

### R5. PUT `/documents/{id}` 未做路径长度/格式校验

**文件**: `khub/api.py:167-168`

```python
if method == "PUT" and path.startswith("/documents/") and len(path) > len("/documents/"):
    cid = unquote(path[len("/documents/"):])
```

**问题**: 未处理路径含其他段（`/documents/foo/bar`）的情况。`/documents/foo/bar` 会被解析为 `cid="foo/bar"`，写入数据库。后续 GET 可能无法正确匹配此 ID（path router 会误判为 `/documents/{id}/versions` 等）。

**修复**:

```python
if method == "PUT" and path.startswith("/documents/") and len(path) > len("/documents/"):
    rest = path[len("/documents/"):]
    if "/" in rest:
        return 400, {"error": "invalid document id (path too deep)"}
    cid = unquote(rest)
```

---

### R6. 冲突视图硬编码取最后两个版本

**文件**: `khub/web/script.js:210`

```javascript
const v1 = vers[vers.length - 2], v2 = vers[vers.length - 1];
```

**问题**: 假设冲突一定在最新两个版本之间。但冲突可能由手动标记（`mark_conflict`）或同步流程在任意版本对上产生。若版本数 > 2，取最后两个可能不是实际冲突的两个版本，用户可能选择放弃其中一个。

**修复建议**: 服务端返回冲突信息时附带冲突涉及的 `version_id` 对，而非前端推测。

---

### R7. 编辑 HTML 文档时丢失格式

**文件**: `khub/web/script.js:172`

```javascript
const origContent = contentEl ? contentEl.textContent : '';
```

**问题**: `textContent` 剥离所有 HTML 标签。若文档 `format='html'`，用户进入编辑模式后看到的纯文本不含任何标记，保存后 HTML 文档被无声转换为纯文本。使用者可能不知道格式信息已丢失。

**修复建议**: 根据 `format` 决定：若为 `format='html'`，使用 `innerHTML` 或从 API 单独获取原始内容；保存时保持原始格式。

---

### R8. `int(keep_id)` 未捕获 `ValueError`

**文件**: `khub/api.py:192`

```python
self.store.resolve_conflict(cid, int(keep_id))
```

**问题**: 若请求体 `keep_version` 为字符串或非数字类型（如 `"abc"` 或 `null`），`int(keep_id)` 抛出 `ValueError` 且无捕获，返回 500。

**修复**: 使用 `_safe_int` 或 try/except：

```python
try:
    keep_id = int(keep_id)
except (TypeError, ValueError):
    return 400, {"error": "keep_version 必须是有效整数"}
```

---

### R9. `_html_page()` 每次请求读盘

**文件**: `khub/api.py:337-346`

```python
@staticmethod
def _html_page():
    page_path = os.path.join(os.path.dirname(__file__), "web", "index.html")
    with open(page_path, encoding="utf-8") as f:
        return f.read()
```

**问题**: 每次 `GET /` 请求都从磁盘读取 `index.html`（约 1.2KB）。虽然不是大开销，但在高并发下仍有不必要的 I/O。更关键的是：若部署后热更新了 index.html，旧内容会因为浏览器缓存 / 文件句柄导致不一致。

**修复建议**: 缓存文件内容和 mtime，仅在文件发生变化时重新读取；或在开发/生产环境中使用不同的加载策略。

---

### R10. 无并发请求去重 / AbortController

**文件**: `khub/web/script.js` 多处

**问题**: 用户快速点击"检索"或"语义"或"全部文档"时，多个 `async fetch` 并发执行，后完成的覆盖先完成的。最后渲染结果取决于网络延迟而非用户意图。

**修复建议**: 使用 AbortController 在发起新请求时取消前一个未完成的请求：

```javascript
let searchController = null;
async function search(q, source) {
    if (searchController) searchController.abort();
    searchController = new AbortController();
    const r = await fetch('/search?...', { signal: searchController.signal });
    ...
}
```

---

### R11. 冲突解决时未并发加载两个版本

**文件**: `khub/web/script.js:211-212`

```javascript
const c1 = await fetch('/documents/' + encodeURIComponent(id) + '/versions/' + v1.version_id).then(x => x.json());
const c2 = await fetch('/documents/' + encodeURIComponent(id) + '/versions/' + v2.version_id).then(x => x.json());
```

**问题**: 两个版本内容是顺序加载的，版本内容较大时会增加用户等待时间。

**修复**: 使用 `Promise.all` 并行加载：

```javascript
const [c1, c2] = await Promise.all([
    fetch(`/documents/${encodeURIComponent(id)}/versions/${v1.version_id}`).then(x => x.json()),
    fetch(`/documents/${encodeURIComponent(id)}/versions/${v2.version_id}`).then(x => x.json()),
]);
```

---

### R12. PUT 创建新版本后没有处理冲突标记

**文件**: `khub/api.py:167-184`

**问题**: 用户通过 WebUI 编辑文档时，如果该文档当前处于冲突状态（`conflict=1`），`store_document` 创建了新版本但未清除 `conflict` 标记。这可能导致文档永远卡在冲突状态。

**修复建议**: PUT 处理完后应检查并清除冲突标记，或在 `store_document` 中当有新版写入时自动清除。

---

## 🔵 仅供参考

### R13. 主题切换按钮 aria-label / 无障碍

**文件**: `khub/web/index.html:9`

```html
<button class="theme-toggle" onclick="toggleTheme()" title="切换深色/浅色模式">🌙</button>
```

- `title` 属性在触摸设备上不显示，应考虑用 `aria-label` 替代或补充。
- 无可见的 `:focus-visible` 样式，键盘用户无法感知焦点位置。
- 所有 `div` 卡片上的 `onclick=loadDoc(...)` 对键盘用户不可见（应添加 `tabindex="0"` + `onkeydown` 或使用 `<a>` 标签）。
- `onclick` 中的 `return false` 模式（如 `loadAll();return false`）在 JS 禁用时或脚本出错时，`#` 链接会让页面跳到顶部。建议用 `href="javascript:void(0)"` 或内联 `event.preventDefault()`。

### R14. `esc()` 不在属性上下文中保护

**文件**: `khub/web/script.js:9`

```javascript
function esc(s) { return (s || '').replace(/[&<>]/g, c => ...); }
```

当前 JS 代码中所有内联 `onclick` 模板字符串（如 `editDoc('esc(id)','esc(title)')`）都已对参数使用 `esc()`。由于 `esc()` 不转义单引号 `'`，若某个 `id` 或 `title` 通过其他路径（不是 `esc()`）拼接进单引号包裹的属性中，可能被突破。目前各调用点已正确使用 `esc()`，暂未发现突破路径，但仍建议补上 `'` 转义加固。

### R15. `#stats` 内联样式应移至 CSS

**文件**: `khub/web/index.html:12`

```html
<div id="stats" style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px"></div>
```

内联样式与外部 CSS 的分离目标矛盾。应移至 `style.css`：

```css
#stats { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
```

### R16. 主题切换时无 `<meta name="color-scheme">`

若系统原生控件（滚动条、输入框、选择框）跟随主题，应在 `<head>` 中添加：

```html
<meta name="color-scheme" content="light dark">
```

或 JS 中动态设置：

```javascript
document.documentElement.style.colorScheme = next;
```

目前 `select` 和 `input` 的默认滚动条/下拉箭头在深色模式下仍为浅色，视觉突兀。

### R17. `@media (prefers-color-scheme: dark)` 选择器可简化为 `[data-theme="dark"]`

**文件**: `khub/web/style.css:31-47`

当前通过 `@media + :root:not([data-theme="light"])` 实现 OS 级深色自动适配。逻辑正确但 CSS 重复（与 `[data-theme="dark"]` 的定义几乎相同）。可考虑用单一 `[data-theme="dark"]` 配合 JS 在 `initTheme` 时检测 `prefers-color-scheme` 来简化。

---

## 测试覆盖缺口

| 场景 | 当前状态 | 建议 |
|------|----------|------|
| PUT `/documents/{id}` 创建版本 | ❌ 无测试 | 测试版本创建、FTS 更新、冲突标记清除 |
| POST `/documents/{id}/resolve` | ❌ 无测试 | 测试 resolve 后 conflict 归零、新版本创建、无效 keep_version 400 |
| GET `/documents/{id}/versions/{vid}` | ❌ 无测试 | 测试版本存在/不存在、content 截断 |
| HTML 格式文档 XSS | ❌ 无测试 | 测试 `<script>`、事件处理器、`javascript:` URI 等向量 |
| 搜索分页 state 重置 | ❌ 无测试 | 测试切换查询后 currentPage 归零 |
| SSE 流式 400/401 响应 | ❌ 无测试 | 测试非 200 响应时前端错误显示 |
| 冲突视图 >2 个版本 | ❌ 无测试 | 测试版本数 >2 时视图正确性 |
| 编辑 HTML 格式文档 | ❌ 无测试 | 测试编辑后格式保持 |
| 深色模式 + 静态文件热更新 | ❌ 无测试 | 测试 localStorage 持久化、文件缓存行为 |

---

## 总结

| 严重程度 | 数量 | 关键项 |
|----------|------|--------|
| 🔴 必须修复 | 4 | `resolve_conflict` 忽略 keep_version、HTML XSS 过滤不全、search currentPage 未重置、SSE 无 resp.ok 检查 |
| 🟡 建议修复 | 8 | 路径校验、冲突视图硬编码、编辑丢格式、int 转换异常、文件读盘、并发去重、版本加载串行、冲突状态未清理 |
| 🔵 仅供参考 | 5 | 无障碍标签、esc 加固、内联样式、color-scheme、CSS 选择器简化 |

整体架构合理，外部化 html/css/js 的决策正确。核心问题是 `resolve_conflict` 的数据语义缺失（第 R1）和 HTML 格式的 XSS 防护不完整（第 R2），这两项修复后方可合入。
