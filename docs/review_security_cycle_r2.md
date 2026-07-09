# 安全加固循环第 2 轮评审报告

- **评审分支**: `m1`
- **评审文件**: `khub/api.py` (HEAD `84c1a3d`)
- **评审日期**: 2026-07-11
- **评审范围**: 安全加固最终签出（sign-off）验证——第 2 轮独立审查
- **前序报告**: `docs/review_security_cycle_r1.md`（Cycle 1，code-reviewer-19，基于 ecd2e34）

---

## 概述

本报告是安全加固的第 2 轮独立评审。Cycle 1（R1）已对 `khub/api.py` 中 6 项检查点逐一验证，判定无功能阻断或安全漏洞残留，标记 3 条 P4 技术债和 6 条非阻塞改进建议。

Cycle 2 在第 1 轮结论基础上，以独立视角重新验证全部安全措施，补充 R1 未覆盖的 edge case 分析，并为最终签出做出判定。

**关键前提**: `api.py` 在 Commit `ecd2e34`（R1 评审基准）与 `84c1a3d`（当前 HEAD）之间**无任何代码变更**——HEAD 仅新增了 R1 报告文档。因此本报告是对**同一份代码**的独立二次审查，而非增量审查。

---

## 1. 安全响应头——独立验证

### 1.1 `_send()` 统一出口

所有非 SSE 响应经由 `Handler._send()`（line 427–450）发放。验证每个安全头的存在性和值。

| # | 响应头 | 行号 | 值 | 判定 |
|---|--------|------|-----|------|
| 1 | `X-Content-Type-Options` | 436 | `nosniff` | ✅ |
| 2 | `X-Frame-Options` | 437 | `DENY` | ✅ |
| 3 | `Referrer-Policy` | 438 | `no-referrer` | ✅ |
| 4 | `Permissions-Policy` | 439–440 | `camera=(), microphone=(), geolocation=(), interest-cohort=()` | ✅ |
| 5 | `Strict-Transport-Security` | 441–442 | `max-age=31536000; includeSubDomains`（无条件发送）| ✅ |
| 6 | `Content-Security-Policy` | 443–448 | 条件发送（仅 `text/html`）| ✅ |

#### 1.1.1 CSP 指令逐项核实（line 443–448）

```python
if ctype == "text/html; charset=utf-8":
    self.send_header("Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; form-action 'none'; "
        "frame-ancestors 'none'; base-uri 'self'; object-src 'none'")
```

| 指令 | 值 | 验证 |
|------|-----|------|
| `default-src` | `'self'` | ✅ 基线限制，未显式指定的 fetch 指令回退至此 |
| `script-src` | `'self' 'unsafe-inline'` | ✅ 必要——WebUI 使用内联 onclick |
| `style-src` | `'self' 'unsafe-inline'` | ✅ 必要——WebUI 使用内联 style 属性 |
| `img-src` | `'self' data:` | ✅ 必要——部分占位图使用 data URI |
| `form-action` | `'none'` | ✅ 防御 XSS 表单劫持 |
| `frame-ancestors` | `'none'` | ✅ 与 `X-Frame-Options: DENY` 双重防御 |
| `base-uri` | `'self'` | ✅ 防止 `<base>` 标签劫持 |
| `object-src` | `'none'` | ✅ 禁用 `<object>`/`<embed>`/`<applet>` 插件 |

**判定**: CSP 指令完备，无遗漏。`'unsafe-inline'` 为功能必需，属可接受折衷。✅

### 1.2 `_send_sse` 安全头缺口（line 471–477）

SSE 端点自行发送响应头，未继承 `_send()` 的安全头：

```python
self.send_response(200)
self.send_header("Content-Type", "text/event-stream")
self.send_header("Cache-Control", "no-cache")
self.send_header("Connection", "keep-alive")
self.send_header("Access-Control-Allow-Origin", "*")
self.send_header("X-Accel-Buffering", "no")
```

与 R1 一致判定：

| 缺失头 | SSE 场景影响 | 判定 |
|--------|-------------|------|
| `X-Content-Type-Options` | SSE MIME 不会被误嗅 | ✅ 可接受 |
| `X-Frame-Options` | SSE 不渲染，无 framing 风险 | ✅ 可接受 |
| `Referrer-Policy` | SSE 不触发导航 | ✅ 可接受 |
| `Permissions-Policy` | SSE 不调用浏览器 API | ✅ 可接受 |
| `Strict-Transport-Security` | 有预防价值（如通过 HTTPS 代理访问 SSE） | ⚠️ 建议补充（R1 遗留建议） |

**本报告补充验证**: `_send_sse` 在进入 SSE 逻辑前**先调用 `_send()` 返回错误**（401/400 时），确保鉴权/校验失败时安全头仍被发送。仅成功路径的 200 SSE 响应缺少安全头。✅ 失败的响应有完整保护。

### 1.3 `do_OPTIONS` 响应头（line 532–540）

```python
def do_OPTIONS(self):
    self.send_response(204)
    self.send_header("Access-Control-Allow-Origin", "*")
    self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
    self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
    self.end_headers()
```

- 204 No Content：无 body，不渲染 ✅
- 安全响应头对 204 不适用（无渲染内容）✅
- CORS 头配置正确：`Allow-Methods` 涵盖所有已实现方法、`Allow-Headers` 覆盖 `Authorization` ✅
- **未设置 `Access-Control-Max-Age`**：浏览器每次跨域请求都发送 preflight，增加延迟但不影响安全 ✅

**判定**: `do_OPTIONS` 的安全处理可接受。✅

---

## 2. 请求体大小限制（10MB）——独立验证

### 2.1 常量与校验点

```python
_MAX_BODY_SIZE = 10 * 1024 * 1024  # line 16 → 10,485,760 字节
```

| HTTP 方法 | 行号 | 校验逻辑 | 判定 |
|-----------|------|---------|------|
| `do_POST` | 509–510 | `length > _MAX_BODY_SIZE` → 413 | ✅ |
| `do_PUT`  | 549–550 | 同上 | ✅ |
| `do_DELETE` | 574–575 | 同上 | ✅ |

### 2.2 边缘场景独立验证（补充 R1）

| 场景 | 预期行为 | 验证 |
|------|---------|------|
| Content-Length = 10MB 整 | 不触发 413，正常处理 | ✅ 边界正确（`>` 非 `>=`） |
| Content-Length = 10MB + 1 | 413 拒绝 | ✅ 超限即拒 |
| Content-Length = 0，body 非空 | `rfile.read(0)` → `b"{}"` | ⚠️ body 丢失但非安全漏洞 |
| 多个 Content-Length 头 | `get()` 返回首个 | ✅ 遵循 RFC 7230 §3.3.2 |
| Content-Length 为负数 | `int("-1")` → -1 → `-1 > _MAX_BODY_SIZE` → False → 通过 | ⚠️ `rfile.read(-1)` 读取全部直至 EOF，潜在风险（见 2.3） |
| Content-Length 极大值 | `int()` 可处理大整数 | ✅ |

### 2.3 ⚠️ 发现：负值 Content-Length 可绕过大小限制（新增）

当 `Content-Length: -1` 时：

- `int("-1")` 成功返回 `-1`
- `-1 > _MAX_BODY_SIZE` → `False` → **不触发 413**
- `self.rfile.read(-1)` → Python 语义：**读取所有可用数据直至 EOF**

这意味着：
1. 攻击者可绕过 10MB 大小限制
2. `rfile.read(-1)` 可能读取远超预期大小的数据（在 `ThreadingHTTPServer` 中无超时）

**实际影响评估**：
- 攻击者需要本地网络访问（服务绑定 127.0.0.1）
- 如有 `KHUB_API_TOKEN`，还须持有有效令牌
- `rfile.read(-1)` 受 TCP 接收缓冲区限制，非无限
- 读取后的 JSON 解析在超大 body 下也可能失败

**严重性**: 低（L3）——本地服务 + 可选鉴权大幅缩小暴露面

**建议修复**: 在 `int()` 后增加正数校验：
```python
length = int(length)
if length < 0:
    length = 0  # 或直接返回 413
```

---

## 3. Transfer-Encoding: chunked 拒绝——独立验证

### 3.1 覆盖

| 方法 | 行号 | 检测位置 | 判定 |
|------|------|---------|------|
| `do_POST` | 502–503 | body 读取前 | ✅ |
| `do_PUT` | 543–544 | body 读取前 | ✅ |
| `do_DELETE` | 568–569 | body 读取前 | ✅ |

```python
if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
    return self._send(411, {"error": "请使用 Content-Length，不接受 Transfer-Encoding: chunked"})
```

### 3.2 检测逻辑验证

| 检查项 | 结果 |
|--------|------|
| `.lower()` 归一化 | ✅ 防止大写/大小写混合绕过 |
| 411 状态码 | ✅ RFC 7231 §6.5.11 语义准确 |
| 位于 `rfile.read()` 之前 | ✅ 不会读取 chunked body |
| 中文错误信息 | ✅ 便于本地排障 |

### 3.3 ⚠️ 发现：多值 Transfer-Encoding 可绕过检测（新增，防御深度）

当前检测使用 `== "chunked"` 精确匹配。HTTP 规范允许 `Transfer-Encoding` 为逗号分隔的多值列表，例如：

```
Transfer-Encoding: gzip, chunked
Transfer-Encoding: chunked, gzip       # RFC 7230 禁止此顺序
```

当值为 `"gzip, chunked"` 时：
- `.lower()` → `"gzip, chunked"`
- `== "chunked"` → **`False` → 绕过**

攻击者可以利用此绕过发送 `Transfer-Encoding: gzip, chunked`，同时带上有效的 `Content-Length`。Python `http.server` **不处理** chunked 传输编码，因此 `rfile.read(length)` 从原始 socket 读取 Content-Length 指定的字节数。如果 Content-Length 恰好等于未分块的数据部分大小，JSON 解析可能成功。

**实际影响评估**：
- 需要本地网络访问（127.0.0.1）
- 可选鉴权提供额外保护
- 绕过仅影响对 "chunked" 的拒绝，不影响 body 大小限制（仍受 `_MAX_BODY_SIZE` 约束）
- 实际 chunked 编码数据（含 chunk size 行）仍会导致 JSON 解析失败 → 400

**严重性**: 低（L3）——防御深度加强点

**建议修复**: 将 `== "chunked"` 改为 `in` 检测：
```python
if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
```

---

## 4. Content-Length 解析安全——独立验证

### 4.1 try/except 覆盖

| 方法 | 实现 | 覆盖异常 | 降级行为 | 判定 |
|------|------|---------|----------|------|
| `do_POST` (line 504–508) | `get()` → `int()` | `TypeError, ValueError` | `length = 0` | ✅ |
| `do_PUT` (line 545–548) | `int(get() or "0")` | `TypeError, ValueError` | `length = 0` | ✅ |
| `do_DELETE` (line 570–573) | `int(get() or "0")` | `TypeError, ValueError` | `length = 0` | ✅ |

### 4.2 风格差异（已知 P4，确认）

- `do_POST`: 两步模式（`get()` → 变量 → `int()`）
- `do_PUT`/`do_DELETE`: 一步模式（`int(get() or "0")`）

功能等价。纯代码一致性议题。✅ 无安全影响。

---

## 5. 静态文件 MIME 类型映射——独立验证

### 5.1 映射表（line 19–29）

```python
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

### 5.2 使用点（line 70）

```python
ctype = _MIME.get(os.path.splitext(filename)[1].lower(), "application/octet-stream")
```

| 检查项 | 结果 |
|--------|------|
| `.lower()` 扩展名归一化 | ✅ 防止 `.JS`/`.JPG` 绕过 |
| 未知扩展名回退 `application/octet-stream` | ✅ + `X-Content-Type-Options: nosniff` 防止 MIME 嗅探 |
| 文本类型含 `charset=utf-8` | ✅ HTML/CSS/JS |
| 二进制类型无 `charset` | ✅ PNG/JPEG/SVG/ICO/JSON |
| 路径穿越双校验 | ✅ `os.path.realpath`（line 63–65）未退化 |
| 映射覆盖当前 WebUI 需求 | ✅ 仅使用 `.html`/`.css`/`.js` |

### 5.3 映射完备性

与 R1 判断一致：当前覆盖够用，未来扩展新文件类型需同步。✅

---

## 6. `_send_sse` 鉴权与协议合规——独立验证

### 6.1 鉴权一致性

```python
# line 454–456 — _send_sse 入口
token = os.environ.get("KHUB_API_TOKEN")
if token and self.headers.get("Authorization", "") != f"Bearer {token}":
    return self._send(401, {"error": "unauthorized"})
```

与 `dispatch()` 入口（line 52–54）鉴权逻辑**完全一致**。✅

### 6.2 SSE 协议合规

| 要求 | 实现 | 判定 |
|------|------|------|
| `Content-Type: text/event-stream` | line 472 | ✅ |
| `Cache-Control: no-cache` | line 473 | ✅ |
| `Connection: keep-alive` | line 474 | ✅ |
| `Access-Control-Allow-Origin: *` | line 475 | ✅ （鉴权兜底）|
| `X-Accel-Buffering: no` | line 476 | ✅ nginx 兼容 |
| 事件格式 | line 483 `event: {ev}\ndata: {data}\n\n` | ✅ |
| 客户端断开 | line 486–487 `BrokenPipeError`/`ConnectionResetError` | ✅ |

### 6.3 客户端断开会话清理

`engine.ask_stream()` 生成器在异常传播后由 GC 回收。无文件描述符/连接/事务泄漏风险。✅

---

## 7. 回归风险扫描——独立验证

### 7.1 已有防御未退化

| 防御措施 | 位置 | 状态 |
|---------|------|------|
| 静态文件路径穿越 | `dispatch()` line 63–65 | ✅ 未被修改 |
| API 鉴权（可选 Bearer Token） | `dispatch()` line 52–54 | ✅ 未被修改 |
| HTML 内容 XSS 剥离 | `dispatch()` line 205–212 | ✅ 未被修改 |
| `_safe_int()` 安全类型转换 | line 32–37 | ✅ 未被修改 |
| CORS preflight (`do_OPTIONS`) | line 532–540 | ✅ 未被修改 |

### 7.2 功能路径影响

与 R1 判定一致：所有需要 body 校验的端点（POST/PUT/DELETE）新增了 10MB 上限 + chunked 拒绝 + Content-Length 校验；GET 端点不受影响。✅

### 7.3 并发安全

`ThreadingHTTPServer` 每请求独立线程，Handler 实例请求级绑定，`_send()` 无共享状态。✅

---

## 8. 新增发现汇总

### 8.1 本报告新增（Cycle 2 首次发现）

| # | 问题 | 类型 | 严重性 | 描述 |
|---|------|------|--------|------|
| C2-1 | **负值 Content-Length 可绕过 10MB 上限** | 安全防御 | L3 | `int("-1")` → -1 → 413 检查通过 → `rfile.read(-1)` 读取全部数据 |
| C2-2 | **多值 Transfer-Encoding 绕过 chunked 检测** | 防御深度 | L3 | `Transfer-Encoding: gzip, chunked` 中 `== "chunked"` 不匹配，绕过拒绝逻辑 |

### 8.2 R1 确认残留（无变化）

| # | 问题 | 类型 | 严重性 | 首次发现 |
|---|------|------|--------|---------|
| 1 | `do_POST`/`do_PUT`/`do_DELETE` body 读取代码三重重复 | 可维护性 | P4 | R1 |
| 2 | Content-Length 解析风格不一致（两步 vs 一行） | 一致性 | P4 | R1 |
| 3 | `_send_sse` 缺少 `Strict-Transport-Security` 头 | 防御深度 | 建议 | R1 |

---

## 9. 最终判定

### ✅ 签出就绪（条件通过）

1. **安全响应头**: 全部 6 项在 `_send()` 中正确发放，值合规，覆盖范围合理。`_send_sse` 成功路径缺口可接受。`do_OPTIONS` 204 响应不需要安全头。✅
2. **请求体大小限制**: `do_POST`/`do_PUT`/`do_DELETE` 中 10MB 上限正确实施。⚠️ **建议修复 C2-1**（负值 Content-Length 绕过）后完全就绪。
3. **Transfer-Encoding: chunked 拒绝**: 三处均在 body 读取前检测。⚠️ **建议修复 C2-2**（多值 TE 绕过）后完全就绪。
4. **Content-Length 解析安全**: try/except 全覆盖，非法值不抛 500。✅
5. **静态文件 MIME 映射**: 9 种扩展名正确映射，`.lower()` 防大小写绕过。✅
6. **SSE 鉴权**: 与 `dispatch()` 鉴权逻辑一致，安全时序正确。✅

### ⚠️ 建议合并前修复

| 优先级 | 问题 | 修复难度 | 建议修复 |
|--------|------|---------|---------|
| 低 | C2-1: 负值 Content-Length 绕过 | 1 行 | 三个方法中 `int()` 后增加 `if length < 0: length = 0` |
| 低 | C2-2: 多值 TE 绕过 chunked 检测 | 1 行 | 三处 `== "chunked"` 替换为 `"chunked" in ...` |

两项修复均为单行修改，影响范围完全限定在 body 读取路径，无回归风险。

### 📋 非阻塞改进（继续保留至下个迭代）

- 提取 `_read_body()` 统一 body 读取（消除三重重复 + 风格统一）
- 为 `_send_sse` 补充 HSTS 头（防御深度）
- 设置 `rfile` 读取超时（nginx 反代可替代）

---

*评审人: code-reviewer-20（独立第 2 轮）*
*日期: 2026-07-11*
*基准: HEAD 84c1a3d (origin/m1)*
*代码状态: 与 R1 基准 ecd2e34 一致，无变更*
