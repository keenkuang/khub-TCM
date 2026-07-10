# khub 配置参考

**版本**: 0.2.4

---

## 环境变量

以下环境变量可用于配置 khub 行为。变量可通过 `export VAR=value` 设置，或写入 systemd service 的 `Environment=` 字段。**当前核心配置全部走环境变量**（无全局 `config.yaml` 加载器）。

| 变量 | 用途 | 默认值 | 示例 |
|------|------|--------|------|
| `KHUB_DB` | SQLite 数据库文件路径 | `~/.khub/khub.db` | `/data/khub/khub.db` |
| `KHUB_LIBRARY` | 受管库目录（文档存储位置） | `~/.khub/library` | `/data/khub/library` |
| `KHUB_LOG_LEVEL` | 日志级别 | `INFO` | `DEBUG` |
| `KHUB_LOG_FILE` | 日志文件路径（空表示输出到 stderr） | 空 | `/var/log/khub/khub.log` |
| `KHUB_LOG_FORMAT` | `json` | 日志格式。`json`=结构化 JSON，`text`=纯文本（本地开发） |
| `KHUB_LOG_ROTATION` | `30` | JSON 日志文件保留天数（配合 TimedRotatingFileHandler） |
| `KHUB_METRICS_ENABLED` | `0` | 设为 `1` 启用 `/metrics` Prometheus 端点 |
| `KHUB_API_TOKEN` | REST API 鉴权令牌；设置后**所有**端点（含读）需 `Bearer <token>` | 空（不鉴权） | `sk-xxx` |
| `KHUB_ADMIN_PASSWORD` | — | 首次启动时 admin 用户的密码。不设则自动生成随机密码并打印到控制台 |
| `KHUB_PII_ENCRYPT` | PII 加密开关（设置后启用） | 空 | `1` |
| `KHUB_PII_KEY` | Fernet 对称加密密钥（base64 编码，44 字符） | 自动生成 | `(base64 44 字符)` |
| `KHUB_PII_KEY_FILE` | Fernet 密钥文件路径（优先于自动生成；推荐方式） | `~/.khub/pii.key` | `/secret/pii.key` |
| `KHUB_EMBEDDING_URL` | 向量嵌入服务 URL（OpenAI 风格 `/v1/embeddings`） | 空 | `http://127.0.0.1:8080` |
| `KHUB_EMBED_DIM` | 嵌入向量维度 | `256` | `768` |
| `KHUB_EMBED_API_KEY` | 嵌入服务鉴权密钥 | 空 | `sk-xxx` |
| `KHUB_EMBED_MODEL` | 嵌入模型名（请求体 `model` 字段） | 空 | `bge-m3` |
| `KHUB_LLM_URL` | LLM 服务 URL（OpenAI 风格 `/v1/chat/completions`） | 空 | `http://127.0.0.1:8080` |
| `KHUB_LLM_API_KEY` | LLM 服务鉴权密钥 | 空 | `sk-xxx` |
| `KHUB_LLM_MODEL` | LLM 模型名称 | `default` | `gpt-4o-mini` |
| `KHUB_QUIP_TOKEN` | Quip API 访问令牌 | 空 | `(Quip token)` |
| `IMA_CLIENT_ID` | IMA 客户端 ID | 空 | `(IMA client id)` |
| `IMA_API_KEY` | IMA API 密钥 | 空 | `(IMA api key)` |
| `KHUB_DISABLE_ANN` | 禁用 ANN（近似最近邻）向量索引 | 空 | `1` |
| `KHUB_WAL_KEEP` | 本地保留最近 N 条已推送 WAL（prune_wal 窗口） | 空（保留全量） | `1000` |
| `KHUB_WAL_KEEP_DAYS` | 保留最近 D 天内的已推送 WAL（优先级低于 KHUB_WAL_KEEP） | 空（保留全量） | `7` |
| `WECHAT_APPID` | — | 微信公众号 AppID（必填） |
| `WECHAT_SECRET` | — | 微信公众号 AppSecret（必填） |

---

## 配置文件

核心 **不读取** 任何全局 `config.yaml`；所有运行参数通过上方环境变量注入（CLI 子命令与 REST 服务均从环境变量读取）。

各子系统有各自独立的配置文件：

- **定时调度**：`khub schedule --config tasks.yaml` 读取 YAML 任务定义（`name` / `command` / `interval`），见 `khub/scheduler.py` 与 `docs/operations.md`。
- **数据源客户端**（IMA / Quip / Obsidian 等）：凭据与路径通过各自环境变量传入，不依赖统一配置文件。
