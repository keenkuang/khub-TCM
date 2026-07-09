# Docker 部署增强方案

> 对现有 Dockerfile / docker-compose / deployment.md 的增强计划
> 2026-07-10

---

## 一、当前状态分析

| 文件 | 现状 | 问题 |
|------|------|------|
| `Dockerfile` | Python 3.11, root 用户运行, 基础依赖 | 无非 root 用户；python 3.12 更优 |
| `.dockerignore` | 已有基础忽略规则 | 缺少 `*.md`、`docs/` 等 |
| `docker-compose.yml` | khub + nginx 双服务, WAL 未配置 | 无 `KHUB_WAL_KEEP` 环境变量 |
| `nginx/khub-docker.conf` | HTTP→HTTPS, 反代, 安全头 | 功能完整 |
| `docs/deployment.md` | 基础安装 + systemd + nginx 示例 | 版本 0.2.0, 缺 RAG/看板/安全头说明 |

## 二、增强方案

### 2.1 Dockerfile 增强

- `python:3.11-slim` → `python:3.12-slim`
- 新增 `adduser --system app` + `USER app`
- COPY 后 `chown -R app:app /app`
- 复制 `docker-entrypoint.sh` 并设为 ENTRYPOINT

### 2.2 新增 docker-entrypoint.sh

入口脚本，在启动前修正卷所有权，再降权运行：

```bash
#!/bin/sh
# 修正运行时挂载卷所有权（首次挂载时归 root）
chown -R app:app /data/db /data/library 2>/dev/null || true
# 以降权用户执行原始命令
exec dumb-init su -s /bin/sh app -c "python -m khub.cli $*"
```

### 2.3 .dockerignore 补全

- 无改动（已存在 docs/ 忽略）

### 2.4 docker-compose.yml 增强

- 新增 WAL 保留窗口环境变量：
  - `KHUB_WAL_KEEP=1000`
  - `KHUB_WAL_KEEP_DAYS=7`
- SSH/PII 路径从 `/root/` 改为 `/home/app/`
- 新增 entrypoint 脚本挂载

### 2.5 nginx/khub-docker.conf 增强

- 新增 CSP 头：`Content-Security-Policy: default-src 'self'`

### 2.6 docs/deployment.md 重写

- 版本号 0.2.0 → 0.2.4
- 新增 Docker Compose 部署说明
- 新增 RAG/看板/WebUI 功能说明
- 新增安全头说明

## 三、文件修改清单

| 文件 | 修改类型 | 预估行数 |
|------|----------|----------|
| `Dockerfile` | 修改 | ~5 行 |
| `.dockerignore` | 修改 | ~3 行 |
| `docker-compose.yml` | 修改 | ~5 行 |
| `docs/deployment.md` | 重写 | ~80 行 |
