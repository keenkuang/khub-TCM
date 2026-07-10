# Docker 部署安全角色评审报告

**评审范围**: commit 7997ffc, branch m1
**评审日期**: 2026-07-10
**评审文件**:
| 文件 | 行数 | 角色 |
|------|------|------|
| `Dockerfile` | 33 | 镜像构建定义 |
| `docker-entrypoint.sh` | 7 | 容器入口 & 权限降级 |
| `docker-compose.yml` | 79 | 编排配置 & 密钥管理 |
| `nginx/khub-docker.conf` | 52 | 反向代理 & 安全标头 |
| `docs/deployment.md` | 163 | 生产部署指引 |

**方法**: 人工审查 + 模式匹配（OWASP Docker Security Cheat Sheet、CIS Docker Benchmark、NIST SP 800-190）。

---

## 摘要

本次评审共发现 **9 项安全发现**，按严重程度分：

| 等级 | 数量 | 编号 |
|------|------|------|
| 高 | 1 | H1 |
| 中 | 3 | M1 — M3 |
| 低 | 4 | L1 — L4 |
| 信息 | 1 | I1 |

---

## 详细发现

### H1 — 生产部署无强制 API 鉴权

| 属性 | 值 |
|------|------|
| 文件 | `docker-compose.yml` + `docs/deployment.md` |
| 位置 | compose.yml:18-34, deployment.md:94 |
| CVSS 3.1 | 6.5 (AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:L/A:N) |

**描述**: `KHUB_API_TOKEN` 在 docker-compose.yml 中未设置，deployment.md 注明默认值为空（不鉴权）。安装说明（方式 A）中 `khub serve` 绑定 127.0.0.1 靠网络层封闭；但 Docker Compose 部署通过 nginx 对外暴露 80/443 端口，此时 API 完全对外开放，**无任何认证校验**。

**风险**:
- 攻击者可未经认证调用所有 API 端点
- 检索/删除库中文档、读取 PII 数据、触发灾备操作
- 若 LLM 模块开启，攻击者可消耗 LLM 配额

**建议**:
- docker-compose.yml 中预先设置一个占位 API Token（或强制要求用户配置）
- deployment.md "生产建议" 节将 `KHUB_API_TOKEN` 设为**必选**配置项
- nginx 层可增加 `auth_basic` 作为额外防护层

---

### M1 — CSP `'unsafe-inline'` 削弱 XSS 保护

| 属性 | 值 |
|------|------|
| 文件 | `nginx/khub-docker.conf` |
| 位置 | 第 25 行 |
| CVSS 3.1 | 5.4 (AV:N/AC:L/PR:N/UI:R/S:U/C:L/I:L/A:N) |

**描述**: Content-Security-Policy 配置了 `default-src 'self'`、`script-src 'self' 'unsafe-inline'` 和 `style-src 'self' 'unsafe-inline'`。`'unsafe-inline'` 允许所有内联 `<script>` 和 `<style>` 标签执行，如果应用存在任何反射型或存储型 XSS 漏洞，攻击者可通过注入内联脚本完全绕过 CSP。

**风险**: 任何 XSS 漏洞的攻击面不受 CSP 压缩; 内联脚本使 CSP 的双层防护失效。

**建议**:
- 评估 Jinja2 模板是否可通过 nonce 或 hash 替换 `'unsafe-inline'`
- 短期缓解：至少将 production 环境的 `script-src` 收紧为 `'strict-dynamic'` + nonce（需应用侧配合）
- 若路线图中已纳入前端构建流程，考虑引入 nonce 生成机制

---

### M2 — Nginx 无限流/防暴力破解

| 属性 | 值 |
|------|------|
| 文件 | `nginx/khub-docker.conf` |
| 位置 | 全文 |
| CVSS 3.1 | 5.3 (AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:L) |

**描述**: Nginx 配置中未启用 `limit_req_zone` 或 `limit_conn_zone`，攻击者可以高速率发起请求。健康检查端点 `/health` 对外可见且无保护，可被用于 DDoS 放大。

**风险**:
- API 端点可被精准字典攻击
- 资源消耗导致容器 OOM 或 DB 连接耗尽
- `/health` 端点可作为反射放大向量

**建议**:
- 在 `server` 块中增加 `limit_req_zone $binary_remote_addr zone=api:10m rate=30r/m`
- 对 `/health` 端点允许更高限制（如 60r/m），其余 endpoint 使用业务逻辑限流
- 可考虑 Cloudflare / CDN 侧 WAF 限流

---

### M3 — `openssh-client` 带入生产运行时

| 属性 | 值 |
|------|------|
| 文件 | `Dockerfile` |
| 位置 | 第 5 行 |
| CVSS 3.1 | 4.7 (AV:L/AC:H/PR:L/UI:N/S:U/C:H/I:L/A:N) |

**描述**: Dockerfile 中 `apt-get install openssh-client` 将 SSH 客户端引入生产运行时镜像。该项目使用 SSH 做灾备推送（SshReplica），但 SSH 客户端在容器内提供了完整的网络隧道、端口转发、文件传输能力。

**风险**: 若应用层被攻破（如通过未鉴权的 API），攻击者可用 SSH 客户端建立出站隧道，泄露数据或横向移动到内网其他主机。

**建议**:
- 拆分架构：将 SshReplica 灾备功能迁移到独立 sidecar 容器，生产主容器不安装 SSH
- 短期缓解：如果必须保留 SSH，限制容器的 outbound 网络能力（`docker run --network` 或 iptables 规则）

---

### L1 — 入口脚本静默忽略 `chown` 错误

| 属性 | 值 |
|------|------|
| 文件 | `docker-entrypoint.sh` |
| 位置 | 第 5 行 |
| CVSS 3.1 | 3.3 (AV:L/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:L) |

**描述**: `chown -R app:app /data/db /data/library 2>/dev/null || true` 将所有错误（包括权限不足、路径不存在、只读卷）重定向至 `/dev/null` 并不影响执行。当使用只读卷或 `:ro` 挂载时，`chown` 会静默失败，容器启动后 `app` 用户可能因权限不足无法写入数据库或文档。

**风险**: 仅在容器以非预期方式启动时触发（如 `docker run` 手动覆盖卷权限），此时用户无法获得明确错误提示。

**建议**:
- 区分预期失败和非预期失败：可先检查目录是否存在且可写
- 至少将错误输出到 stderr（`chown ... || echo "[WARN] chown failed: $?" >&2`）供日志审查

---

### L2 — 自签名证书缺少生产替换说明

| 属性 | 值 |
|------|------|
| 文件 | `docs/deployment.md` |
| 位置 | 第 67-69 行 |
| CVSS 3.1 | 2.6 (AV:N/AC:H/PR:N/UI:N/S:U/C:N/I:L/A:N) |

**描述**: 部署指南生成自签名证书（`openssl req -x509 ...`）作为首次启动步骤，但未明确提醒用户在**生产环境必须替换为 CA 签发的证书**。生产环境使用自签名证书可能导致：
- 浏览器安全警告（用户跳过警告后暴露于中间人攻击）
- 网络设备/代理无法验证链路真实性

**建议**: 在自签名证书生成步骤后添加提示文字：

> **⚠️ 生产环境注意事项**
> 上述命令生成的是自签名证书，仅供开发和内部测试使用。
> 面向公网的生产部署请替换为 Let's Encrypt 等 CA 签发的证书。
> 可参考 [certbot](https://certbot.eff.org/) 获取免费可信证书。

---

### L3 — 环境变量传递密钥不符合 Docker Secrets 最佳实践

| 属性 | 值 |
|------|------|
| 文件 | `docker-compose.yml` |
| 位置 | 第 26-27 行（注释） |
| CVSS 3.1 | 3.1 (AV:L/AC:L/PR:L/UI:N/S:U/C:L/I:N/A:N) |

**描述**: 文档中 PII 密钥和 API Key 通过环境变量传递（`KHUB_PII_KEY`、`KHUB_EMBED_API_KEY` 等）。环境变量可以通过 `docker inspect`、`docker exec env`、`/proc` 文件系统被具有宿主机访问权限的其他进程读取。

**风险**: 宿主机多租户或共享 CI 环境中，密钥可能泄露。

**建议**:
- 使用 Docker Compose v3 `secrets` 替代环境变量（将密钥写入文件，容器内挂载为文件）
- 应用代码中已支持 `KHUB_PII_KEY_FILE` 方式，应作为主要推荐方法

---

### L4 — Nginx 未设置 Referrer-Policy 标头

| 属性 | 值 |
|------|------|
| 文件 | `nginx/khub-docker.conf` |
| 位置 | 第 13-52 行 |
| CVSS 3.1 | 1.0 (AV:N/AC:H/PR:N/UI:R/S:U/C:N/I:N/A:N) |

**描述**: Nginx 响应头中缺少 `Referrer-Policy`。当前浏览器在跨站请求时默认发送完整 Referer URL，可能将 kHUB 的 URL 结构暴露给外部站点。

**风险**: 低——需要用户点击链接离开 kHUB 页面才可能泄露。kHUB 是内部工具，外链场景有限。

**建议**: 添加 `add_header Referrer-Policy "strict-origin-when-cross-origin" always;`

---

### I1 — X-XSS-Protection 已在现代浏览器中弃用

| 属性 | 值 |
|------|------|
| 文件 | `nginx/khub-docker.conf` |
| 位置 | 第 24 行 |
| 类型 | 信息性 |

**说明**: `add_header X-XSS-Protection "1; mode=block"` 在 Chrome 中已于 2019 年移除（Chrome 78+），Firefox 从未实现。该标头对现代浏览器无实际效果，但作为过时代码残留没有安全危害。

**建议**: 可移除以简化配置，核心 XSS 防护已由 CSP 标头覆盖。

---

## 安全基准对照

| 基准项目 | Dockerfile | entrypoint | compose.yml | nginx.conf | 状态 |
|----------|-----------|------------|-------------|------------|------|
| 非 root 用户运行 | ✅ adduser app:app | ✅ su app | — | — | 合格 |
| HEALTHCHECK | ✅ | — | ✅ | — | 合格 |
| 资源限制 | — | — | ✅ mem/cpu | — | 合格 |
| 只读根文件系统 | ❌ 未配置 | — | — | — | 建议强化 |
| `--cap-drop=ALL` | ❌ 未配置 | — | ❌ 未配置 | — | 建议强化 |
| Docker 密钥 | — | — | ❌ 仅环境变量 | — | 建议强化 |
| 镜像漏洞扫描 | ❌ 未集成 | — | — | — | 建议引入 |
| HSTS | — | — | — | ✅ | 合格 |
| CSP | — | — | — | ⚠️ unsafe-inline | 见 M1 |
| 限流 | — | — | — | ❌ 未配置 | 见 M2 |
| 日志审计 | — | — | — | ✅ stdout/stderr | 合格 |

---

## 总结

整体 Docker 部署配置安全基础扎实：
- 使用 dumb-init 正确处理信号
- 非 root 用户运行、资源限制、健康检查、安全标头体系完备
- `.dockerignore` 正确排除了 `.git`、`ssl/`、`docs/` 等敏感目录
- PII 加密默认启用

主要改进方向集中在**生产加固**：
1. **API 鉴权（H1）** —— 是当前最大的攻击面，开放 API 无任何认证
2. **CSP 收紧（M1）** —— 需与前端协作移除 `'unsafe-inline'`
3. **限流保护（M2）** —— Nginx 层低成本可加
4. **SSH 客户端剥离（M3）** —— 属于架构性决策，建议纳入 roadmap

---

*评审人: security-bot / auto-agent*
*模板: OWASP Docker Security Cheat Sheet + CIS Docker Benchmark v1.6*
