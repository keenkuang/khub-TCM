# khub 生产部署指南

**版本**: 0.2.6

---

## 运行环境

- **Python**: 3.11+
- **数据库**: SQLite3（需 FTS5 支持，Ubuntu 22.04+ 内置）
- **操作系统**: 推荐 Linux (Ubuntu 22.04+)
- **容器**: Docker 25+ / Docker Compose v2+

---

## 功能概览（v0.2.4）

| 功能 | 说明 |
|------|------|
| 电子书管理 | PDF/EPUB 入库、元数据、全文检索 |
| 语义检索 | 向量近似检索（sqlite-vec）、离线和真实模型 |
| REST API | 标准库实现，零依赖 |
| Web UI | 文档浏览、检索、冲突解决、编辑、深色模式 |
| 数据看板 | 统计卡片、来源分布条形图、近 7 天入库折线图 |
| **RAG 问答** | 向量检索 + LLM 上下文组装 + 流式 SSE 输出 |
| 数据源同步 | 飞书知识空间、Quip、Obsidian、IMA 文档拉取 |
| 灾备/热备 | WAL 触发器 + 快照 + SSH/S3 副本 + 端到端演练 |
| PII 加密 | Fernet 对称加密 + 访问审计 |
| LLM 接入 | OpenAI 风格 API 接口，设 `KHUB_LLM_URL` 即启用 |

---

## 部署方式

### 方式 A：pip 安装（推荐）

```bash
# 1. 安装
git clone https://github.com/keenkuang/khub-TCM.git
cd khub-TCM
pip install -e ".[pdf,ann]"

# 2. 启动
export KHUB_DB=~/.khub/khub.db
khub serve

# 3. 打开浏览器访问 http://127.0.0.1:8765
```

### 方式 B：Docker 单容器

```bash
docker run -d --name khub \
  -v khub-db:/data/db -v khub-library:/data/library \
  -p 8765:8765 \
  -e KHUB_DB=/data/db/khub.db \
  -e KHUB_LIBRARY=/data/library \
  ghcr.io/keenkuang/khub-tcm:latest
```

### 方式 C：Docker Compose（推荐生产）

```bash
# 1. 生成自签名证书（首次）
cd khub-m1
mkdir -p ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ssl/khub.key -out ssl/khub.crt \
  -subj "/CN=khub.local"

# 2. 启动全套服务（khub + nginx + HTTPS）
docker compose up -d

# 3. 访问 https://localhost
```

包含：nginx 反代（自动 HTTPS）、自签名证书、资源限制、健康检查。

---

## 配置

### 核心环境变量

完整变量列表见 [`docs/config.md`](config.md)。核心变量：

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `KHUB_DB` | SQLite 数据库路径 | `~/.khub/khub.db` |
| `KHUB_LIBRARY` | 受管库目录 | `~/.khub/library` |
| `KHUB_LOG_LEVEL` | 日志级别 | `INFO` |
| `KHUB_WAL_KEEP` | 保留最近 N 条已推送 WAL | 保留全量 |
| `KHUB_WAL_KEEP_DAYS` | 保留最近 D 天内的已推送 WAL | 保留全量 |
| `KHUB_API_TOKEN` | REST API 鉴权令牌 | 空（不鉴权） |
| `KHUB_PII_ENCRYPT` | PII 加密开关 | 空（关闭） |
| `KHUB_LLM_URL` | LLM 服务 URL（OpenAI 风格） | 空（离线模式） |
| `KHUB_EMBEDDING_URL` | 向量嵌入服务 URL | 空（本地 n-gram） |

### 数据目录

- 数据库：`~/.khub/khub.db`（默认）
- 文档存储：`~/.khub/library/`（sha256 分桶）

---

## 安全

### 内置安全措施

| 措施 | 说明 |
|------|------|
| CSP | 限于 `self` 加载脚本/样式，防 XSS |
| X-Content-Type-Options | 防 MIME 嗅探 |
| X-Frame-Options | 防点击劫持 |
| HSTS | 强制 HTTPS（nginx 层配置） |
| API 鉴权 | 可选 Bearer 令牌（`KHUB_API_TOKEN`） |
| PII 加密 | Fernet 对称加密 + 访问审计 |
| 请求体上限 | 10MB（含负值 Content-Length 防护） |
| 静态文件鉴权 | 路径穿越已防护 |

### 生产建议

- REST API 默认绑定 `127.0.0.1`，通过 nginx 反代暴露
- 设置 `KHUB_API_TOKEN` 避免本地任意进程裸读 PII
- PII 加密默认关闭，生产环境建议启用
- 定期执行 `khub dr push` 将快照推送到异地（SSH/S3）

---

## 升级

```bash
cd /home/keen/khub-m1
git pull
pip install -e .
sudo systemctl restart khub
```

Docker 部署：

```bash
docker compose pull
docker compose up -d
```

---

## 备份与恢复

```bash
# 本地快照
khub dr init
khub dr push

# 远程灾备（SSH）
khub dr push --target ssh://user@nas/backups/khub

# 恢复
khub dr restore --to latest --target /data/db/restored.db
```

详细灾备操作见 [`docs/disaster_recovery.md`](disaster_recovery.md) 和 [`docs/ha_dr/`](ha_dr/)。
