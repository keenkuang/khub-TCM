# 安全加固循环第 1 轮评审报告

- **评审分支**: `m1`
- **评审文件**: `khub/api.py` (HEAD `ecd2e34`)
- **评审日期**: 2026-07-11
- **评审范围**: 完整安全加固实施的全量最终审查

---

## 概述

本报告对 `khub/api.py` 中所有安全加固措施进行最终全量审查。此前已历经三轮迭代评审（R1–R3，存档于 `docs/review_security_r{1,2,3}.md`）及一轮最终验证（`docs/review_security_final.md`），累计发现 12 个问题，其中 11 个已修复并验证通过。当前报告对 **6 项检查点** 逐一独立验证，并聚焦边缘场景、回归风险、防御深度和可观测性。

---

## 1. 安全响应头

### 1.1 头发放位置

所有安全响应头通过 `Handler._send()` 方法统一发放（line 427–449），该方法是所有非 SSE 响应的唯一出口。SSE 端点 `_send_sse` 自行发放响应头。

### 1.2 逐头验证

#### X-Content-Type-Options
```python
# line 436
self.send_header("X-Content-Type-Options", "nosniff")
```
- **值**: `nosniff` ✅ 合法且正确
- **覆盖**: 所有通过 `_send()` 的响应 ✅
- **效果**: 与 `_MIME` 映射配合，防止浏览器 MIME 嗅探攻击 ✅
- **缺失场景**: `_send_sse` 未携带此头（见第 6 节分析）

#### X-Frame-Options
```python
# line 437
self.send_header("X-Frame-Options", "DENY")
```
- **值**: `DENY` ✅ 最严格选项
- **覆盖**: 所有响应 ✅
- **与 CSP 冗余**: `frame-ancestors 'none'` 提供同级别保护，双保险 ✅

#### Referrer-Policy
```python
# line 438
self.send_header("Referrer-Policy", "no-referrer")
```
- **值**: `no-referrer` ✅ 最严格选项（R1 建议 `strict-origin-when-cross-origin`，最终采用更保守的 `no-referrer`，合理）
- **覆盖**: 所有响应 ✅
- **效果**: 完全禁止 `Referer` 头泄露内部 URL 路径，适合场景（纯本地 API 暴露 PII）

#### Permissions-Policy
```python
# line 439–440
self.send_header("Permissions-Policy",
    "camera=(), microphone=(), geolocation=(), interest-cohort=()")
```
- **语法正确性**: `feature=()` 是 Permissions-Policy 标准语法 ✅
- **禁用范围**: 摄像头、麦克风、地理位置（高权限 API）、FLoC 广告追踪（`interest-cohort`）
- **完备性**: API 服务不依赖任何浏览器权限，当前禁用集合合理 ✅
- **潜在补充**: 可额外禁用 `payment=(), autoplay=(), fullscreen=(), display-capture=()` 进一步收窄攻击面（非阻塞建议）

#### Strict-Transport-Security (HSTS)
```python
# line 441–442
self.send_header("Strict-Transport-Security",
    "max-age=31536000; includeSubDomains")
```
- **无条件发送**: ✅ R3 发现的 `if code == 200:` 条件缺陷已在 commit `f9f4324` 修复，现对所有响应无条件发送
- **max-age**: 31536000 秒（1 年），合理 ✅
- **includeSubDomains**: 适用于同域名下所有子域 ✅
- **实际影响**: 当前服务仅运行在 HTTP (127.0.0.1)，浏览器不会处理 HTTP 上的 HSTS 头，属于预防性加固

#### Content-Security-Policy
```python
# line 443–448 (conditional on text/html)
if ctype == "text/html; charset=utf-8":
    self.send_header("Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; form-action 'none'; "
        "frame-ancestors 'none'; base-uri 'self'; object-src 'none'")
```
- **条件范围正确**: CSP 仅在 `text/html` 响应中发送（line 443），符合 CSP 规范（仅文档级需要）
- **指令完备性**:

| 指令 | 值 | 评估 | 说明 |
|------|-----|------|------|
| `default-src` | `'self'` | ✅ 合理基线 | 未明确指定的 fetch 指令回退至此 |
| `script-src` | `'self' 'unsafe-inline'` | ✅ 功能正确 | R1 发现 `'unsafe-inline'` 缺失导致 onclick 全阻，已修复 |
| `style-src` | `'self' 'unsafe-inline'` | ✅ 必要 | WebUI 使用内联 `style` 属性 |
| `img-src` | `'self' data:` | ✅ 必要 | 部分图标/占位图使用 data URI |
| `form-action` | `'none'` | ✅ 防御 XSS 表单劫持 | WebUI 无表单动作，无影响 |
| `frame-ancestors` | `'none'` | ✅ 与 X-Frame-Options 互补 | 双重防御点击劫持 |
| `base-uri` | `'self'` | ✅ 防止 `<base>` 劫持 | R1 建议补充，已添加 |
| `object-src` | `'none'` | ✅ 禁用插件 | R1 建议补充，已添加 |

- **缺失但低优先级**: `connect-src 'self'`（当前未显式限制 fetch/XHR 目标，回退到 `default-src 'self'` 已够用）

### 1.3 `_send_sse` 安全头缺口

`_send_sse`（line 452–487）自行发送响应头，未包含任何安全头：

```python
# line 471–477
self.send_response(200)
self.send_header("Content-Type", "text/event-stream")
self.send_header("Cache-Control", "no-cache")
self.send_header("Connection", "keep-alive")
self.send_header("Access-Control-Allow-Origin", "*")
self.send_header("X-Accel-Buffering", "no")
```

| 缺失头 | SSE 场景影响 | 修复建议 |
|---------|-------------|---------|
| `X-Content-Type-Options: nosniff` | 低——SSE 的 MIME 类型不会被误嗅 | 可选择性添加保持一致 |
| `Strict-Transport-Security` | 有预防价值——如通过 HTTPS 代理访问 SSE | **建议添加**（防御深度） |
| `Referrer-Policy` | 无实际影响——SSE 响应不触发新导航 | 可忽略 |
| `Permissions-Policy` | 无实际影响——SSE 不调用浏览器 API | 可忽略 |

**判定**: `Strict-Transport-Security` 建议补齐；其余头在 SSE 场景下为可接受的缺口。

---

## 2. 请求体大小限制（10MB）

### 2.1 常量定义
```python
# line 16
_MAX_BODY_SIZE = 10 * 1024 * 1024
```
✅ 值 = 10,485,760 字节，约 10MB。

### 2.2 校验覆盖

| 方法 | 校验位置 | 效果 |
|------|---------|------|
| `do_POST` | line 509–510 | `length > _MAX_BODY_SIZE` → 413 |
| `do_PUT` | line 549–550 | 同上 |
| `do_DELETE` | line 574–575 | 同上 |

### 2.3 边缘场景分析

| 场景 | 行为 | 判定 |
|------|------|------|
| Content-Length = 10MB | length == _MAX_BODY_SIZE → 正常处理 | ✅ 边界未误伤 |
| Content-Length = 10MB + 1 | length > _MAX_BODY_SIZE → 413 拒绝 | ✅ 超限即拒 |
| Content-Length = 0 且 body 非空 | length=0 → `rfile.read(0)` → `b"{}"` → body 丢失 | ⚠️ 静默丢失，但非安全漏洞 |
| Content-Length = 0 的 POST/PUT | body 空 ↔ dispatch 中 title/content 校验失败 → 400 | ✅ 行为正确 |
| 恶意超长 Content-Length (> INT_MAX) | Python 可处理大整数，`int()` 不溢出 | ✅ |
| 多个 Content-Length 头 | `get()` 返回第一个值，遵循 RFC 7230 §3.3.2 要求 | ✅ |

### 2.4 不足

1. **无读取超时**: `self.rfile.read(length)` 在慢速网络下可能长时间阻塞。`ThreadingHTTPServer` 每请求独立线程，但大量慢速请求可耗尽线程池。
2. **无 body 内容校验上限**: 当前仅校验长度，不校验 body 内容类型（JSON 结构深度等）。
3. **代码三重重复**: `do_POST`/`do_PUT`/`do_DELETE` 的 body 读取逻辑完全一致，未来修改需同步三处（已知 P4 残留）。

---

## 3. Transfer-Encoding: chunked 拒绝

### 3.1 实现

三个 HTTP 方法均已增加 chunked 检测：

```python
# do_POST line 502–503, do_PUT line 543–544, do_DELETE line 568–569
if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
    return self._send(411, {"error": "请使用 Content-Length，不接受 Transfer-Encoding: chunked"})
```

### 3.2 验证

| 检查项 | 结果 |
|--------|------|
| `do_POST` 中 chunked 检测位于 body 读取前 | ✅ |
| `do_PUT` 中 chunked 检测位于 body 读取前 | ✅ |
| `do_DELETE` 中 chunked 检测位于 body 读取前 | ✅ |
| 返回状态码 411 Length Required | ✅ 语义准确（RFC 7231 §6.5.11） |
| `.lower()` 归一化 | ✅ 防止 `TE`/`Te`/`chunked` 大小写变体绕过 |
| 中文错误信息 | ✅ 便于国内排障 |

### 3.3 残留风险

- **`Transfer-Encoding: chunked` + `Content-Length` 同时存在**: HTTP 规范（RFC 7230 §3.3.3）规定此时应忽略 `Content-Length`，但当前代码仅检测 `Transfer-Encoding` 值，若两者同时发送，会在 chunked 检测通过前先被 body 读取逻辑处理。不过由于 chunked 检测在前，检测到即返回 411，不会进入 body 读取路径。**安全** ✅。

### 3.4 历史状态

R1 将该问题标记为 **P2**（安全绕过），R2/R3 持续追踪为未修复，commit `f9f4324` **最终修复**。✅

---

## 4. Content-Length 解析安全

### 4.1 try/except 覆盖

| 方法 | 实现 | 覆盖异常 | 降级行为 |
|------|------|---------|----------|
| `do_POST` (line 504–508) | 先 `get()` 再 `int()` | `TypeError, ValueError` | `length = 0` |
| `do_PUT` (line 545–548) | `int(get() or "0")` | `TypeError, ValueError` | `length = 0` |
| `do_DELETE` (line 570–573) | `int(get() or "0")` | `TypeError, ValueError` | `length = 0` |

### 4.2 边界场景

| 输入 | `int()` 结果 | 行为 |
|------|-------------|------|
| `"1024"` | 1024 | ✅ 正常 |
| `"0"` | 0 | ✅ 正常 |
| `""` | 空字符串 → `ValueError` → 降级为 0 | ⚠️ 降级行为（body 替换为 `b"{}"`） |
| `"abc"` | `ValueError` → 降级为 0 | ✅ 不抛 500 |
| 缺失头 | `get(_, "0")` 返回 `"0"` → 0 | ✅ |
| `" 1024 "` | `ValueError`（int 不允许前导空格）→ 降级为 0 | ⚠️ `" 1024 "` 是格式违规，降级合理 |
| `"1.5"` | `ValueError`（int 不接收浮点）→ 降级为 0 | ✅ 协议违规 |
| `"9999999999999"` | 大整数正常解析 | ✅ |

### 4.3 风格不一致（已知 P4）

`do_POST` 使用两步模式，`do_PUT`/`do_DELETE` 使用 `or "0"` 一行模式。功能等价，但：

- `do_POST`: `length = self.headers.get("Content-Length", "0")` 后接 `int(length)` — `get` 默认值已是 `"0"`，`or "0"` 不需要
- `do_PUT`/`do_DELETE`: `int(self.headers.get("Content-Length", "0") or "0")` — 额外的 `or "0"` 防御 `get` 返回空字符串 `""`

**实际效果**: `"0" or "0"` 仍为 `"0"`，无功能差异。建议统一风格（非阻塞）。

---

## 5. 静态文件 MIME 类型映射

### 5.1 映射表
```python
# line 19–29
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

### 5.2 使用点
```python
# line 70
ctype = _MIME.get(os.path.splitext(filename)[1].lower(), "application/octet-stream")
```

### 5.3 验证

| 检查项 | 结果 |
|--------|------|
| `.lower()` 扩展名归一化 | ✅ 防止 `.JS`/`.JPG` 等大小写绕过 |
| 未知扩展名回退 `application/octet-stream` | ✅ + `X-Content-Type-Options: nosniff` 使浏览器拒绝执行 |
| `charset=utf-8` 在文本类型上正确设置 | ✅ HTML/CSS/JS 均带字符集声明 |
| 二进制类型无字符集声明 | ✅ PNG/JPEG/SVG/ICO/JSON 无 `charset` |
| 路径穿越防御未退化 | ✅ `os.path.realpath` 双校验仍在（line 63–65）|

### 5.4 映射完备性

当前 WebUI 只引用 `index.html`、`style.css`、`script.js` 三种文件，映射表恰好覆盖。未来扩展以下文件类型时需要同步更新 `_MIME`：

| 文件类 | 扩展名 | 建议 Content-Type |
|--------|--------|-------------------|
| Web 字体 | `.woff` / `.woff2` | `font/woff2` |
| Web 字体 | `.ttf` | `font/ttf` |
| 矢量图 | `.webp` | `image/webp` |
| 源码映射 | `.map` | `application/json` |
| 字体图标 | `.eot` | `application/vnd.ms-fontobject` |
| 文档 | `.pdf` | `application/pdf` |

---

## 6. `_send_sse` CORS 与鉴权处理

### 6.1 鉴权
```python
# line 454–456
token = os.environ.get("KHUB_API_TOKEN")
if token and self.headers.get("Authorization", "") != f"Bearer {token}":
    return self._send(401, {"error": "unauthorized"})
```
- 鉴权逻辑与 `dispatch()` 入口处（line 52–54）**完全一致** ✅
- 401 返回使用 `_send()`，含所有安全响应头 ✅
- 在读取/解析 body 之前鉴权，安全时序正确 ✅

### 6.2 CORS
```python
# line 475
self.send_header("Access-Control-Allow-Origin", "*")
```
- 硬编码 `*`，与 `do_OPTIONS`（line 535）一致 ✅
- 由于 SSE 端点有独立鉴权保护，`*` 的暴露面有限 ✅
- **建议**: 将 CORS 来源与 `KHUB_API_TOKEN` 联动 —— 有 token 时 `*` 安全（鉴权兜底），无 token 时限制更严格（非阻塞）

### 6.3 SSE 协议合规

| 要求 | 实现 | 判定 |
|------|------|------|
| `Content-Type: text/event-stream` | line 473 | ✅ |
| `Cache-Control: no-cache` | line 474 | ✅ |
| `Connection: keep-alive` | line 475 | ✅ 标准实践 |
| `X-Accel-Buffering: no` | line 477 | ✅ nginx 代理兼容 |
| 事件格式 `event: +\ndata: +\n\n` | line 483 | ✅ |
| 客户端断开处理 | line 486–487: `BrokenPipeError`/`ConnectionResetError` 静默捕获 | ✅ |

### 6.4 客户端断开处理分析

```python
# line 486–487
except (BrokenPipeError, ConnectionResetError):
    pass  # 客户端断开，静默结束
```

断开会话的资源清理：
- 生成器 `engine.ask_stream()` 会在异常传播时被 GC 回收 ✅
- 无文件描述符/网络连接泄漏风险 ✅
- 无数据库事务悬空风险（`ask_stream` 为纯检索）✅

---

## 7. 回归风险扫描

### 7.1 已有防御未退化

| 防御措施 | 位置 | 状态 |
|---------|------|------|
| 静态文件路径穿越 | `dispatch()` line 63–65 | ✅ 未被修改 |
| API 鉴权（可选 Bearer Token） | `dispatch()` line 52–54 | ✅ 未被修改 |
| HTML 内容 XSS 剥离 | `dispatch()` line 205–212 | ✅ 未被修改 |
| `_safe_int()` 安全类型转换 | line 32–37 | ✅ 未被修改 |
| CORS preflight (`do_OPTIONS`) | line 532–540 | ✅ 未被修改 |

### 7.2 功能路径影响

| 端点 | 是否受影响 | 说明 |
|------|-----------|------|
| `GET /health` | 无 | 不经过安全头/body 校验逻辑 |
| `GET /stats` | 无 | 同上 |
| `GET /search` | 无 | 同上 |
| `GET /documents` | 无 | 同上 |
| `GET /documents/{id}` | 无 | 同上 |
| `POST /documents` | ✅ 受 body 校验影响 | 新增 10MB + chunked + Content-Length 校验 |
| `PUT /documents/{id}` | ✅ 同上 | 同上 |
| `POST /ask` | ✅ 受 body 校验影响 | 同上 |
| SSE (`stream=true`) | ✅ 受鉴权影响 | 鉴权逻辑与 dispatch 一致 |
| 静态文件 `/web/*` | ✅ 受 MIME + CSP 影响 | MIME 类型从固定 `octet-stream` 改为扩展名映射 |
| 根路径 `GET /` | ✅ 受 CSP 影响 | CSP 仅在 HTML 响应中发送，正确 |

### 7.3 并发安全

`ThreadingHTTPServer` 为每请求分配新线程，Handler 实例与请求生命周期绑定。`_send()` 中安全响应头在每次请求时重新设置，无共享状态竞争 ✅。

---

## 8. 已知残留问题汇总

### 8.1 功能/安全相关（无遗留）

所有 P0–P3 问题已修复并验证通过。当前无功能阻断或安全漏洞残留。✅

### 8.2 可维护性（P4）

| # | 问题 | 类型 | 首次发现 |
|---|------|------|---------|
| 1 | `do_POST`/`do_PUT`/`do_DELETE` body 读取代码三重重复 | 可维护性 | R2 (review_security_r2.md) |
| 2 | Content-Length 解析风格不一致（两步 vs 一行） | 一致性 | R3 (review_security_r3.md) |
| 3 | `_send_sse` 缺少 `Strict-Transport-Security` 头 | 防御深度 | R3/R1 多次提及 |

### 8.3 改进建议（非阻塞）

| # | 建议 | 难度 | 价值 |
|---|------|------|------|
| 1 | 提取 `_read_body()` 静态方法统一 body 读取（一石三鸟：消除重复+风格统一+降低改 bug 风险） | 低 | 高 |
| 2 | 为 `_send_sse` 补充 HSTS 头 | 低 | 中 |
| 3 | 将 CORS 来源与 `KHUB_API_TOKEN` 联动 | 低 | 低（有鉴权兜底） |
| 4 | 为静态文件服务添加更多 MIME 类型预置（woff2/pdf 等）| 低 | 低 |
| 5 | 设置 `rfile` 读取超时防止慢速攻击耗尽线程池 | 中 | 中（nginx 反代可替代） |
| 6 | Permissions-Policy 补充 `payment=(), fullscreen=(), display-capture=()` | 低 | 低 |

---

## 9. 最终判定

### ✅ 合并就绪

1. **安全响应头**: 全部 6 项（CSP、X-Content-Type-Options、X-Frame-Options、HSTS、Referrer-Policy、Permissions-Policy）均已就位，值正确，覆盖范围合理。
2. **请求体大小限制**: 10MB 上限在 `do_POST`/`do_PUT`/`do_DELETE` 中正确实施。
3. **Transfer-Encoding: chunked 拒绝**: 三处均已实现，位于 body 读取之前。**R1 P2 安全绕过已关闭。**
4. **Content-Length 解析安全**: try/except 覆盖所有三个方法，非法值不抛 500。**R2 P4 健壮性已修复。**
5. **静态文件 MIME 映射**: 9 种扩展名映射正确，`.lower()` 防大小写绕过。**R1 P0 功能阻断已关闭。**
6. **`_send_sse` 鉴权**: 与 `dispatch()` 鉴权逻辑一致，安全时序正确。

### ⚠️ 建议在下一迭代处理

- 提取 body 读取公共方法（P4 技术债，1次修改解决3个残留问题）
- 为 `_send_sse` 补充 HSTS 头（防御深度）

---

*评审人: code-reviewer-19*
*日期: 2026-07-11*
*基准: HEAD ecd2e34 (origin/m1)*
