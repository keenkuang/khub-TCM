# khub 配置参考

**版本**: 0.2.0

---

## 环境变量

以下环境变量可用于配置 khub 行为。变量可通过 `export VAR=value` 设置，或写入 systemd service 的 `Environment=` 字段。

| 变量 | 用途 | 默认值 | 示例 |
|------|------|--------|------|
| `KHUB_DB` | SQLite 数据库文件路径 | `~/.khub/khub.db` | `/data/khub/khub.db` |
| `KHUB_LIBRARY` | 受管库目录（文档存储位置） | `~/.khub/library` | `/data/khub/library` |
| `KHUB_LOG_LEVEL` | 日志级别 | `INFO` | `DEBUG` |
| `KHUB_LOG_FILE` | 日志文件路径（空表示输出到 stderr） | 空 | `/var/log/khub/khub.log` |
| `KHUB_PII_ENCRYPT` | PII 加密开关（设置后启用） | 空 | `1` |
| `KHUB_PII_KEY` | Fernet 对称加密密钥（base64 编码，44 字符） | 自动生成 | `(base64 44 字符)` |
| `KHUB_EMBEDDING_URL` | 向量嵌入服务 URL | 空 | `http://127.0.0.1:8080` |
| `KHUB_EMBED_DIM` | 嵌入向量维度 | `256` | `768` |
| `KHUB_EMBED_API_KEY` | 嵌入服务鉴权密钥 | 空 | `sk-xxx` |
| `KHUB_LLM_URL` | LLM 服务 URL | 空 | `http://127.0.0.1:8080` |
| `KHUB_LLM_API_KEY` | LLM 服务鉴权密钥 | 空 | `sk-xxx` |
| `KHUB_LLM_MODEL` | LLM 模型名称 | `default` | `gpt-4o-mini` |
| `KHUB_QUIP_TOKEN` | Quip API 访问令牌 | 空 | `(Quip token)` |
| `KHUB_DISABLE_ANN` | 禁用 ANN（近似最近邻）向量索引 | 空 | `1` |

---

## 配置文件

khub 也支持从 `~/.khub/config.yaml` 读取配置。环境变量优先级高于配置文件。

### config.yaml 示例

```yaml
db: ~/.khub/khub.db
library: ~/.khub/library
log_level: INFO
log_file: /var/log/khub/khub.log
pii_encrypt: false
pii_key: ""
embedding_url: ""
embed_dim: 256
embed_api_key: ""
llm_url: ""
llm_api_key: ""
llm_model: default
quip_token: ""
disable_ann: false
```
