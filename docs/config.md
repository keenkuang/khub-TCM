# khub 配置参考

> 版本：v0.9.4 ｜ 更新：2026-07-10

---

## 环境变量

以下环境变量可用于配置 khub 行为。**当前核心配置全部走环境变量**（无全局 `config.yaml` 加载器）。

### 基础
| 变量 | 默认值 | 用途 |
|------|--------|------|
| `KHUB_DB` | `~/.khub/khub.db` | SQLite 数据库文件路径 |
| `KHUB_LIBRARY` | `~/.khub/library` | 受管库目录（文档存储位置） |
| `KHUB_BRAND_NAME` | `kHUB` | 品牌名称（覆盖 Web UI 标题与 API 返回） |
| `KHUB_BRAND_LOGO` | 空 | 品牌 Logo URL（显示在 Web UI 导航栏） |
| `KHUB_ADMIN_PASSWORD` | 自动生成 | admin 用户的初始密码（首次启动时） |
| `KHUB_API_TOKEN` | 空（不鉴权） | REST API 鉴权令牌；设置后所有端点需 `Bearer <token>` |
| `KHUB_HTTPS` | 空 | 设为 `1` 启用 HTTPS 合规检查 |
| `NO_COLOR` | 空 | 设为任意值禁用 CLI 彩色输出 |

### 日志
| 变量 | 默认值 | 用途 |
|------|--------|------|
| `KHUB_LOG_LEVEL` | `INFO` | 日志级别 |
| `KHUB_LOG_FILE` | 空（stderr） | 日志文件路径 |
| `KHUB_LOG_FORMAT` | `json` | 日志格式。`json`=结构化 JSON，`text`=纯文本（本地开发） |
| `KHUB_LOG_ROTATION` | `30` | JSON 日志文件保留天数 |

### LLM / AI
| 变量 | 默认值 | 用途 |
|------|--------|------|
| `KHUB_LLM_URL` | 空 | LLM 服务 URL（OpenAI 风格 `/v1/chat/completions`） |
| `KHUB_LLM_API_KEY` | 空 | LLM 服务鉴权密钥 |
| `KHUB_LLM_MODEL` | `default` | LLM 模型名称 |
| `KHUB_EMBEDDING_URL` | 空 | 向量嵌入服务 URL（OpenAI 风格 `/v1/embeddings`） |
| `KHUB_EMBED_DIM` | `256` | 嵌入向量维度 |
| `KHUB_EMBED_API_KEY` | 空 | 嵌入服务鉴权密钥 |
| `KHUB_EMBED_MODEL` | 空 | 嵌入模型名 |
| `KHUB_DISABLE_ANN` | 空 | 设为 `1` 禁用 ANN 向量索引 |

### 安全与合规
| 变量 | 默认值 | 用途 |
|------|--------|------|
| `KHUB_PII_ENCRYPT` | 空 | 设为 `1` 启用 PII 字段加密落盘 |
| `KHUB_PII_KEY` | 自动生成 | Fernet 对称加密密钥（base64 44 字符） |
| `KHUB_PII_KEY_FILE` | `~/.khub/pii.key` | Fernet 密钥文件路径 |
| `KHUB_TENANT_MODE` | 空 | 设为 `1` 启用多租户模式 |
| `KHUB_RETENTION_AUDIT_LOG` | `365` | 审计日志保留天数 |
| `KHUB_RETENTION_NOTIFICATIONS` | `90` | 通知保留天数 |
| `KHUB_RETENTION_SYNC_CHANGES` | `180` | 同步变更保留天数 |
| `KHUB_RETENTION_WEBHOOK_DELIVERIES` | `30` | Webhook 投递记录保留天数 |
| `KHUB_RETENTION_WORKFLOW_INSTANCES` | `90` | 工作流实例保留天数 |

### 灾备
| 变量 | 默认值 | 用途 |
|------|--------|------|
| `KHUB_WAL_KEEP` | 空（保留全量） | 本地保留最近 N 条已推送 WAL |
| `KHUB_WAL_KEEP_DAYS` | 空（保留全量） | 保留最近 D 天内的已推送 WAL |

### 数据源
| 变量 | 用途 |
|------|------|
| `KHUB_QUIP_TOKEN` | Quip API 访问令牌 |
| `IMA_CLIENT_ID` | IMA 客户端 ID |
| `IMA_API_KEY` | IMA API 密钥 |
| `FEISHU_APP_ID` | 飞书 AppID |
| `FEISHU_APP_SECRET` | 飞书 AppSecret |
| `FEISHU_SPACE_ID` | 飞书知识空间 ID |
| `WECHAT_APPID` | 微信公众号 AppID |
| `WECHAT_SECRET` | 微信公众号 AppSecret |

### 集成
| 变量 | 用途 |
|------|------|
| `WECHAT_WEBHOOK` | 企业微信群机器人 Webhook URL |
| `DINGTALK_WEBHOOK` | 钉钉群机器人 Webhook URL |
| `KHUB_METRICS_ENABLED` | 设为 `1` 启用 `/metrics` Prometheus 端点 |

### CLI
| 变量 | 用途 |
|------|------|
| `KHUB_USER` | `khub whoami` 默认用户名 |
| `KHUB_TOKEN` | CLI 默认鉴权令牌 |

---

## 配置文件

核心 **不读取** 任何全局 `config.yaml`；所有运行参数通过上方环境变量注入。

各子系统有各自独立的配置文件：
- **定时调度**：`khub schedule --config tasks.yaml` 读取 YAML 任务定义
- **Electron 桌面**：`desktop/package.json` — 启动端口通过 `KHUB_PORT` 环境变量配置
