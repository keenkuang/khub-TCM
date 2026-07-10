# 安全加固代码评审报告（R3）

- **评审范围**: Commits `63e6a37`（R2 修复）+ `a045072`（新增安全头）
- **评审文件**: `khub/api.py`
- **基线提交**: `a045072`（HEAD, m1）
- **评审日期**: 2026-07-10

---

## 1. R1 修复逐项验证

### 1.1 🔴 P0 — CSP `script-src 'self'` → `script-src 'self' 'unsafe-inline'`

**状态: ✅ 正确修复**（commit `ff0a842`）

```python
# api.py:446
"default-src 'self'; script-src 'self' 'unsafe-inline'; "
```

CSP 仅在 `ctype == "text/html; charset=utf-8"` 时发送（line 444），符合规范。

### 1.2 🔴 P0 — 静态文件 MIME 类型

**状态: ✅ 正确修复**（commit `ff0a842`）

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

- `.lower()` 归一化扩展名，防止大小写绕过 ✅
- 未知扩展名回退 `application/octet-stream` + `X-Content-Type-Options: nosniff` ✅

### 1.3 🟢 P3 — CSP `base-uri 'self'; object-src 'none'`

**状态: ✅ 正确修复**（commit `ff0a842`）

```python
# api.py:449
"frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
```

---

## 2. R2 Fix 逐项验证（commit `63e6a37`）

### 2.1 Content-Length try/except — `do_POST`

**状态: ✅ 正确修复**

```python
# api.py:503-507
length = self.headers.get("Content-Length", "0")
try:
    length = int(length)
except (TypeError, ValueError):
    length = 0
```

- 非数字 Content-Length 被捕获为 `length = 0`，不抛 500 ✅
- `int("")` 触发 `ValueError`，正确降级 ✅
- 注意：降级为 0 后 body 被替换为 `b"{}"`，请求体静默丢失 —— 这是可接受的行为（同原逻辑）。

### 2.2 Content-Length try/except — `do_PUT`

**状态: ✅ 正确修复**

```python
# api.py:542-545
try:
    length = int(self.headers.get("Content-Length", "0") or "0")
except (TypeError, ValueError):
    length = 0
```

- 非数字 Content-Length 被捕获 ✅
- `or "0"` 防御空字符串（`get` 返回 `""` 时降级为 `"0"`）✅

### 2.3 Content-Length try/except — `do_DELETE`

**状态: ✅ 正确修复**

```python
# api.py:565-568
try:
    length = int(self.headers.get("Content-Length", "0") or "0")
except (TypeError, ValueError):
    length = 0
```

与 `do_PUT` 完全一致 ✅

---

## 3. R2 未修复问题状态

以下为 R2 中标记未修复且至今未改的问题。

### 3.1 🔴 P2 — `Transfer-Encoding: chunked` 绕过体积极限

**状态: ❌ 仍未修复**

三处（do_POST line 503, do_PUT line 542, do_DELETE line 565）均未检测 `Transfer-Encoding: chunked`：

```python
# 无一处在读取 body 前检查 Transfer-Encoding
```

当客户端发送 `Transfer-Encoding: chunked` 且不携带 `Content-Length` 时：
- `Content-Length` 默认为 `"0"` → `length = 0`
- `length > _MAX_BODY_SIZE` → `False` → **绕过 10MB 上限**
- `self.rfile.read(0)` → body 被替换为 `b"{}"`

**建议修复**（三处同步增加）：

```python
te = self.headers.get("Transfer-Encoding", "").lower()
if te == "chunked":
    return self._send(413, {"error": "chunked encoding 不支持"})
```

### 3.2 ⚪ P4 — 请求体校验代码三重重复

**状态: ❌ 仍未修复**

`do_POST` / `do_PUT` / `do_DELETE` 三处仍然各自独立实现请求体读取逻辑：

- Content-Length 解析（try/except 方式略有不同——见第 6 节）
- 体积极限校验
- rfile.read + json.loads

**建议修复**: 提取为 `Handler` 的静态方法。

### 3.3 🟢 P3 — `_send_sse` 硬编码 `Access-Control-Allow-Origin: *`

**状态: ❌ 未修改**（可接受）

`_send_sse`（line 476）仍然直接写 `Access-Control-Allow-Origin: *`。影响轻微，因为 SSE 端点的鉴权已经在 `_send_sse` 入口处独立处理。

---

## 4. 新增安全头验证（commit `a045072`）

### 4.1 Referrer-Policy

**状态: ✅ 配置正确**

```python
# api.py:438
self.send_header("Referrer-Policy", "no-referrer")
```

- 值 `no-referrer` 是合法且最严格的选项 ✅
- R2 建议值为 `strict-origin-when-cross-origin`（更宽松），当前选择更为保守 ✅
- 该头的放置位置正确——在 `_send` 方法中，所有响应均发送 ✅

### 4.2 Permissions-Policy

**状态: ✅ 配置正确**

```python
# api.py:439-440
self.send_header("Permissions-Policy",
    "camera=(), microphone=(), geolocation=(), interest-cohort=()")
```

- 禁用了高风险的摄像头/麦克风/地理位置权限 ✅
- 额外禁用了 `interest-cohort=()`（Google FLoC 广告追踪）✅
- 目标 URL 为本地 API，无需任何上述权限 ✅

### 4.3 Strict-Transport-Security（HSTS）

**状态: ⚠️ 配置存在条件缺陷**

```python
# api.py:441-443
if code == 200:
    self.send_header("Strict-Transport-Security",
        "max-age=31536000; includeSubDomains")
```

**问题**: `code == 200` 条件过于严格。

根据 RFC 6797 §7.2，HSTS 头"must be included in all responses over secure transport"——包括 301/302 重定向、4xx 错误、5xx 错误等。仅对 200 发送 HSTS 意味着：

| 场景 | 是否带 HSTS | 影响 |
|------|------------|------|
| GET / 返回 200 → 显示 WebUI | ✅ | 正常 |
| 301 重定向（如未来加的路由） | ❌ | 浏览器不会为该域名注册 HSTS，下次访问仍从 HTTP 开始 |
| 404 错误 | ❌ | 浏览器不会为该域名注册 HSTS |
| 413 请求体过大 | ❌ | 同上 |

**减轻因素**:
- 当前服务仅运行在 HTTP（`127.0.0.1`），HSTS 在纯 HTTP 上无实际效果（浏览器忽略）
- 头已存在，改条件即可——`if code == 200:` → 移除条件或改为 `if code >= 200:`（排除 1xx）

**建议修复**：

```python
# Remove the code filter entirely — HSTS should be sent on all responses
self.send_header("Strict-Transport-Security",
    "max-age=31536000; includeSubDomains")
```

---

## 5. R3 新增发现

### 5.1 ⚪ P4 — do_POST 与 do_PUT/do_DELETE 的 Content-Length 解析风格不一致

**位置**: do_POST（line 503-507）vs do_PUT（line 542-545）/ do_DELETE（line 565-568）

| 方法 | 实现模式 |
|------|---------|
| `do_POST` | 两步骤：先 `get()` 再 `int()` |
| `do_PUT` | 一行内 try: `int(get() or "0")` |
| `do_DELETE` | 同 `do_PUT` |

功能等价，但风格不一致。提取为 `_read_body` 静态方法即可统一解决（同时解决第 3.2 节的三重重复问题）。

### 5.2 ✅ `_send_sse` 不经过 `_send`，缺少安全头

**状态: ✅ 已知且可接受**（R2 已记录）

`_send_sse`（line 453-488）自行发送响应头，未包含：
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`
- `Permissions-Policy`
- `Strict-Transport-Security`

SSE 响应类型为 `text/event-stream`，浏览器不将其作为文档渲染，因此 CSP/X-Frame-Options 不适用。HSTS 和相关策略头的缺失属于可接受的防御深度缺口。

**未来增强建议**（可选）：

```python
# 在 _send_sse 的 send_response 之后增加
self.send_header("X-Content-Type-Options", "nosniff")
self.send_header("Referrer-Policy", "no-referrer")
self.send_header("Strict-Transport-Security",
    "max-age=31536000; includeSubDomains")
```

### 5.3 ✅ 路径穿越防御仍稳固

`dispatch()` 中静态文件服务（line 62-66）的 `os.path.realpath` 双校验未被上述任何提交修改，防御未退化。✅

---

## 6. 最终严重性分级

| # | 问题 | 严重性 | 分类 | R2 状态 | R3 状态 |
|---|------|--------|------|---------|---------|
| 1 | 内联 onclick 被 `script-src 'self'` 阻断 | 🔴 P0 | 功能阻断 | ✅ 已修复 | ✅ 验证通过 |
| 2 | 静态文件 MIME 类型错误 → JS/CSS 被拒 | 🔴 P0 | 功能阻断 | ✅ 已修复 | ✅ 验证通过 |
| 3 | 缺少 `base-uri 'self'` / `object-src 'none'` | 🟢 P3 | CSP 修补 | ✅ 已修复 | ✅ 验证通过 |
| 4 | `Transfer-Encoding: chunked` 绕过 10MB | 🔴 P2 | 安全绕过 | ❌ 未修复 | ❌ **仍未修复** |
| 5 | Content-Length 格式异常 → 500 崩溃 | ⚪ P4 | 健壮性 | ✅ 已修复 | ✅ 验证通过 |
| 6 | 请求体校验代码三重重复 | ⚪ P4 | 可维护性 | ❌ 未修复 | ❌ **仍未修复** |
| 7 | 缺少 `Strict-Transport-Security` | 🟢 P3 | 安全加固 | ❌ 缺失 | ✅ **已添加**（但有条件缺陷 ↓） |
| 8 | HSTS 仅对 `code == 200` 生效（应全响应发送）| 🟢 P3 | 配置错误 | —（新发现）| ⚠️ **新增** |
| 9 | 缺少 `Referrer-Policy` | 🟢 P3 | 安全加固 | ❌ 缺失 | ✅ **已添加** |
| 10 | 缺少 `Permissions-Policy` | 🟢 P3 | 安全加固 | ❌ 缺失 | ✅ **已添加** |
| 11 | `_send_sse` 硬编码 `Access-Control-Allow-Origin: *` | 🟢 P3 | 配置异议 | ❌ 未改 | ❌ 未改（可接受）|
| 12 | do_POST/do_PUT/do_DELETE Content-Length 解析风格不一致 | ⚪ P4 | 一致性 | —（新发现）| ⚪ **新增** |

---

## 7. 结论与建议

### 本轮亮点

- **R1 三个问题全部修复验证通过** ✅
- **R2 关键修复（Content-Length 容错）验证通过** ✅
- **新增三个安全头全部就位**：Referrer-Policy、Permissions-Policy、HSTS ✅

### 仍需修复的问题（按优先级）

1. **🔴 P2 — `Transfer-Encoding: chunked` 绕过体积极限**（R2 遗留）
   - 三处各加 2-3 行 chunked 检测即可，修复成本极低
   - 这是当前唯一真正的安全漏洞

2. **🟢 P3 — HSTS `code == 200` 条件缺陷**（本轮新发现）
   - 移除 `if code == 200:` 条件，让 HSTS 在所有响应中发送
   - 整改成本：删除 1 行缩进

3. **⚪ P4 — 请求体校验代码三重重复 + 解析风格不一致**（R2 遗留）
   - 提取 `_read_body` 静态方法统一处理
   - 一石三鸟：解决重复、风格不一致、未来 bug 风险

### 部署意见

**当前 HEAD 可以合并**。两个需要关注的问题：
- P2 chunked 绕过是真实安全漏洞，但攻击面有限（仅本地网络）
- HSTS 条件缺陷在纯 HTTP 场景下无实际影响

建议在下一迭代中优先修复 P2 和 P3（HSTS 条件），P4 可排入技术债清理。

---

*Reviewer: code-reviewer-17*
