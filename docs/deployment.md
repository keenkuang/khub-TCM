# khub 生产部署指南

> 版本：v1.4.0 ｜ 更新：2026-07-10

---

## 运行环境

- **Python**: 3.11+
- **数据库**: SQLite3（需 FTS5 支持，Ubuntu 22.04+ 内置）
- **操作系统**: 推荐 Linux (Ubuntu 22.04+)
- **容器**: Docker 25+ / Docker Compose v2+
- **K8s**: Helm 3+

---

## 功能概览（v0.9.4）

| 功能 | 说明 |
|------|------|
| 电子书管理 | PDF/EPUB 入库、元数据、全文检索、版本 Diff |
| 语义检索 | 向量近似检索（sqlite-vec）、离线和真实嵌入模型 |
| 统一搜索 | 跨文档/患者/课程/中药/方剂/证型 6 类实体 |
| AI Copilot | 自然语言→意图识别→8 工具执行 + LLM 驱动 |
| AI Agent 平台 | 自定义 Agent 定义 + 工具链编排 + LLM 驱动 |
| 工作流引擎 | 状态机（auto/condition/notify）+ 事件触发 |
| 临床孪生 | 患者/病历/问诊/增量摘要/时间线/辨证脉络/AI 辨证/疗效追踪 |
| 中医知识图谱 | 14 证型 × 50 方剂 × 60 中药，推理引擎（证→法→方→药→归经） |
| 门诊运营 | 排班/预约/就诊/取消/改约/NoShow/随访 |
| 课程运营 | 课程/课时/学员报名/成绩/容量控制 |
| 微信公众号 | 文章素材→定时排期→群发→粉丝同步 |
| 运营看板 | 4 卡片布局（文档/预约/排班利用率） |
| 报表引擎 | 自定义 SQL → 表格/图表 → CSV 导出 |
| 数据分析 | 患者分群/疗效分析/就诊预测/预约趋势 |
| RAG 问答 | 向量检索 + LLM 上下文组装 + 流式 SSE |
| 数据源同步 | 飞书/Quip/Obsidian/IMA 文档拉取 |
| 灾备/热备 | WAL 触发器 + 快照 + SSH/S3 副本 + 端到端演练 |
| PII 加密 | Fernet 对称加密 + 访问审计 |
| 多用户 | JWT 登录 + RBAC（8 角色） + 数据隔离 |
| 多租户 | 租户管理 + X-Tenant-ID 隔离 |
| 远程医疗 | WebRTC 视频信令 + 电子处方 |
| 知识社区 | 文章发布 + 评论 + 标签 |
| 开放平台 | 插件系统 + Webhook（6 事件）+ OpenAPI/Swagger |
| 实时推送 | SSE 通知 + 事件总线 + 企微/钉钉机器人 |
| 国际化 | 翻译引擎 + Accept-Language 检测 + Web UI 语言切换 |
| 离线同步 | 变更日志 + push/pull + 冲突检测 |
| PWA | Service Worker 离线缓存 + manifest |
| Electron 桌面 | 托盘图标 + Ollama 本地模型 + 系统菜单 |
| 微信小程序 | 登录/预约/孪生摘要/健康趋势 |

---

## 部署方式

### 方式 A：一键安装脚本

```bash
curl -fsSL https://raw.githubusercontent.com/keenkuang/khub-TCM/master/install.sh | bash
```

自动完成：OS 检测 → Python 安装 → 创建用户 → pip 安装 → DB 初始化 → systemd 配置。

### 方式 B：pip 安装

```bash
git clone https://github.com/keenkuang/khub-TCM.git
cd khub-TCM
pip install -e ".[all]"
export KHUB_DB=~/.khub/khub.db
khub serve
# 浏览器访问 http://127.0.0.1:8765
```

### 方式 C：Docker 单容器

```bash
docker run -d --name khub \
  -v khub-data:/data \
  -p 8765:8765 \
  -e KHUB_DB=/data/khub.db \
  -e KHUB_LIBRARY=/data/library \
  ghcr.io/keenkuang/khub-tcm:latest
```

### 方式 D：Docker Compose（推荐生产）

```bash
# 生成自签名证书（首次）
mkdir -p ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ssl/khub.key -out ssl/khub.crt \
  -subj "/CN=khub.local"
# 启动全套服务（khub + nginx + HTTPS）
docker compose up -d
```

包含：nginx 反代（自动 HTTPS）、资源限制、健康检查、日志轮转。

### 方式 E：Kubernetes（Helm Chart）

```bash
helm install khub ./helm/khub \
  --set persistence.size=10Gi \
  --set ingress.enabled=true \
  --set ingress.host=khub.example.com
```

---

## 配置

完整变量列表见 [`docs/config.md`](config.md)。核心变量：

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `KHUB_DB` | SQLite 数据库路径 | `~/.khub/khub.db` |
| `KHUB_LIBRARY` | 受管库目录 | `~/.khub/library` |
| `KHUB_LOG_LEVEL` | 日志级别 | `INFO` |
| `KHUB_API_TOKEN` | REST API 鉴权令牌 | 空（不鉴权） |
| `KHUB_PII_ENCRYPT` | PII 加密开关 | 空（关闭） |
| `KHUB_LLM_URL` | LLM 服务 URL | 空（离线模式） |
| `KHUB_EMBEDDING_URL` | 向量嵌入 URL | 空（本地 n-gram） |
| `WECHAT_APPID` | 微信公众号 AppID | — |
| `KHUB_ADMIN_PASSWORD` | admin 初始密码 | 自动生成 |

---

## 安全

| 措施 | 说明 |
|------|------|
| CSP | `self` 加载，防 XSS |
| 多用户鉴权 | JWT + RBAC（8 角色 × 12 资源） |
| API 鉴权 | `KHUB_API_TOKEN` 或 JWT Bearer |
| PII 加密 | Fernet + 审计日志 |
| 请求体上限 | 10MB |
| 数据隔离 | `scope_filter` 按角色限定查询范围 |
| 合规检查 | 10 项清单 + 评分报告 |
| 数据保留 | 5 表可配置保留天数 |
| 灾备 | WAL + 快照 + SSH/S3 远程副本 |

---

## 升级

```bash
# pip 安装
git pull && pip install -e . && sudo systemctl restart khub

# Docker
docker compose pull && docker compose up -d

# Helm
helm upgrade khub ./helm/khub
```

---

## 备份与恢复

```bash
# 配置灾备目标
khub dr init --target file:///backup/khub
# 推送快照 + WAL
khub dr push
# 远程灾备
khub dr push --target ssh://user@nas/backups/khub
# 恢复
khub dr restore --to latest --target /data/db/restored.db
```

详细灾备操作见 [`docs/disaster_recovery.md`](disaster_recovery.md) 和 [`docs/ha_dr/`](ha_dr/)。
