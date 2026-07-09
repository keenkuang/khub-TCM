# Docker 部署增强 —— 架构角色评审

> 评审提交: `7997ffc` on branch `m1`
> 评审人: CodeBuddy Code (architect role)
> 日期: 2026-07-10

---

## 总体评价

本次提交对 Docker 部署进行了系统性增强，覆盖了镜像构建安全、运行时权限降级、WAL 生命周期管理、Nginx 安全层、部署文档五个维度。设计与实现匹配 PRD 方案，没有架构层面的硬伤。以下按文件逐一分析。

---

## 一、Dockerfile

### ✅ 正确的

| 项目 | 评价 |
|------|------|
| `python:3.12-slim` | 升级到 3.12，安全更新及时，基础镜像精简 |
| 非 root 用户 | `addgroup --system app && adduser --system --ingroup app app`，标准的 system 级用户创建方式 |
| `dumb-init` | 作为 PID 1 收割僵尸进程——对于 spawn 子进程（SshReplica、scheduler）的应用是必要的 |
| `--no-install-recommends` | 减少攻击面 |
| 分层缓存设计 | `COPY pyproject.toml` → `pip install` → `COPY .` → `pip install -e .`，依赖层独立缓存 |
| `chown -R app:app /app` | 确保运行时源码目录权限正确 |
| HEALTHCHECK 用纯 stdlib | 无需 curl，镜像更精简 |
| `rm -rf /var/lib/apt/lists/*` | 同层清理 apt 缓存，防止缓存残留到镜像层 |

### ⚠️ 建议

| # | 问题 | 严重度 | 建议 |
|---|------|--------|------|
| A1 | 预装 `pip install PyYAML pypdf ...` 未锁定版本 | **中** | 未锁定版本意味着每次镜像构建可能拉取不同版本，引入非预期的行为变更。建议在 `pyproject.toml` 中约束依赖版本来对齐预装版本，或给预装命令加 `-c constraints.txt` |
| A2 | 未曾使用 `USER app` 指令 | **低** | 当前设计是 entrypoint 以 root 启动 → chown 降权 → su 到 app 运行。这是有意为之的（需要 root 权限修正卷所有权），模式常见。建议在 Dockerfile 注释中明确标注："ENTRYPOINT 以 root 启动以修正卷所有权，随后降权运行" |
| A3 | 无 GOSU fallback | **低** | 当前 `su -s /bin/sh app -c` 在 `dumb-init` 下工作正常。但如果未来需要考虑 `docker stop` 信号传播到子进程，`su` 不传递信号。改用 `gosu` 可确保信号正确传递。当前非阻塞问题，但可作为 future enhancement 记录 |

---

## 二、docker-entrypoint.sh

### ✅ 正确的

| 项目 | 评价 |
|------|------|
| `set -e` | 关键错误时立即失败，行为可预期 |
| `chown ... 2>/dev/null \|\| true` | 优雅处理卷首次挂载时权限修正，忽略不存在的目录 |
| `exec dumb-init` | `exec` 替换 shell 进程，PID 1 由 dumb-init 接管，信号传递正确 |
| `su -s /bin/sh app` | 降权到非 root 用户 |

### ⚠️ 建议

| # | 问题 | 严重度 | 建议 |
|---|------|--------|------|
| B1 | `$*` 展开丢失参数边界 | **低** | 使用 `$*` 会将所有参数用空格拼接。若 CMD 中某参数包含空格，会解析错误。改为 `"$@"` 可保留参数边界。当前 CMD 是固定的简单值（`serve --host 0.0.0.0 --port 8765`），实际无风险，但作为 shell 脚本惯例建议修复 |
| B2 | 卷挂载覆盖入口脚本 | **低** | `docker-compose.yml` 将 `docker-entrypoint.sh` 卷挂载到容器内（`./docker-entrypoint.sh:/usr/local/bin/docker-entrypoint.sh:ro`），方便开发时热更新，但生产环境本应使用镜像内置版本。建议在 `docker-compose.yml` 中标注"开发阶段覆盖，CI/CD 构建时应去掉此行" |

### 🔧 B1 修复示例

```sh
exec dumb-init su -s /bin/sh app -c "python -m khub.cli $@"
```

---

## 三、docker-compose.yml

### ✅ 正确的

| 项目 | 评价 |
|------|------|
| `KHUB_WAL_KEEP=1000` / `KHUB_WAL_KEEP_DAYS=7` | 为 WAL 日志设置保留窗口，防止无限制增长耗尽磁盘 |
| `PII_KEY` 挂载路径从 `/root/` 改为 `/home/app/` | 与非 root 用户一致 |
| SSH/PII 路径修正 | 完整 |
| `stop_grace_period: 60s` | 给服务足够时间完成 WAL 落盘等清理操作 |
| nginx `depends_on: condition: service_healthy` | 严格的启动顺序，避免 nginx 在 khub 未就绪前转发请求 |
| 资源限制（mem_limit/cpus） | 防止单容器耗尽宿主机资源 |
| `restart: unless-stopped` | 两个服务均已配置 |

### ⚠️ 建议

| # | 问题 | 严重度 | 建议 |
|---|------|--------|------|
| C1 | 缺少网络隔离 | **高** | 两个服务处于默认共享网络（`default`），khub 端口（8765）对同一网络内所有容器可见。建议为 khub 创建 internal-only 网络，阻止外部容器访问 khub 内部 API。nginx 作为入口暴露到外部网络 |

**修复示例**：

```yaml
networks:
  internal:
    internal: true    # khub 内网
  external:           # nginx 对外

services:
  khub:
    networks:
      - internal    # 仅内网
  nginx:
    networks:
      - internal    # 可访问 khub
      - external    # 暴露 80/443
```

---

## 四、nginx/khub-docker.conf

### ✅ 正确的

| 项目 | 评价 |
|------|------|
| CSP header | `default-src 'self'` + `form-action 'none'` + `frame-ancestors 'none'`，防护 XSS 和点击劫持 |
| 已有安全头 | `X-Content-Type-Options`, `X-Frame-Options`, `HSTS` |
| HTTP → HTTPS 强制跳转 | 完整 |
| TLS 配置 | TLSv1.2 + TLSv1.3 仅，密码套件安全 |
| WebSocket 支持 | `proxy_set_header Upgrade` / `Connection "upgrade"`，支持 SSE/WebSocket |
| `proxy_buffering off` | 正确——RAG 流式输出需要实时透传，关掉缓冲 |
| SPA 友好 | `proxy_http_version 1.1` 正确 |

### ⚠️ 建议

| # | 问题 | 严重度 | 建议 |
|---|------|--------|------|
| D1 | CSP 允许 `'unsafe-inline'` 脚本/样式 | **中** | `script-src 'self' 'unsafe-inline'` 和 `style-src 'self' 'unsafe-inline'` 意味着 CSP 总体效果被大幅削弱——内联脚本可以从 XSS 执行。建议调查前端是否可以使用 nonce 或 hash 替代 `unsafe-inline`。如果前端是 SPA 框架（React/Vue 的样式注入），`style-src 'unsafe-inline'` 可能无法避免；但 `script-src 'unsafe-inline'` 应优先尝试 nonce 方案 |
| D2 | `form-action 'none'` 可能阻塞功能 | **中** | 如果前端有原生 HTML `<form>` 提交（如搜索表单直接 POST 到后端），`form-action 'none'` 会阻止所有表单提交。如果所有表单都通过 JS fetch 提交，则无影响。**需要前端验证** |
| D3 | `X-XSS-Protection: 1; mode=block` 已废弃 | **低** | 此 header 已在 Chrome/Edge/Safari 中移除，仅作兼容保留。安全影响极小，但文档中标注时建议说明其现状 |
| D4 | 未配置 `proxy_cookie_flags` | **低** | 若未来引入 session cookie，建议增加 `proxy_cookie_flags ~ (.*) SameSite=Lax; HttpOnly; Secure`，减少 CSRF 风险 |

---

## 五、docs/deployment.md

### ✅ 正确的

| 项目 | 评价 |
|------|------|
| 版本号 0.2.4 | 与当前功能对齐 |
| 三种部署方式（pip/Docker 单容器/Docker Compose） | 完整覆盖不同场景 |
| 功能概览表格 | 清晰展示 v0.2.4 功能集合 |
| 安全矩阵表格 | 整理了所有安全措施，便于运维者快速了解防护能力 |
| 灾备操作文档化 | 与 `docs/disaster_recovery.md` 和 `docs/ha_dr/` 形成联动 |

### ⚠️ 建议

| # | 问题 | 严重度 | 建议 |
|---|------|--------|------|
| E1 | 升级说明中 `git pull` + `pip install -e .` + `systemctl restart khub` 与 Docker 部署的 `docker compose pull + up -d` 混在同一章节 | **低** | 建议将"升级"拆分为"pip 部署升级"和"Docker 部署升级"两个子节，避免运维者混淆 |
| E2 | 安全矩阵中 CSP 标注为"限于 `self` 加载"有误导性 | **低** | 实际 CSP 中包含了 `'unsafe-inline'`，并非严格限于 `self`。建议在安全表格的 CSP 行加注"（含 unsafe-inline 回退）" |

---

## 汇总

### 必须修复

| # | 文件 | 问题 |
|---|------|------|
| C1 | docker-compose.yml | 缺少 internal 网络隔离，khub 端口对同网络所有容器可见 |

### 建议修复

| # | 文件 | 问题 |
|---|------|------|
| A1 | Dockerfile | 预装依赖未锁定版本 |
| D1 | nginx/khub-docker.conf | CSP `'unsafe-inline'` 削弱防护效果 |
| D2 | nginx/khub-docker.conf | `form-action 'none'` 需前端验证 |
| B1 | docker-entrypoint.sh | `$*` 应替换为 `$@` |

### 仅供参考

| # | 文件 | 问题 |
|---|------|------|
| A2、A3 | Dockerfile | USER 注释标注、gosu future enhancement |
| B2 | docker-compose.yml | 入口脚本卷挂载的生产标注 |
| D3 | nginx/khub-docker.conf | X-XSS-Protection 已废弃说明 |
| D4 | nginx/khub-docker.conf | proxy_cookie_flags 未来预案 |
| E1、E2 | docs/deployment.md | 升级章节拆分、CSP 标注精确性 |

---

*评审结束。整体方向正确，实现质量高，无架构级阻塞问题。建议优先修复网络隔离（C1），其余可在 v0.2.5 迭代中打磨。*
