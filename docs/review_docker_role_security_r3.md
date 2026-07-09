# Docker 部署安全评审 —— 第 3 轮 (R3)

**评审范围**: commit `f176e7a` (R2 修复)，基于 R1 `review_docker_role_security.md` + R2 `review_docker_role_security_r2.md`
**评审日期**: 2026-07-10
**R2 修复提交**: `f176e7a fix(docker): R2 评审修复——回归 + 限流收紧`

---

## 1. R2 修复验证（commit f176e7a）

### 1.1 R2-H1 — Entrypoint `$@` → `$*` 回退

| 属性 | 值 |
|------|------|
| 原始（R2 发现） | `$@` 在 `su -c "..."` 双引号内拆词，仅传递 `serve` |
| R2 建议 | 恢复为 `$*` |
| f176e7a 实际 | `$*` |
| 当前代码 (`docker-entrypoint.sh:6`) | `exec dumb-init su -s /bin/sh app -c "python -m khub.cli $*"` |

**验证结果**: ✅ 已正确修复。`$*` 在双引号内将所有 CMD 参数合并为单字符串，`su -c` 收到完整命令 `python -m khub.cli serve --host 0.0.0.0 --port 8765`。

---

### 1.2 R2-L2 — 限流速率 20r/s → 30r/m

| 属性 | 值 |
|------|------|
| R2 发现 | 20r/s (1200r/m) 过松，R1 建议 30r/m |
| f176e7a 实际 | `rate=30r/m`，`burst=50→10` |
| 当前代码 (`khub-docker.conf:7,34`) | `rate=30r/m` / `burst=10 nodelay` |

**验证结果**: ✅ 限流速率已从 20r/s 收紧至 30r/m。burst 从 50 减至 10。

---

## 2. R2 未修复发现（仍存在）

以下 R2 新发现**未在 f176e7a 中处理**，当前版本仍然存在：

| 编号 | 标题 | 等级 | 位置 |
|------|------|------|------|
| R2-M1 | `/health` 端点绕过限流 | 中 | `khub-docker.conf:48-52` |
| R2-M2 | 网络隔离不完整 (`internal: false`) | 中 | `docker-compose.yml:69-71` |
| R2-L1 | 无被拦截请求日志 (`limit_req_log_level`) | 低 | `khub-docker.conf:34` |

详情见 R2 报告 `review_docker_role_security_r2.md` §3。

---

## 3. R1 未修复发现（仍存在）

以下 R1 发现从未被处理，三个版本均未修正：

| 编号 | 标题 | 等级 | 位置 |
|------|------|------|------|
| H1 | 生产部署无强制 API 鉴权 | 高 | `docker-compose.yml:18-34` |
| M1 | CSP `'unsafe-inline'` 削弱 XSS 保护 | 中 | `khub-docker.conf:28` |
| M3 | `openssh-client` 带入生产运行时 | 中 | `Dockerfile:5` |
| L1 | 入口脚本静默忽略 `chown` 错误 | 低 | `docker-entrypoint.sh:5` |
| L2 | 自签名证书缺少生产替换说明 | 低 | `docs/deployment.md` |
| L3 | 环境变量传递密钥 | 低 | `docker-compose.yml` |
| L4 | Nginx 未设置 Referrer-Policy 标头 | 低 | `khub-docker.conf` |
| I1 | X-XSS-Protection 在现代浏览器中已弃用 | 信息 | `khub-docker.conf:27` |

---

## 4. 新发现（R3）

### R3-M1 — 30r/m + burst=10 造成可用性问题

| 属性 | 值 |
|------|------|
| 文件 | `nginx/khub-docker.conf` |
| 行号 | 7, 34 |
| CVSS 3.1 | 5.3 (AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:L) |
| 等级 | **中** |

**描述**: 当前限流 `rate=30r/m` + `burst=10 nodelay` 在安全性和可用性之间存在失衡。

**定量分析**:
- 稳态速率：1 请求 / 2 秒（30r/m）
- Burst 容量：10 个令牌
- 现代 Web 页面加载典型产生 5–15 个子请求（CSS、JS、字体、图像）
- 单次页面加载即可耗尽 burst 配额
- 耗尽后用户立即导航下一页面 → 返回 429 Too Many Requests

**场景推演**:
```
t=0s    用户打开 khub 首页 → 12 个子请求 → 10 成功, 2 个被限流 (429)
t=2s    令牌恢复 1 个
t=4s    恢复 2 个
t=10s   用户点击导航 → 8 个子请求 → 只有 5 个令牌可用 → 3 个被限流
```

**风险**: 正常用户频繁收到 429，要么放弃使用，要么运维人员被迫关闭限流——反而更不安全。

**建议**:
- 将速率提升至 **60r/m～120r/m**（即 1–2 req/s），burst 调整为 **20～30**
- 或对 API 路径和静态资源路径采用**差异化限流**：
  ```nginx
  location /api/ { limit_req zone=api:10m rate=30r/m; ... }
  location /static/ { limit_req zone=static:10m rate=120r/m; ... }
  ```
- 如当前无静态资源路径，至少确保 `/health` 拥有独立宽松限流

---

### R3-L1 — 缺少 `no-new-privileges`

| 属性 | 值 |
|------|------|
| 文件 | `docker-compose.yml` (khub 服务) |
| 行号 | 2–45 |
| CVSS 3.1 | 3.3 (AV:L/AC:L/PR:L/UI:N/S:U/C:N/I:L/A:N) |
| 等级 | **低** |

**描述**: 未设置 `security_opt: no-new-privileges:true`。该配置可阻止容器内进程通过 SUID 二进制文件或 `su` 进行权限提升。虽然 khub 以 `app` 用户运行，但若应用层被攻破，攻击者可利用容器内的 SUID 程序（如 `su`、`mount`、`ping`）提升回 root。

**CIS Docker Benchmark**: 5.19 — 推荐在所有生产容器中启用。

**建议**: 在 `khub` 服务下添加：
```yaml
security_opt:
  - no-new-privileges:true
```

---

### R3-L2 — 缺少 `read_only` 根文件系统

| 属性 | 值 |
|------|------|
| 文件 | `docker-compose.yml` (khub 服务) |
| 行号 | 2–45 |
| CVSS 3.1 | 3.1 (AV:L/AC:L/PR:L/UI:N/S:U/C:N/I:L/A:N) |
| 等级 | **低** |

**描述**: 未设置容器根文件系统只读。容器内的 `/tmp`、`/var` 等路径可被写入，攻击者可在容器逃逸场景下写入恶意文件。khub 的所有持久化数据通过卷挂载到 `/data/db` 和 `/data/library`，因此将根文件系统设为只读不会影响正常功能。

**注意**: `chown` 在 `docker-entrypoint.sh:5` 中写入 `/data/db` 和 `/data/library`（两个路径都是卷），不会受 `read_only` 影响。但如果用户手动将卷挂载为 `:ro`，`chown` 将静默失败（见 R1 L1）。

**CIS Docker Benchmark**: 5.2 — 推荐使用 `--read-only` 标志。

**建议**: 添加 `read_only: true` 到 khub 服务：
```yaml
khub:
  read_only: true
```

---

### R3-L3 — 缺少 `cap_drop: ALL`

| 属性 | 值 |
|------|------|
| 文件 | `docker-compose.yml` (khub 服务) |
| 行号 | 2–45 |
| CVSS 3.1 | 4.2 (AV:L/AC:L/PR:L/UI:N/S:U/C:N/I:L/A:L) |
| 等级 | **低** |

**描述**: 未显式丢弃容器 capabilities。虽然 khub 以非 root 用户运行，但 Linux capabilities 在内核级独立生效。默认 Docker 容器仍拥有超过 14 种 capabilities（如 CAP_NET_RAW、CAP_DAC_OVERRIDE、CAP_CHOWN 等）。

**风险**:
- CAP_CHOWN：即使以 app 用户运行，内核仍允许改变文件所有权（已被 chown 调用利用）
- CAP_NET_RAW：允许原始套接字，可用于 ARP 欺骗或 ICMP 隧道
- CAP_DAC_OVERRIDE：允许绕过文件读写权限检查

**建议**: 丢弃所有 capabilities，按需添加最小集合：
```yaml
khub:
  cap_drop:
    - ALL
  cap_add: []     # 如需要，逐项加入（当前无明确需求）
```

---

### R3-I1 — `limit_req` burst=10 与 30r/m 的令牌桶数学关系

| 属性 | 值 |
|------|------|
| 文件 | `nginx/khub-docker.conf` |
| 行号 | 7, 34 |
| 等级 | **信息** |

**说明**: 30r/m (0.5r/s) 的速率下，令牌按 1 个 / 2 秒生成。burst=10 意味着需要 20 秒填满 burst。这意味着：
- 用户在高频操作间隔 <20 秒时持续被限流
- 用户低频操作（间隔 >3 分钟）时 burst 已完全恢复
- 这种模式不适合 Web 应用，更适合纯 API 场景

**建议**: 结合 R3-M1 一并调整。

---

## 5. 安全基准对照更新

| 基准项目 | R1 | R2 | R3 | 备注 |
|----------|----|----|----|------|
| 非 root 用户运行 | ✅ | ✅ | ✅ | 不变 |
| HEALTHCHECK | ✅ | ✅ | ✅ | 不变 |
| 资源限制 | ✅ | ✅ | ✅ | 不变 |
| HSTS | ✅ | ✅ | ✅ | 不变 |
| 只读根文件系统 | ❌ | ❌ | ❌ | R3-L2 |
| `cap_drop=ALL` | ❌ | ❌ | ❌ | R3-L3 |
| `no-new-privileges` | ❌ | ❌ | ❌ | R3-L1 |
| Docker 密钥 | ❌ | ❌ | ❌ | 未处理 |
| 镜像漏洞扫描 | ❌ | ❌ | ❌ | 未处理 |
| CSP | ⚠️ | ⚠️ | ⚠️ | 未处理 |
| 限流 | ❌ | ⚠️ | ⚠️ (新问题) | R3-M1 |
| 网络隔离 | ❌ | ⚠️ | ⚠️ | R2-M2 未修 |
| 日志审计 | ✅ | ❌ | ❌ | R2-L1 未修 |
| Entrypoint 安全性 | ✅ | ❌ | ✅ | 已修复 |
| API 鉴权 | ❌ | ❌ | ❌ | H1 未修（最高优先） |

---

## 6. 累积优先级行动项

| 优先级 | 编号 | 标题 | 文件 | 工作量 |
|--------|------|------|------|--------|
| 🔴 P0 | H1 | 强制 API 鉴权 | `docker-compose.yml` + `docs/deployment.md` | 1–2 天 |
| 🟡 P1 | R2-M1 | `/health` 端点限流 | `khub-docker.conf` | 2 行 |
| 🟡 P1 | R2-M2 | 网络隔离 `internal: true` | `docker-compose.yml` | 5 行 |
| 🟡 P1 | R3-M1 | 限流速率调整防可用性问题 | `khub-docker.conf` | 1–5 行 |
| 🟤 P2 | R2-L1 | 增加限流日志 | `khub-docker.conf` | 2 行 |
| 🟤 P2 | R3-L1 | `no-new-privileges` | `docker-compose.yml` | 2 行 |
| 🟤 P2 | R3-L2 | `read_only` 根文件系统 | `docker-compose.yml` | 1 行 |
| 🟤 P2 | R3-L3 | `cap_drop: ALL` | `docker-compose.yml` | 3 行 |
| 🟤 P2 | M1 | CSP `unsafe-inline` | `khub-docker.conf` + 前端 | 中长期 |
| ⚪ P3 | M3 | SSH 客户端 sidecar | `Dockerfile` | 架构决策 |
| ⚪ P3 | L1–L4, I1 | 标头/文档/Docker Secrets | 多文件 | 低优先 |

---

## 7. 结论

commit `f176e7a` 正确修复了 R2 的两个关键问题：

1. ✅ `$@` → `$*` 回退 — entrypoint 参数传递已恢复正常
2. ✅ 限流 20r/s → 30r/m — 暴力破解速率窗口显著收缩

**未修复遗留问题**: R2-M1 (/health 绕过限流)、R2-M2 (internal: false)、R2-L1 (限流无日志) 仍待处理。

**本次新增 4 项发现**:

| 编号 | 标题 | 等级 |
|------|------|------|
| R3-M1 | 30r/m + burst=10 可用性问题（正常页面加载即触发 429） | 🟡 P1 |
| R3-L1 | 缺少 `no-new-privileges` | 🟤 P2 |
| R3-L2 | 缺少 `read_only` 根文件系统 | 🟤 P2 |
| R3-L3 | 缺少 `cap_drop: ALL` | 🟤 P2 |

**R3-M1 值得特别注意**: 当前限流参数虽然安全上显著好于 20r/s，但 30r/m 在日常 Web 浏览中会频繁触发 429，可能迫使运维完全关闭限流。建议在收紧 `/health` 限流的同时，适当放宽 API 主限流至 60–120r/m。

**优先级建议**:
1. **P0**: API 鉴权（H1）——从 R1 起就是最大攻击面，积累 3 轮未处理
2. **P1**: `/health` 限流 + 网络隔离 + 主限流速率校准
3. **P2**: Docker 安全加固（cap_drop、read_only、no-new-privileges）+ 限流日志

---

*评审人: security-bot / general-purpose-38*
*基线: R1 (04e1121) + R2 (bf3e90d) + R2 修复 (f176e7a)*
