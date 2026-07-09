# Docker 部署安全评审 —— 第 2 轮 (R2)

**评审范围**: commit bf3e90d (R1 修复)，基于 R1 报告 `docs/review_docker_role_security.md`
**评审日期**: 2026-07-10
**R1 修复提交**: `bf3e90d fix(docker): 多角色评审修复——网络隔离 + 限流 + entrypoint`

---

## 1. R1 修复验证

### 1.1 M2 — Nginx 限流

| 属性 | 值 |
|------|------|
| R1 建议 | `limit_req_zone $binary_remote_addr zone=api:10m rate=30r/m` |
| 实际实施 | `limit_req_zone $binary_remote_addr zone=khub_limit:10m rate=20r/s` |
| 范围 | 仅 `location /`，未覆盖 `/health` |

**验证结果**: ⚠️ 部分修复，存在 3 个问题：

**(1) 速率过高** — R1 建议 30r/m (0.5r/s)，实际用了 20r/s (1200r/m)，差 40 倍。20r/s 无法阻止暴力破解：攻击者可用单 IP 在约 14 小时内尝试完 6 位数字 PIN 全空间 (1M / 20 = 50,000s ≈ 14h)。

**(2) `/health` 端点未限流** — `location /health` 块（khub-docker.conf:48-52）内无 `limit_req` 指令，攻击者可通过 `/health` 绕过限流进行 DDoS。

**(3) 无被拦截请求日志** — `limit_req zone=khub_limit burst=50 nodelay` 静默丢弃超出请求，nginx access_log 和 error_log 均不记录被限流的请求，运维人员无法感知攻击。

| 文件 | 行号 |
|------|------|
| `nginx/khub-docker.conf` | 7（速率）, 34（burst）, 48-52（/health 豁免） |

---

### 1.2 网络隔离 — khub-net

| 属性 | 值 |
|------|------|
| 实施 | 两服务加入 `khub-net`，网络定义于 compose 尾部 |
| `internal` | `false`（显式非内部网络） |

**验证结果**: ⚠️ 部分修复。

**正向效果**:
- khub 服务无 `ports:` 映射，不会对外暴露端口 ✅
- 所有 khub 流量必须经过 nginx 反代 ✅
- docker-compose 内依赖关系仅通过内部 DNS 解析 ✅

**遗留问题**:
- `internal: false` 意味着该网络**未隔离**—khub 容器可访问外网，其他容器（如不在 khub-net 上的容器）通过 Docker 默认 bridge 也可能访问 khub
- 生产环境应使用 `internal: true` 并由 nginx 充当唯一入口（nginx 可同时加入内部 `khub-net` 和外部网络）

| 文件 | 行号 |
|------|------|
| `docker-compose.yml` | 7, 62, 69-71 |

---

### 1.3 Entrypoint `$@` 修复

| 属性 | 值 |
|------|------|
| 原始代码 | `exec dumb-init su -s /bin/sh app -c "python -m khub.cli $*"` |
| 修复后 | `exec dumb-init su -s /bin/sh app -c "python -m khub.cli $@"` |
| Docker CMD | `["serve", "--host", "0.0.0.0", "--port", "8765"]`（**4 个参数**） |

**验证结果**: ❌ **回退性变更 (Regression)**。

**技术分析**:

在 POSIX shell 中，`"$@"` 在双引号内展开为多个独立单词：

```
CMD = ["serve", "--host", "0.0.0.0", "--port", "8765"]
$@  = "serve" "--host" "0.0.0.0" "--port" "8765"

"python -m khub.cli $@" 展开为:
→ "python -m khub.cli serve" "--host" "0.0.0.0" "--port" "8765"

su 接收:
  argv[0] = -s, argv[1] = /bin/sh, argv[2] = app,
  argv[3] = -c, argv[4] = "python -m khub.cli serve"
  argv[5] = "--host", argv[6] = "0.0.0.0", argv[7] = "--port", argv[8] = "8765"
```

`su -c` 仅读取 argv[4] 作为命令，其余参数（`--host 0.0.0.0 --port 8765`）被传递给 shell 作为 `$0` 等，**导致 Python 进程实际运行**：

```
python -m khub.cli serve
# 而非预期的：
python -m khub.cli serve --host 0.0.0.0 --port 8765
```

**原始 `$*` 是正确的**，因为它在双引号内将所有参数合并为单个字符串：
```
"python -m khub.cli $*" → "python -m khub.cli serve --host 0.0.0.0 --port 8765"（单个词）
su -c 接收到完整命令字符串 ✅
```

| 文件 | 行号 |
|------|------|
| `docker-entrypoint.sh` | 6 |
| `Dockerfile` | 32（CMD 定义） |

---

## 2. 未解决的 R1 发现

以下 R1 发现不在 `bf3e90d` 修复范围内，仍然存在：

| 编号 | 标题 | 原始等级 | 状态 |
|------|------|----------|------|
| H1 | 生产部署无强制 API 鉴权 | 高 | ✅ 未改 |
| M1 | CSP `'unsafe-inline'` 削弱 XSS 保护 | 中 | ✅ 未改 |
| M3 | `openssh-client` 带入生产运行时 | 中 | ✅ 未改 |
| L1 | 入口脚本静默忽略 `chown` 错误 | 低 | ✅ 未改 |
| L2 | 自签名证书缺少生产替换说明 | 低 | ✅ 未改 |
| L3 | 环境变量传递密钥不符合 Docker Secrets 最佳实践 | 低 | ✅ 未改 |
| L4 | Nginx 未设置 Referrer-Policy 标头 | 低 | ✅ 未改 |
| I1 | X-XSS-Protection 已在现代浏览器中弃用 | 信息 | ✅ 未改 |

---

## 3. 新发现（R2）

### R2-H1 — Entrypoint `$*`→`$@` 回退性回归

| 属性 | 值 |
|------|------|
| 文件 | `docker-entrypoint.sh` |
| 行号 | 6 |
| CVSS 3.1 | 7.5 (AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H) |
| 等级 | ⚠️ **高** |

**描述**: R1 将 `$*` 改为 `$@`，但 CMD 有 4 个参数（`serve --host 0.0.0.0 --port 8765`），`$@` 在双引号内拆分为多个独立词，导致 `su -c` 仅收到第一个参数 `serve`。剩余参数被丢弃。

**影响**:
- 容器启动时默认绑定 `127.0.0.1:8765`（而非 `0.0.0.0:8765`），内部通信可能失败
- 若未来 CMD 增加额外参数（如 `--debug`、`--config`），均会被静默丢弃
- 该 Bug 可能在特定环境下导致容器健康检查失败、服务不可用

**建议**:
- 立即恢复为 `$*`：`exec dumb-init su -s /bin/sh app -c "python -m khub.cli $*"`
- 如需正确处理带空格的参数，应移出双引号或用数组：
  ```sh
  exec dumb-init su -s /bin/sh app -c "python -m khub.cli $(echo "$@")"
  ```
  或使用 `exec` 代替 `su -c` 包装（如果降权可用 gosu/su-exec 替代）。

---

### R2-M1 — `/health` 端点绕过限流

| 属性 | 值 |
|------|------|
| 文件 | `nginx/khub-docker.conf` |
| 行号 | 48-52 |
| CVSS 3.1 | 5.3 (AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:L) |
| 等级 | **中** |

**描述**: R1 M2 明确指出 `/health` 端点对外可见且无保护。R1 修复仅在 `location /` 上应用了 `limit_req`，`location /health` 完全不受限流约束。

**风险**:
- 攻击者可通过 `/health` 以任意速率请求，占用后端资源
- `/health` 返回文档计数等内部状态，可能泄露业务指标
- 可被用作 DDoS 反射放大向量（R1 已有描述）

**建议**:
- 在 `location /health` 中增加独立限流（更高阈值）：
  ```nginx
  location /health {
      limit_req zone=khub_limit burst=10 nodelay;
      proxy_pass http://khub_backend/health;
      ...
  }
  ```
- 或对 `/health` 使用独立的宽松限流区：
  ```nginx
  limit_req_zone $binary_remote_addr zone=health:10m rate=5r/s;
  ```

---

### R2-M2 — 网络隔离不完整 (`internal: false`)

| 属性 | 值 |
|------|------|
| 文件 | `docker-compose.yml` |
| 行号 | 69-71 |
| CVSS 3.1 | 4.8 (AV:A/AC:L/PR:N/UI:N/S:U/C:L/I:L/A:N) |
| 等级 | **中** |

**描述**: `khub-net` 定义为 `internal: false`，虽解决了 nginx 端口暴露问题，但未实现真正的网络隔离。`internal: false` 意味着：
- khub 容器可以主动发起外网出站连接
- Docker host 上其他容器（如通过 `docker-compose` 其他文件部署的）可通过 Docker DNS 或默认 bridge 访问 khub

**风险**:
- 若 khub 被攻破，攻击者可利用 khub 容器建立 C2 出站隧道
- 若 host 上存在恶意容器，可绕过 nginx 直接访问 khub:8765
- 削弱了网络层面的纵深防御

**建议**:
- 生产环境设置 `internal: true`
- 将 nginx 加入两个网络：`khub-net`（internal）+ `frontend-net`（external），作为唯一对外入口
- docker-compose.yml 示例：
  ```yaml
  networks:
    khub-net:
      internal: true
    frontend-net:
      driver: bridge

  services:
    khub:
      networks: [khub-net]
    nginx:
      networks: [khub-net, frontend-net]
  ```

---

### R2-L1 — 无被拦截请求日志

| 属性 | 值 |
|------|------|
| 文件 | `nginx/khub-docker.conf` |
| 行号 | 34 |
| CVSS 3.1 | 3.7 (AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:L) |
| 等级 | **低** |

**描述**: `limit_req` 静默丢弃超限请求，不在 access_log 或 error_log 中记录。运维人员无法区分"被限流丢包"和"业务无流量"，也难以在遭受 DDoS 时感知攻击频率。

**建议**:
- 在 nginx 配置中增加限流日志级别，至少记录被拒绝的请求：
  ```nginx
  limit_req_log_level warn;
  limit_req_status 429;
  ```
- 考虑在 error_log 中单独记录超限请求的来源 IP

---

### R2-L2 — 限流速率过于宽松

| 属性 | 值 |
|------|------|
| CVSS 3.1 | 3.7 (AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:L) |
| 等级 | **低** |

**描述**: 20r/s 的限流阈值对暴力破解防护效果有限。考虑 khub 是文档库/知识库应用，正常用户操作频率远低于 20r/s（人工阅读 + 搜索）。R1 建议的 30r/m 可能过低，但 20r/s 过松。

**建议**:
- 将速率降低至 60r/m (1r/s) 或 120r/m (2r/s)，burst 调整为 20，在正常用户体验与安全之间取得平衡
- 对不同端点应用不同限流策略（登录/API 端点更严格，静态资源可宽松）

---

### R2-I1 — WebSocket 连接不受 `nodelay` 限流约束

| 属性 | 值 |
|------|------|
| 文件 | `nginx/khub-docker.conf` |
| 行号 | 37-38 |
| 等级 | **信息** |

**描述**: Nginx 配置启用了 WebSocket 升级（`Upgrade $http_upgrade`, `Connection "upgrade"`）。WebSocket 建立后，`nodelay` 模式的 `limit_req` 仅限制握手阶段的请求速率，后续 WebSocket 帧不受限流约束。

**影响**: 风险很低—当前 kHUB 后端 `khub.cli` 不提供 WebSocket 端点，且 `proxy_buffering off` 已禁用缓冲。但若未来引入 WebSocket-based 功能（实时搜索、文档同步），需重新评估限流策略。

**建议**: 当前无需处理。如路线图中包含 WebSocket 功能，届时需增加 WebSocket-specific 限流（如 `limit_conn` 或应用层速率限制）。

---

## 4. 安全基准对照更新

| 基准项目 | R1 状态 | R2 状态 | 备注 |
|----------|---------|---------|------|
| 非 root 用户运行 | ✅ | ✅ | 不变 |
| HEALTHCHECK | ✅ | ✅ | 不变 |
| 资源限制 | ✅ | ✅ | 不变 |
| 只读根文件系统 | ❌ | ❌ | 未处理 |
| `--cap-drop=ALL` | ❌ | ❌ | 未处理 |
| Docker 密钥 | ❌ | ❌ | 未处理 |
| 镜像漏洞扫描 | ❌ | ❌ | 未处理 |
| HSTS | ✅ | ✅ | 不变 |
| CSP | ⚠️ unsafe-inline | ⚠️ unsafe-inline | 未处理 |
| 限流 | ❌ 未配置 | ⚠️ 配置但不足 | 新增：/health 未覆盖、速率过高 |
| 网络隔离 | ❌ 未配置 | ⚠️ 有需强化 | 新增：internal: false |
| 日志审计 | ✅ | ❌ | 新增：限流无日志 |
| Entrypoint 安全性 | ✅ | ❌ | 新增：$@ 回归 Bug |
| API 鉴权 | ❌ | ❌ | 未处理；最高优先级 |

---

## 5. 优先级行动项

| 优先级 | 编号 | 标题 | 文件 | 预估工作量 |
|--------|------|------|------|-----------|
| 🔴 P0 | R2-H1 | 修复 `$@`→`$*` 回退 | `docker-entrypoint.sh` | 1 行 |
| 🔴 P0 | H1 | 强制 API 鉴权 | `docker-compose.yml` + `docs/deployment.md` | 1-2 天 |
| 🟡 P1 | R2-M1 | `/health` 端点限流 | `nginx/khub-docker.conf` | 2 行 |
| 🟡 P1 | R2-M2 | 完善网络隔离 (`internal: true`) | `docker-compose.yml` | 5 行 |
| 🟡 P1 | R2-L1 | 增加限流日志 | `nginx/khub-docker.conf` | 2 行 |
| 🟤 P2 | R2-L2 | 收紧限流速率 | `nginx/khub-docker.conf` | 1 行 |
| 🟤 P2 | M1 | CSP `unsafe-inline` | `nginx/khub-docker.conf` + 前端 | 中长期 |
| 🟤 P2 | L1 | chown 错误日志 | `docker-entrypoint.sh` | 2 行 |
| ⚪ P3 | M3 | SSH 客户端 sidecar | `Dockerfile` | 架构决策 |
| ⚪ P3 | L2-L4, I1 | 标头/文档/Docker Secrets | 多文件 | 低优先 |

---

## 6. 结论

R1 修复（`bf3e90d`）方向正确但存在不足：

1. ❌ **`$@`→`$*` 回退**（R2-H1）是此次修复中最严重的问题，实际破坏了多参数 CMD 传递。应**立即修复**。
2. ⚠️ **限流**（M2）部分实施，速率过高且 `/health` 未覆盖。
3. ⚠️ **网络隔离**有概念但实现不完整（`internal: false`）。
4. 🔴 **API 鉴权**（H1）仍是最重要的安全缺口，未被触及。

建议修复顺序：`docker-entrypoint.sh` 的 1 行回退（P0）→ nginx 限流加强（P1）→ 网络隔离完善（P1）→ API 鉴权（P0，需业务评估）。

---

*评审人: security-bot / general-purpose-36*
*基线: R1 报告 (04e1121) + OWASP Docker Security Cheat Sheet + CIS Docker Benchmark v1.6*
