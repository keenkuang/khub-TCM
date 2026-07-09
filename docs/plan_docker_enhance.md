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

- `python:3.11-slim` → `python:3.12-slim`（对齐本地运行环境）
- 新增 `adduser --system app` + `USER app`（非 root 运行，安全最佳实践）
- COPY 后 `chown -R app:app /app`

### 2.2 .dockerignore 补全

- 补充 `*.md`、`docs/`、`*.pdf`、`*.docx`

### 2.3 docker-compose.yml 增强

- 新增 WAL 保留窗口环境变量：
  - `KHUB_WAL_KEEP=1000`
  - `KHUB_WAL_KEEP_DAYS=7`
- 取消注释 SSH agent 转发的注释示例

### 2.4 docs/deployment.md 重写

- 版本号 0.2.0 → 0.2.4
- 新增 3 个部署方案：pip 安装、Docker 单服务、Docker Compose 全套
- 新增功能说明：RAG 问答 AI 助手、WebUI（编辑/冲突解决/深色模式）、数据看板
- 新增安全头说明（CSP/HSTS/Referrer-Policy）
- 新增 WAL 持久化配置说明

## 三、文件修改清单

| 文件 | 修改类型 | 预估行数 |
|------|----------|----------|
| `Dockerfile` | 修改 | ~5 行 |
| `.dockerignore` | 修改 | ~3 行 |
| `docker-compose.yml` | 修改 | ~5 行 |
| `docs/deployment.md` | 重写 | ~80 行 |
