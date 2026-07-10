# 文档版本 Diff 第 1 轮代码评审

评审提交：1566608（分支 m1）

评审范围：
- `khub/diff.py` — LCS 行级 diff 算法 + `diff_to_html` 渲染
- `khub/api.py` — `GET /documents/{id}/diff` 端点
- `khub/web/script.js` — `loadDiff()` 函数 + 比较按钮

---

## 1. khub/diff.py

### 1.1 LCS 算法正确性

**结论：正确。** 标准 DP 实现，构建 `(m+1)×(n+1)` LCS 长度表后回溯生成结果。

| 边界情况 | 预期 | 实际 | 判定 |
|----------|------|------|------|
| `old=""`, `new=""` | `[]` | `[]`（`dp=[[0]]`，while 不进入，返回空列表） | 正确 |
| `old="a"`, `new=""` | `[delete]` | `[{"type":"delete","content":"a",...}]` | 正确 |
| `old=""`, `new="a"` | `[insert]` | `[{"type":"insert","content":"a",...}]` | 正确 |
| 全部不同 | 全部 `delete`/`insert` 交错 | 按 LCS 回溯产生正确序列 | 正确 |
| 全部相同 | 全部 `equal` | 全部 `equal`，行号正确 | 正确 |

`old_ln`/`new_ln` 在回溯时从底向上记录，出栈后恢复正序，语义正确。

### 1.2 性能：O(mn) 空间复杂度

**严重性：中等 — 大文档风险**

- 当前实现构建完整 `(m+1)×(n+1)` DP 表。m、n 为行数。
- 当文档较大（如 10k 行 × 10k 行），DP 表 = 1 亿个 int，单 Python int 约 28 字节 → ~2.8 GB 内存，不可接受。
- 典型用药说明/病历几百行时无影响，但建议为长期安全做调用方长度兜底。

**建议：**
1. 短期：在 `diff_lines()` 入口对行数做软限（如 max 5000 行），超限返回退化结果（如“文档过大，无法比较”）。
2. 长期：替换为 Myers diff 算法（O(ND) 时间，O(N) 空间），或 Hirschberg 分治（O(min(m,n)) 空间）。

### 1.3 XSS 安全性

**结论：安全。**

```python
content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
```

- 用户内容经 `&`/`<`/`>` 三段转义后嵌入 `<span>` 文本节点。
- `class` 和 `style` 属性值使用硬编码字符串，非用户输入，安全。
- `old_ln`/`new_ln` 来源于算法（整数或 `None`），不经 HTML 转义直接被 `str()` 渲染，但在属性值上下文中整数是安全的。

### 1.4 其他

- `splitlines(keepends=True)` 保留换行符，使 diff 结果中能够体现换行位置。好。
- `diff_to_html` 返回拼接字符串而非逐行 append 到列表：字符串拼接 O(n²) 但 n 为行数（通常 < 10k），尚可接受。如将来行数增多可改为 `''.join(lines_html_list)`。

---

## 2. khub/api.py — diff 端点

### 2.1 路由与参数验证

```python
# 第 200–219 行
if len(parts) >= 2 and parts[1] == "diff":
    ...
    v1 = _safe_int(qs.get("v1", [0])[0], 0)
    v2 = _safe_int(qs.get("v2", [0])[0], 0)
    if not v1 or not v2:
        return 400, {"error": "请指定 v1 和 v2（版本 ID）"}
```

- `_safe_int` 对非法输入回退默认值，不会抛 `ValueError` → 安全。
- `not v1 or not v2` 检查 0 值，但**不拒绝负数**。负数 version_id 会导致 `get_version` 返回 None → 最终返回 404。功能正确，但语义不够精确。建议改为 `if v1 <= 0 or v2 <= 0`。

### 2.2 错误处理

- `get_version` 返回 None 时返回 404，正确。
- `diff_lines` 不抛异常（纯算法），无需 try/except。

### 2.3 大文档风险

**严重性：中等**

- 版本内容端点（`/versions/{vid}`）在第 185 行做了 `content[:100000]` 截断，但 **diff 端点未做截断**。
- 入站内容 `ver1["content"]` 可能为数十万字符，直接传给 `diff_lines`，触发 1.2 节分析的 O(mn) 内存问题。

**建议：**
- 在 `diff_lines` 调用前对 `ver1["content"]` 和 `ver2["content"]` 各行数做软限；或统一截断至最大合理行数后再比对。

### 2.4 响应体体积

- 返回的 `diff` 列表包含完整 `content` 字符串，加上 `diff_html` 字段双重传输。对于大范围变更的文档，响应体可能显著膨胀。
- 前端当前只使用 `diff_html`（直接插入 innerHTML），`diff` 原始数据未被前端使用。

**建议（可选优化）：** 将 `diff` 原始列表设为可选参数（如 `?raw=true`），默认不返回，减少传输量。

---

## 3. khub/web/script.js — 前端

### 3.1 XSS：esc() 在 HTML 属性上下文中不安全

**严重性：高（理论上） / 低（实际利用难度高）**

`esc()` 定义：

```javascript
function esc(s) {
  return (s || '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
```

此函数将 `'` 转义为 `&#39;`。在 `innerHTML` 赋值的 **onclick 属性** 中，HTML 解析器会在传给 JavaScript 引擎之前解码 `&#39;` 回 `'`，使单引号逃逸。

**受影响位置（均位于 `script.js`）：**

| 行号 | 表达式 | 问题 |
|------|--------|------|
| 80 | `onclick="loadDoc(\'' + esc(r.canonical_id) + '\',...)` | canonical_id 含 `'` 时注入 |
| 83 | `onclick="loadDiff(\'' + esc(r.canonical_id) + '\',...)` | 同上 |
| 254 | `onclick="loadDoc(\'' + esc(d.id) + '\',...)` | 同上 |
| 271 | `onclick="loadDoc(\'' + esc(id) + '\');return false"` | 同上 |
| 300 | `onclick="saveDoc(\'' + esc(id) + '\')"` | 同上 |
| 301 | `onclick="loadDoc(\'' + esc(id) + '\',..."` | 同上 |
| 347–348 | `resolveConflict` onclick | 同上 |
| 393 | AI 助手来源链接 onclick | 同上 |

**实际利用条件：**
- `canonical_id` 由服务端生成（UUID / KZOCR-xxx 格式），不含用户可控的 `'` 字符。
- 但如果未来引入用户自定义 ID 或允许标题/元数据影响 ID 生成方式，攻击面会打开。

**建议修复：**
```javascript
// 方案 A：用 encodeURIComponent + JSON.stringify 构建属性
el.setAttribute('onclick', "loadDoc('" + encodeURIComponent(id) + "')");

// 方案 B（推荐）：避免模板字符串到 onclick，改用 addEventListener
btn.addEventListener('click', () => loadDoc(id));

// 方案 C（最小改动）：数据属性 + 事件委托
el.dataset.docId = id;
```

**推荐方案 B**：消除所有内联 onclick，统一使用 `addEventListener` 或事件委托。

### 3.2 loadDiff() 额外 HTTP 请求

```javascript
const vers = await fetch('/documents/' + encodeURIComponent(id) + '/versions').then(x => x.json());
const last = vers[vers.length - 1], prev = vers[vers.length - 2];
```

- 在 `loadDoc` 中已经获取了 `r.version_count`，但未传递给 `loadDiff` 复用。
- `loadDiff(id, versionCount)` 的第二个参数未使用。

**建议：** 在 `loadDoc` 的 `loadDiff` 调用中传入两个最新版本号，避免一次 `/versions` 列表请求。

### 3.3 fetch 响应缺少 ok 检查

```javascript
const r = await fetch('/documents/' + ... + '/diff?v1=' + ...).then(x => x.json());
if (r.error) { ... }
```

- 依赖服务端在非 2xx 时返回 JSON 格式的 `{"error": ...}`。如果服务端返回 HTML 错误或纯文本（如 nginx 502），`.json()` 会抛异常，被外层 catch 捕获 → 显示"加载失败: ..."。这是可接受的错误降级。
- 但做一次 `r.ok` / `r.status` 检查更健壮，可区分服务端错误和网络错误。

### 3.4 diff 容器高度固定

```html
<div style="border:1px solid ...;max-height:600px;overflow-y:auto">
```

- 固定 600px 高度对长 diff 会强制滚动，OK。
- 无数据时（空 diff）渲染一个空 div，保留了边框和表头。需要确认此场景是否友好——diff 为空时应显示"无差异"提示而非空白面板。

---

## 4. 综合评分与优先级

| 编号 | 问题 | 严重性 | 优先级 |
|------|------|--------|--------|
| F1 | `esc()` 在 onclick 属性中的 XSS 逃逸 | 高（理论）/ 低（实际利用） | 高 — 修复成本低，应在更多 ID 来源开放前修 |
| F2 | O(mn) 空间复杂度对大文档不友好 | 中 | 中 — 加行数软限即可 |
| F3 | diff 端点未截断超大内容 | 中 | 中 — 与 F2 联动 |
| S1 | 负数 version_id 未被明确拒绝 | 低 | 低 |
| S2 | `loadDiff` 未复用 `versionCount` 参数 | 低 | 低 |
| S3 | diff 响应双倍数据（raw + html） | 低 | 可选 |
| S4 | 空 diff 时空白面板 | 低 | 低 |

## 5. 修复建议摘要

### 必须修复（高优先级）

1. **`script.js`：消除内联 onclick 中的 `esc()` 逃逸。** 最低成本方案：对所有 `innerHTML` 中的 onclick 属性改为 `JSON.stringify(id)` 编码（利用 JS 的 JSON 序列化保证安全）。最佳方案：全部替换为 `addEventListener`。

### 建议修复（中优先级）

2. **`diff.py` 或 `api.py`：加行数上限。** 在 `diff_lines()` 或 API 层，若 `old_lines` 或 `new_lines` 超过阈值（如 5000 行），返回合理退化提示。
3. **`api.py`：diff 端点对 content 做截断后 diff。** 与版本内容端点行为一致。
4. **`script.js`：在 diff 结果为空时显示"无差异"提示。** 检查 `r.changes === 0` 时的 UI 呈现。

### 可选优化（低优先级）

5. `api.py`：`not v1 or not v2` → `v1 <= 0 or v2 <= 0`。
6. `script.js`：复用 `versionCount` 参数避免额外 HTTP 请求。
7. 长远：将 LCS 替换为 Myers diff 以改善空间效率。

---

*评审日期：2026-07-10*
*评审人：CodeBuddy Code（general-purpose-47）*
