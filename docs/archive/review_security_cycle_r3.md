# 安全加固循环第 3 轮（R3）评审报告

**评审时间**: 2026-07-10  
**评审对象**: `khub/api.py`（commit `b4a45a3`）  
**评审范围**: 安全加固 R2 周期修复——负值 Content-Length + 多值 Transfer-Encoding

---

## 1. 评审结论

**状态: ✅ 全部通过 — 修复正确，无新问题**

R2 周期提交 `b4a45a3` 的两项修复已在 `do_POST` / `do_PUT` / `do_DELETE` 三个方法中正确、一致地落地。未发现遗漏、不一致或引入的新安全问题。

---

## 2. R2 修复核对

### 2.1 C2-1: 负值 Content-Length 绕过体积极限

| 攻击向量 | `int(-1)` → `rfile.read(-1)` → `rfile.read()` 读取全部数据，绕过 10MB 上限 |
|-----------|----------------------------------------------------------------|
| 修复要求 | 三个方法均在 `int()` 解析后追加 `if length < 0: length = 0` |
| 状态 | ✅ **全部通过** |

**逐行确认**:

| 方法 | 行号 | 代码 | 通过 |
|------|------|------|:----:|
| `do_POST` | 509–510 | `if length < 0:\n    length = 0` | ✅ |
| `do_PUT` | 551–552 | `if length < 0:\n    length = 0` | ✅ |
| `do_DELETE` | 578–579 | `if length < 0:\n    length = 0` | ✅ |

**修复逻辑正确性**:
- 负值 Content-Length 被钳制为 0，`rfile.read(0)` 返回空字节串，不会读取请求体
- 后续 `json.loads(b"{}")` 正常处理空内容
- 钳制发生在体积极限检查 (`_MAX_BODY_SIZE`) 之前，因此 `0 < 10MB` 不会触发 413，行为正确

### 2.2 C2-2: 多值 Transfer-Encoding 绕过 chunked 检测

| 攻击向量 | `Transfer-Encoding: gzip, chunked` → `"gzip, chunked" == "chunked"` 为 `False`，绕过拒绝 |
|-----------|----------------------------------------------------------------------|
| 修复要求 | `== "chunked"` 改为 `"chunked" in ...` |
| 状态 | ✅ **全部通过** |

**逐行确认**:

| 方法 | 行号 | 代码 | 通过 |
|------|------|------|:----:|
| `do_POST` | 502 | `"chunked" in self.headers.get("Transfer-Encoding", "").lower()` | ✅ |
| `do_PUT` | 545 | `"chunked" in self.headers.get("Transfer-Encoding", "").lower()` | ✅ |
| `do_DELETE` | 572 | `"chunked" in self.headers.get("Transfer-Encoding", "").lower()` | ✅ |

**修复逻辑正确性**:
- `in` 操作符在逗号分隔的多值头中正确匹配子串 `"chunked"`
- `.lower()` 确保大小写不敏感（防御 `Transfer-Encoding: CHUNKED` 等变体）
- `.get(..., "")` 确保缺失头时不会抛出异常，空字符串不包含 `"chunked"`

---

## 3. 安全响应头（_send 方法）全量核对

| 响应头 | 值 | 位置 | 通过 |
|--------|-----|------|:----:|
| `X-Content-Type-Options` | `nosniff` | 无条件发送 | ✅ |
| `X-Frame-Options` | `DENY` | 无条件发送 | ✅ |
| `Referrer-Policy` | `no-referrer` | 无条件发送 | ✅ |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), interest-cohort=()` | 无条件发送 | ✅ |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | **无条件发送**（R3 已修复原 `if code == 200` 条件） | ✅ |
| `Content-Security-Policy` | `default-src 'self'; ...; object-src 'none'` | 仅 `text/html` 响应 | ✅ |

---

## 4. MIME 类型映射

| 扩展名 | MIME 类型 | 通过 |
|--------|-----------|:----:|
| `.html` | `text/html; charset=utf-8` | ✅ |
| `.css` | `text/css; charset=utf-8` | ✅ |
| `.js` | `application/javascript; charset=utf-8` | ✅ |
| `.png` | `image/png` | ✅ |
| `.jpg` / `.jpeg` | `image/jpeg` | ✅ |
| `.svg` | `image/svg+xml` | ✅ |
| `.ico` | `image/x-icon` | ✅ |
| `.json` | `application/json` | ✅ |
| 未匹配 | `application/octet-stream`（fallback） | ✅ |

---

## 5. 新增/遗留问题

| 编号 | 类型 | 描述 | 严重程度 |
|:----:|:----:|------|:--------:|
| R3-01 | 观察 | `do_OPTIONS` 未调用 `_send()`，未设置安全响应头。OPTIONS 预检请求不渲染内容，实际影响极低 | 🔹 仅供参考 |
| R3-02 | 观察 | `_send_sse()` 未调用 `_send()`，SSE 响应缺少安全头。SSE (`text/event-stream`) 不会被浏览器渲染为文档，影响极低 | 🔹 仅供参考 |
| R3-03 | 观察 | `do_POST` 与 `do_PUT`/`do_DELETE` 的 Content-Length 解析写法略有差异（前者先 `get` 再 try，后者 `get` + `or "0"` 内联），但功能等价 | 🔹 仅供参考 |

以上三项均为低风险观察项，不影响当前发布。`_send_sse` 若后续需要增加安全头，可通过抽取 `_security_headers()` 辅助方法统一注入。

---

## 6. diff 验证

执行 `git diff b4a45a3 -- khub/api.py` 确认当前文件与 HEAD 一致：**无未暂存修改**。

---

**评审人**: code-reviewer-21  
**最终裁定**: ✅ 修复正确，无新增问题，建议合并
