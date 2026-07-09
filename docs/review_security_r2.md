# 安全加固代码评审报告（R2）

- **评审范围**: Commit `ff0a842` — 对 R1 报告（`b3b699e`）的修复实施
- **评审文件**: `khub/api.py`
- **基线提交**: `6af4d4f`（原始安全加固）
- **评审日期**: 2026-07-10

---

## 1. R1 修复逐项验证

### 1.1 P0 — CSP `script-src 'self'` → `script-src 'self' 'unsafe-inline'`

**状态: ✅ 正确修复**

```python
# api.py:440
"default-src 'self'; script-src 'self' 'unsafe-inline'; "
```

当前 WebUI 在 `index.html` 和 `script.js` 中共约 17 处内联 `onclick` 属性或动态生成的 `onclick` 字符串，`'unsafe-inline'` 使所有这些处理器恢复正常执行：

| 位置 | 模式 | 数量 | CSP 兼容 |
|------|------|------|----------|
| `index.html` | 直接 `onclick="..."` 属性 | 7 处 | ✅ |
| `script.js` 动态 HTML | 字符串拼接 `onclick=\"...\"` | 10 处 | ✅ |
| `script.js` DOM 属性 | `el.onclick = fn` | 3 处 | ✅（非内联，不受 CSP 影响）|

### 1.2 P0 — 静态文件 MIME 类型（`_MIME` 字典）

**状态: ✅ 正确修复**

```python
# api.py:19-29
_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".json": "application/json",
}
```

- 当前 WebUI 文件（`index.html`, `style.css`, `script.js`）三种扩展名均已覆盖 ✅
- 使用 `.lower()` 归一化扩展名，防止大小写绕过 ✅
- 未知扩展名回退 `application/octet-stream`，配合 `X-Content-Type-Options: nosniff` 使浏览器拒绝执行 ✅
- **完整性评估**: 当前 WebUI 无 `.gif`/`.webp`/`.woff`/`.ttf`/`.map` 等文件引用，映射集合恰好满足当前需求

### 1.3 P3 — CSP 补充 `base-uri 'self'; object-src 'none'`

**状态: ✅ 正确修复**

```python
# api.py:443
"frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
```

- `base-uri 'self'` 防止 `<base>` 标签劫持相对 URL ✅
- `object-src 'none'` 禁用 `<object>/<embed>/<applet>` 插件加载 ✅
- 确认 CSP 仅在 `ctype == "text/html; charset=utf-8"` 时设置（line 438），符合 CSP 规范（仅文档级响应需要）✅

---

## 2. WebUI 兼容性最终验证

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 内联 onclick 事件处理器 | ✅ | `'unsafe-inline'` 覆盖所有 17 处 |
| `<link>` 加载 CSS | ✅ | `Content-Type: text/css` + `nosniff` 正确 |
| `<script>` 加载 JS | ✅ | `Content-Type: application/javascript` + `nosniff` 正确 |
| 内联 style 属性 | ✅ | `style-src 'self' 'unsafe-inline'` |
| `<img>` 图片加载 | ✅ | `img-src 'self' data:` |
| 表单提交 | ✅ | 无表单动作，`form-action 'none'` 无影响 |
| AI 弹窗交互 | ✅ | 无外部资源依赖 |
| 深色/浅色主题切换 | ✅ | `toggleTheme()` 通过 onclick 调用 |

**结论**: WebUI 在修复后的 CSP + MIME 配置下可正常工作。✅

---

## 3. 剩余未修复问题（来自 R1）

### 3.1 🔴 P2 — `Transfer-Encoding: chunked` 绕过体积极限

**状态: ❌ 未修复**

`do_POST` (line 497)、`do_PUT` (line 532)、`do_DELETE` (line 552) 三处均使用：

```python
length = int(self.headers.get("Content-Length", 0) or 0)
```

当客户端使用 `Transfer-Encoding: chunked` 且不发送 `Content-Length` 时：
- `Content-Length` 头不存在 → `get(..., 0)` 返回 `0` → `length = 0`
- 限流判定 `length > _MAX_BODY_SIZE` → `False` → **绕过**
- `self.rfile.read(0)` 返回空 → `body` 被替换为 `b"{}"`
- 对于需要 body 的端点（如 `POST /documents`），body 被静默丢弃

**影响**: 攻击者可发送超过 10MB 的 chunked 请求；同时，合法 chunked 请求的 body 被静默丢弃，导致 PUT/POST 操作静默失败。

**建议修复**:

```python
# 在 do_POST / do_PUT / do_DELETE 开头增加
te = self.headers.get("Transfer-Encoding", "").lower()
if te == "chunked":
    return self._send(413, {"error": "chunked encoding 不支持"})
```

或更严格的方案：要求 Content-Length 必须存在：

```python
content_length = self.headers.get("Content-Length")
if content_length is None:
    return self._send(411, {"error": "缺少 Content-Length"})
length = int(content_length) if content_length else 0
```

### 3.2 🟡 P4 — Content-Length 格式异常保护

**状态: ❌ 未修复**

三处均直接 `int(...)` 未包裹 try/except：

```python
length = int(self.headers.get("Content-Length", 0) or 0)
```

若 `Content-Length` 包含非数字字符（如 `"abc"`），`int("abc")` 抛出 `ValueError`，未被捕获 → **500 Internal Server Error**。

HTTP 协议中 `Content-Length` 应为纯数字，`http.server.BaseHTTPRequestHandler` 的底层解析已有一定校验，但防御性编程仍建议增加保护。

```python
try:
    length = int(self.headers.get("Content-Length", 0) or 0)
except (ValueError, TypeError):
    return self._send(400, {"error": "无效的 Content-Length"})
```

### 3.3 🟢 P3 — 缺失安全响应头

**状态: ❌ 未添加**

| 响应头 | 建议值 | 当前状态 |
|--------|--------|----------|
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains` | ❌ 缺失 |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | ❌ 缺失 |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | ❌ 缺失 |

**减轻因素**: 当前仅以 HTTP 运行在本地 `127.0.0.1`，不涉及 SSL/TLS，HSTS 无实际影响。这些属于预防性加固，可在后续迭代添加。

### 3.4 🟢 P3 — `_send_sse` 硬编码 `Access-Control-Allow-Origin: *`

**状态: ❌ 未修改**

`_send_sse` (line 470) 仍硬编码 `Access-Control-Allow-Origin: *`，与 `do_OPTIONS` (line 524) 中的 CORS 头不一致但实际兼容。

**改善建议**: 可将 CORS 来源与 `KHUB_API_TOKEN` 联动：有 token 时设为 `*`（已有鉴权），无 token 时限制更严格。

---

## 4. R2 新增发现

### 4.1 🟡 P4 — 请求体大小校验代码三重重复

`do_POST` (line 497-499)、`do_PUT` (line 532-534)、`do_DELETE` (line 552-554) 完全相同的一段校验逻辑重复三次：

```python
length = int(self.headers.get("Content-Length", 0) or 0)
if length > _MAX_BODY_SIZE:
    return self._send(413, {"error": "请求体过大（上限 10MB）"})
raw = self.rfile.read(length) if length else b"{}"
```

**建议**: 提取为 `Handler` 的静态方法或函数，减少重复，降低未来修复不一致的风险。

```python
@staticmethod
def _read_body(headers, rfile):
    """安全读取请求体，校验大小上限。"""
    try:
        length = int(headers.get("Content-Length", 0) or 0)
    except (ValueError, TypeError):
        return None, 400, {"error": "无效的 Content-Length"}
    if length > _MAX_BODY_SIZE:
        return None, 413, {"error": "请求体过大（上限 10MB）"}
    raw = rfile.read(length) if length else b"{}"
    return raw, None, None
```

### 4.2 ✅ `_MIME` 映射完备性

| 扩展名 | Content-Type | 当前 WebUI 使用 |
|--------|-------------|----------------|
| `.html` | `text/html; charset=utf-8` | `index.html` ✅ |
| `.css` | `text/css; charset=utf-8` | `style.css` ✅ |
| `.js` | `application/javascript; charset=utf-8` | `script.js` ✅ |
| `.png` | `image/png` | 未使用（但有备无患）✅ |
| `.jpg` / `.jpeg` | `image/jpeg` | 未使用 ✅ |
| `.svg` | `image/svg+xml` | 未使用 ✅ |
| `.ico` | `image/x-icon` | 未使用 ✅ |
| `.json` | `application/json` | 未使用 ✅ |

映射集合对当前 WebUI 完备，未来扩展新文件类型时需同步更新。

### 4.3 ✅ 路径穿越防御稳固

`dispatch()` 中静态文件服务（line 62-66）使用 `os.path.realpath` 双校验，且要求文件路径必须以 `web_dir + os.sep` 开头。该防御在此次变更中未被修改且未退化。✅

---

## 5. 最终严重性分级

| # | 问题 | 严重性 | 分类 | 状态 |
|---|------|--------|------|------|
| 1 | 内联 onclick 被 `script-src 'self'` 阻断 | 🔴 P0 | 功能阻断 | ✅ **已修复** |
| 2 | 静态文件 MIME 类型错误 + nosniff 导致 JS/CSS 被拒 | 🔴 P0 | 功能阻断 | ✅ **已修复** |
| 3 | 缺少 `base-uri 'self'` 和 `object-src 'none'` | 🟢 P3 | CSP 修补 | ✅ **已修复** |
| 4 | `Transfer-Encoding: chunked` 绕过 10MB 体积极限 | 🟡 P2 | 安全绕过 | ❌ **未修复** |
| 5 | `Content-Length` 格式异常 → 500 崩溃 | ⚪ P4 | 健壮性 | ❌ **未修复** |
| 6 | 请求体校验代码三重重复 | ⚪ P4 | 可维护性 | ❌ **未修复**（新发现）|
| 7 | 缺少 `Strict-Transport-Security` | 🟢 P3 | 安全加固 | ❌ 未添加（可接受）|
| 8 | 缺少 `Referrer-Policy` | 🟢 P3 | 安全加固 | ❌ 未添加（可接受）|
| 9 | 缺少 `Permissions-Policy` | 🟢 P3 | 安全加固 | ❌ 未添加（可接受）|
| 10 | `_send_sse` 硬编码 `Access-Control-Allow-Origin: *` | 🟢 P3 | 配置异议 | ❌ 未修改（可接受）|

---

## 6. 结论

R1 报告中的 **两个 P0 功能阻断问题已全部修复**，WebUI 在当前 CSP + MIME 配置下可正常工作。

**推荐意见**: 当前提交可以合并，但建议在合并前或合并后尽快跟进修复以下两个问题：

1. **🔴 P2 — `Transfer-Encoding: chunked` 绕过**：这是唯一真正的安全漏洞。修复成本极低（增加 2-3 行 chunked 检测），建议在当前迭代中修复。
2. **⚪ P4 — Content-Length 异常保护和代码重复**：属于防御性编程和可维护性改进，可安排低优先级修复。

其余 P3 级别的缺失安全头（HSTS/Referrer-Policy/Permissions-Policy）属于预防性加固，在当前纯本地 HTTP 部署场景下不构成实际风险，可延迟到后续迭代。

---

*Reviewer: code-reviewer-16*
