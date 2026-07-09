# Docker 部署增强 —— 最终实施前评审

> 评审人: general-purpose-41
> 日期: 2026-07-10
> 基准: commit `086638b` (R3 修复) + R4 安全/架构双签

---

## 评审范围

| 文件 | 行数 | 评分 |
|------|------|------|
| `Dockerfile` | 33 | ✅ |
| `docker-entrypoint.sh` | 7 | ✅ |
| `docker-compose.yml` | 87 | ✅ |
| `nginx/khub-docker.conf` | 57 | ✅ |
| `docs/deployment.md` | 163 | ✅ |

---

## 一、语法验证

| 检查项 | 结果 |
|--------|------|
| `docker-compose.yml` YAML 解析 | ✅ 通过 |
| `docker compose config` 服务解析 | ✅ 通过（2 services: khub, nginx） |
| `docker-entrypoint.sh` 语法检查 (`bash -n`) | ✅ 通过 |
| `python3 -c "import urllib.request"`（健康检查）| ✅ 通过 |

---

## 二、R1-R4 七项修复追踪

根据 `git log` 历次 fix commit 逐项验证：

| # | 问题 | 所属 | 修复提交 | 当前状态 | 验证 |
|---|------|------|---------|----------|------|
| 1 | **C1** 网络隔离 | R1 | bf3e90d | `khub-net` 桥接，khub 无 `ports:` | ✅ |
| 2 | **B1** entrypoint `$*` 参数展开 | R1→R2 | bf3e90d→f176e7a | `su -c "python -m khub.cli $*"`（R2 回归正确）| ✅ |
| 3 | **H1/M2** nginx 限流 `30r/m` | R1→R2 | bf3e90d→f176e7a | `rate=30r/m`, `burst=20 nodelay` | ✅ |
| 4 | **R3-1** burst 10→20 | R3 | 086638b | `burst=20 nodelay` | ✅ |
| 5 | **R3-2** PII 路径 `/root/`→`/home/app/` | R3 | 086638b | `KHUB_PII_KEY_FILE=/home/app/.khub/pii.key` | ✅ |
| 6 | **R3-4** `pip install -e .`→`.` | R3 | 086638b | `RUN pip install --no-cache-dir .` | ✅ |
| 7 | **R3-5** SSL 私钥 git 追踪 | R3 | N/A | `.gitignore` 包含 `ssl/`，`git ls-files ssl/` 为空 | ✅ |

**结论：7 项全部正确到位，状态与期望一致。**

---

## 三、关键配置验证

### Dockerfile
- `FROM python:3.12-slim` — ✅ 正确基线
- 非 root `app` 用户 (`adduser --system --ingroup app app`) — ✅
- 分层缓存：`pyproject.toml` → 第三方依赖 → `COPY .` → `pip install .` — ✅
- `dumb-init` 作为 PID 1 — ✅
- `ENTRYPOINT ["docker-entrypoint.sh"]` + `CMD` — ✅
- `HEALTHCHECK` 30s/10s/3retries — ✅

### docker-entrypoint.sh
- `set -e` 安全模式 — ✅
- `chown -R app:app /data/db /data/library 2>/dev/null || true` — ✅ 运行时挂载卷所有权修正
- `exec dumb-init su -s /bin/sh app -c "python -m khub.cli $*"` — ✅ `$*` 在 `su -c` 双引号内正确展开所有参数

### docker-compose.yml
- `networks: khub-net`（两服务一致）— ✅
- `stop_grace_period: 60s` — ✅
- `KHUB_DB`, `KHUB_LIBRARY` 路径与卷挂载对齐 — ✅
- `KHUB_WAL_KEEP=1000`, `KHUB_WAL_KEEP_DAYS=7` — ✅
- `KHUB_PII_ENCRYPT=1` — ✅
- PII 密钥挂载注释路径与 `_FILE` 注释一致 (`/home/app/.khub/pii.key`) — ✅
- 资源限制: 1g mem / 512m reservation / 2 CPUs — ✅
- nginx 服务: `depends_on: khub: condition: service_healthy` — ✅
- SSL 卷挂载 `./ssl:/etc/nginx/ssl:ro` — ✅
- 网络 `internal: false` — ✅（khub 需出站 SSH 灾备/真实模型 API）

### nginx/khub-docker.conf
- upstream `khub:8765`（Docker DNS）— ✅
- HTTP→HTTPS 跳转 — ✅
- TLSv1.2/TLSv1.3 + 安全 ciphers — ✅
- CSP: `default-src 'self'; script-src 'self' 'unsafe-inline'; ...` — ✅
- HSTS `max-age=31536000; includeSubDomains` — ✅
- X-Content-Type-Options, X-Frame-Options, X-XSS-Protection — ✅
- `limit_req zone=khub_limit burst=20 nodelay` — ✅
- WebSocket 支持 (`Upgrade`/`Connection`) — ✅
- `proxy_buffering off`（SSE） — ✅
- `proxy_read_timeout 120s` — ✅
- 访问日志 stdout, 错误日志 stderr — ✅

### docs/deployment.md
- 版本 0.2.4 — ✅
- 三种部署方式 (pip / Docker / Docker Compose) 完整 — ✅
- SSL 证书生成步骤 — ✅
- 环境变量表与配置对齐 — ✅
- 安全措施列出完整 — ✅
- 备份/恢复命令 — ✅

---

## 四、回归检查

| 检查项 | 状态 |
|--------|------|
| R2-H1 `$*` 回归是否退化 | ✅ 未退化，仍为 `$*` |
| 非 root `app` 用户是否保留 | ✅ 保留 |
| 30r/m 限流是否改变 | ✅ 未改变 |
| HSTS/CSP/安全标头是否变化 | ✅ 未变化 |
| `KHUB_PII_ENCRYPT=1` 是否保留 | ✅ 保留 |
| entrypoint 参数传递是否完整 | ✅ 4 个 CMD 参数全部进入 |
| 网络隔离策略是否退化 | ✅ 未退化 |

**结论：086638b 未引入任何新回归。**

---

## 五、R4 双签状态

| 评审角色 | 结论 | 引用 |
|----------|------|------|
| 架构评审 (R4) | ✅ **最终签署通过** | `review_docker_role_arch_r4.md` |
| 安全评审 (R4) | ✅ **本轮无阻塞安全问题** | `review_docker_role_security_r4.md` |

**剩余开放项（8 项）**：
均标记为"建议修复"或"仅供参考"等级，跨四轮未恶化，非合并阻塞。

优先级建议（来自安全 R4）：
1. P0: API 鉴权（最大攻击面，需业务评估）
2. P1: `/health` 限流 + 网络隔离 `internal: true`
3. P2: `cap_drop: ALL`, `read_only`, `no-new-privileges`
4. P3: CSP 强化, SSH sidecar

---

## 六、合并就绪评估

| 维度 | 评价 |
|------|------|
| 语法正确性 | ✅ 全部通过 |
| 7 项修复验证 | ✅ 全部验证通过 |
| 回归检查 | ✅ 无回归 |
| 架构评审 (R4) | ✅ 签署通过 |
| 安全评审 (R4) | ✅ 签署通过 |
| 文档一致性 | ✅ 配置与文档对齐 |

### 最终结论：**✅ 合并就绪**

所有阻塞性/关键问题已关闭。经过 4 轮角色化评审（架构 ×4 + 安全 ×4），Docker 部署增强方案实现质量达到合并标准。

---

*本报告基于 `git log` 追溯 + 实际文件内容静态分析 + 工具语法验证生成。*
