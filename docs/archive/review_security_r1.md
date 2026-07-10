# 安全加固代码评审报告（R1）

- **评审范围**: Commit `6af4d4f` — CSP 响应头 + 请求体大小上限 + X-Content-Type-Options / X-Frame-Options
- **评审文件**: `khub/api.py`（18 行新增）
- **评审日期**: 2026-07-10

---

## 1. CSP 正确性：是否会破坏现有 WebUI？

### 1.1 结论：**会破坏。必须修复后再合并。**

现有 WebUI（`khub/web/index.html`）存在以下与 CSP `script-src 'self'` 冲突的模式：

#### (a) 内联 onclick 事件处理器（全部被阻断）

`index.html` 中大量使用 `onclick="..."` 行内事件处理器，CSP `script-src 'self'` **不允许** 任何内联 JavaScript（包括事件处理器属性、`<script>...</script>` 块、`javascript:` URL），除非显式添加 `'unsafe-inline'` 或 `'unsafe-hashes'`。

被阻断的元素（共约 10 个）：

| 位置 | 元素 | 处理器 |
|------|------|--------|
| line 9 | `<button class="theme-toggle">` | `onclick="toggleTheme()"` |
| line 15 | `<button>` | `onclick="search()"` |
| line 16 | `<button class="ghost">` | `onclick="semantic()"` |
| line 17 | `<button class="ghost">` | `onclick="loadAll()"` |
| line 18 | `<button class="ghost">` | `onclick="loadConflicts()"` |
| line 33 | `<button class="fab">` | `onclick="aiToggle()"` |
| line 35 | `<button class="close">` | `onclick="aiToggle()"` |
| line 39 | `<button id="ai-send">` | 此按钮通过 `addEventListener` 绑定 ✅ 不受影响 |

此外，`script.js` 中通过 `innerHTML` 动态渲染的 HTML 也包含 `onclick`，例如 `card()`、`loadDoc()`、`loadConflictView()`、`editDoc()` 等函数中内联的 `onclick` 属性——这些同样会被 CSP 阻断。

#### (b) 静态文件 MIME 类型错误（nosniff 暴露的预存 bug）

`dispatch()` 中静态文件服务（`/web/*` 路径）将所有文件以 `application/octet-stream` 返回：

```python
return 200, f.read(), "application/octet-stream"  # 行 57
```

新增的 `X-Content-Type-Options: nosniff` 将使浏览器**拒绝加载 CSS 和 JS**，因为 MIME 类型不匹配：

- `style.css` 被标记为 `application/octet-stream` 而非 `text/css` → 浏览器拒收
- `script.js` 被标记为 `application/octet-stream` 而非 `application/javascript` → 浏览器拒执行

**后果**: WebUI 完全无法渲染（无样式、无脚本）。这是此提交**最严重的可用性问题**，需要同时修复静态文件 MIME 识别逻辑。

#### (c) 建议修复方案

1. **静态文件 MIME 修复**（先决条件）：按文件扩展名返回正确 Content-Type
   ```python
   _MIME_TYPES = {
       ".html": "text/html; charset=utf-8",
       ".css": "text/css; charset=utf-8",
       ".js": "application/javascript; charset=utf-8",
       ".png": "image/png",
       ".svg": "image/svg+xml",
       # ...
   }
   ext = os.path.splitext(filename)[1].lower()
   ctype = _MIME_TYPES.get(ext, "application/octet-stream")
   return 200, f.read(), ctype
   ```

2. **内联事件处理器迁移**：将 `index.html` 中所有 `onclick` 改为 `id` + `addEventListener`（参考 `script.js` 已使用的模式）

---

## 2. 安全响应头完整性

### 2.1 已添加（✅）
| 响应头 | 值 | 覆盖范围 |
|--------|----|----------|
| `X-Content-Type-Options` | `nosniff` | 所有响应（`_send` 中全局设置） |
| `X-Frame-Options` | `DENY` | 所有响应 |
| `Content-Security-Policy` | 见第 4 节 | 仅 `text/html` 响应 |

### 2.2 建议补充（仍然缺失）

| 响应头 | 建议值 | 理由 |
|--------|--------|------|
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains` | 如部署在 HTTPS 后，防止 SSL 剥离攻击（当前仅本地 HTTP 运行，属预防性添加） |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | 控制 Referer 泄露；默认 full Referer 可能通过外部资源泄露内部路径 |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | 禁用 WebUI 未使用的浏览器 API，减少攻击面 |

---

## 3. 请求体大小校验：边界场景分析

### 3.1 现有逻辑

```python
length = int(self.headers.get("Content-Length", 0) or 0)
if length > _MAX_BODY_SIZE:
    return self._send(413, {"error": "请求体过大（上限 10MB）"})
raw = self.rfile.read(length) if length else b"{}"
```

### 3.2 发现的边缘场景

#### (a) **`Transfer-Encoding: chunked` 绕过限流**（中风险）

当客户端使用 `Transfer-Encoding: chunked` 且不发送 `Content-Length` 时：
- `self.headers.get("Content-Length", 0)` 返回 `0`
- `length = 0`，`if length > _MAX_BODY_SIZE` 为 `False` → 限流完全绕过
- `self.rfile.read(0)` 返回空字节 → body 被替换为 `b"{}"`
- **影响**: 对于 PUT/POST 需要接收 body 的端点，chunked 请求的 body 被静默丢弃，导致非预期行为（如文档更新不生效）。攻击者也可以通过 chunked 编码发送大于 10MB 的请求而不被拒绝。

**建议修复**:
```python
import http.client

# 检查 chunked encoding
is_chunked = self.headers.get("Transfer-Encoding", "").lower() == "chunked"
if is_chunked:
    return self._send(413, {"error": "chunked encoding 不支持"})
```

或更好的方案：使用 `self.rfile` 安全读取：

```python
content_length = self.headers.get("Content-Length")
if content_length is None:
    return self._send(411, {"error": "缺少 Content-Length"})
length = int(content_length) if content_length else 0
if length > _MAX_BODY_SIZE:
    return self._send(413, {"error": "请求体过大（上限 10MB）"})
```

#### (b) **`Content-Length: 0` 的 POST/PUT/DELETE 行为**（低风险）

当显式发送 `Content-Length: 0` 时，`self.headers.get("Content-Length", 0)` 返回 `"0"`，`int("0")` → 0，跳过读取，body 设为 `b"{}"`。这对于需要 JSON body 的端点（如 `POST /documents`）会导致校验失败（title/content 为空），行为正确。✅

#### (c) **Content-Length 非整数或空字符串**（低风险）

`"0"` 是 `self.headers.get` 返回的字符串形式。`int("0")` 能正常转换。但如果 `Content-Length` 包含非数字字符（如 `"abc"`），`int(...)` 会抛出 `ValueError`。

实际上 `http.server.BaseHTTPRequestHandler` 的内部解析已经处理了格式校验，但代码无保护。

**建议**: 包裹 try/except 防止 `Content-Length` 非法值导致 500。

#### (d) **慢速读取攻击 / Slow Read**（低风险）

当 `Content-Length` 为 10MB 且客户端以极慢速度发送数据时，`self.rfile.read(length)` 会阻塞在单个线程上。`ThreadingHTTPServer` 每个请求分配新线程，因此不会阻塞其他请求，但仍可能招致大量慢速请求耗尽线程池。

**建议**: 未来可考虑设置 `rfile` 的读取超时，或在 nginx 反向代理层限制请求体大小（生产部署推荐）。

### 3.3 提交信息不一致

```
commit message: "409 Too Large"
实际代码: 413 Payload Too Large (正确)
```

建议修正提交信息：413 是正确状态码，409 表示 Conflict。

---

## 4. CSP 配置问题

### 4.1 当前配置

```
default-src 'self'
script-src 'self'
style-src 'self' 'unsafe-inline'
img-src 'self' data:
form-action 'none'
frame-ancestors 'none'
```

### 4.2 逐项评估

| 指令 | 评估 | 问题 |
|------|------|------|
| `default-src 'self'` | ✅ 合理的后备基线 | — |
| `script-src 'self'` | ❌ 见 1.1(a) | 阻断所有内联 onclick / `<script>` 块。WebUI `index.html` 和动态渲染的 onclick 均会失效 |
| `style-src 'self' 'unsafe-inline'` | ✅ 允许内联 `style` 属性 | `index.html` 有 `style="display:flex;..."` 等属性，需要 `'unsafe-inline'` |
| `img-src 'self' data:` | ✅ 允许同源图片和 data URI | — |
| `form-action 'none'` | ✅ 防御 XSS 表单劫持 | — |
| `frame-ancestors 'none'` | ✅ 冗余防范点击劫持（与 `X-Frame-Options: DENY` 互补） | — |

### 4.3 缺失的指令

| 指令 | 影响 |
|------|------|
| `base-uri 'self'` | 防止通过 `<base>` 标签劫持相对 URL |
| `object-src 'none'` | 禁掉 `<object>/<embed>/<applet>`（回退到 `default-src 'self'` 允许了这些） |
| `manifest-src 'self'` | 如未来添加 Web Manifest，需要配置 |

### 4.4 建议的 CSP 配置

```
default-src 'self';
script-src 'self';
style-src 'self' 'unsafe-inline';
img-src 'self' data:;
form-action 'none';
frame-ancestors 'none';
base-uri 'self';
object-src 'none'
```

> **注意**: 在 `object-src` 新增 `'none'` 防止对象/插件加载，提供额外安全层。

---

## 5. SSE 端点（`_send_sse`）的安全分析

### 5.1 当前状态

```python
def _send_sse(self, body):
    # ... 鉴权 ...
    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream")
    self.send_header("Cache-Control", "no-cache")
    self.send_header("Connection", "keep-alive")
    self.send_header("Access-Control-Allow-Origin", "*")
    self.send_header("X-Accel-Buffering", "no")
    self.end_headers()
    # ... 发送事件流 ...
```

### 5.2 SS E 是否需要安全响应头？

| 响应头 | 对 SSE 是否有意义 | 建议 |
|--------|-------------------|------|
| `X-Content-Type-Options: nosniff` | 低价值但无害 | 建议添加保持一致性 |
| `X-Frame-Options: DENY` | **无意义** | SSE 响应不在 frame 中渲染，无影响 |
| `Content-Security-Policy` | **无意义** | CSP 是文档级别策略，`text/event-stream` 不会执行脚本，CSP 不适用 |
| `Access-Control-Allow-Origin: *` | **⚠️ 值得关注** | 现在明确指定 `*`，允许任意跨域访问。如果 API Token 已配置，鉴权安全，但元数据暴露面扩大 |

### 5.3 建议

- 为保持代码一致性，可在 `_send_sse` 中加上 `X-Content-Type-Options: nosniff`
- `Access-Control-Allow-Origin: *` 建议与环境变量绑定或与 `do_OPTIONS` 统一管理，避免硬编码

---

## 6. 综合严重性分级

| # | 问题 | 严重性 | 分类 |
|---|------|--------|------|
| 1 | 内联 onclick 被 `script-src 'self'` 阻断 | 🔴 P0 | 功能阻断 |
| 2 | 静态文件 MIME 类型错误 (`octet-stream`)，nosniff 导致 JS/CSS 被拒 | 🔴 P0 | 功能阻断 |
| 3 | `Transfer-Encoding: chunked` 绕过 10MB 体积极限 | 🟡 P2 | 安全绕过 |
| 4 | 缺少 `Strict-Transport-Security` | 🟢 P3 | 安全加固 |
| 5 | 缺少 `Referrer-Policy` | 🟢 P3 | 安全加固 |
| 6 | 缺少 `Permissions-Policy` | 🟢 P3 | 安全加固 |
| 7 | 缺少 `base-uri 'self'` 和 `object-src 'none'` | 🟢 P3 | CSP 修补 |
| 8 | `_send_sse` 硬编码 `Access-Control-Allow-Origin: *` | 🟢 P3 | 配置异议 |
| 9 | 提交信息写 "409 Too Large" 实际用 413 | ⚪ P4 | 文档错误 |
| 10 | 缺少 Content-Length 格式异常保护（try/except） | ⚪ P4 | 健壮性 |

### 优先修复顺序

1. **P0**: 修复静态文件 MIME 类型 + 迁移内联 onclick → addEventListener
2. **P2**: 增加 chunked encoding 检测
3. **P3**: 补充 CSP 指令 + 缺失响应头
4. **P4**: 修正提交信息 + 增加 Content-Length 容错

---

## 7. 总结

该提交引入了重要的安全加固措施（CSP、nosniff、X-Frame-Options、请求体上限），方向正确。但**两个 P0 级别的功能阻断问题**（内联 onclick + 静态文件 MIME 类型 + nosniff 组合）会导致 WebUI 完全不可用。这些问题主要由 `script-src 'self'` + `X-Content-Type-Options: nosniff` 与现有 WebUI 实现的冲突引起。

建议先将静态文件 MIME 识别修复和 onclick 迁移作为前提补丁合并，再合并此安全加固提交。上传体积极限中 `Transfer-Encoding: chunked` 的绕过也需在本次修复中解决。

---

*Reviewer: code-reviewer-15*
