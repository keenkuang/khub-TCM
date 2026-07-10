# khub 架构与数据模型

> 版本：v0.9.4 ｜ 更新：2026-07-10

## 1. 设计原则

1. **二进制不进 SQLite**：原文件存受管库目录（按 sha256 分桶），DB 只存元数据/文本/索引/向量。DB 保持小巧，备份 = 复制整个 `~/.khub/`。
2. **核心表稳定，业务模块只加表**：`documents` / `document_versions` / `attachments` / `sync_states` / `embeddings` / `docs_fts` / `files` / `ebook_meta` 是地基；临床/运营/课程/公众号/社区等均新增独立表，不改动核心。
3. **业务逻辑与传输层解耦**：核心是可导入的 Python 库；CLI 与 REST API 都是消费者，可随意叠加。
4. **LLM 抽象、延迟绑定**：所有智能能力走 `LLMProvider` 接口；`NoOpProvider` 离线兜底，设 `KHUB_LLM_URL` 即切换真实模型。
5. **默认安全**：API 绑 localhost；PII 模块启用加密落盘 + 审计；可设 `KHUB_API_TOKEN` 强制所有请求鉴权。

## 2. 模块与职责

### 基础层
| 模块 | 职责 | 关键接口 |
|------|------|----------|
| `db.Store` | SQLite + FTS5(trigram) + 版本化、文件/元数据登记、检索、索引管理、慢查询日志 | `store_document`, `search`, `_exec` |
| `storage.ManagedLibrary` | 受管库目录：sha256 落盘、去重、move/copy | `store`, `path_for_hash` |
| `models` | 数据模型 `CanonicalDoc` / `RawDoc` / `Attachment` / `SyncResult` | — |
| `crypto` | PII Fernet 对称加密落盘 | `enc`, `dec`, `get_cipher`, `PIICipher` |
| `audit` | PII 读取访问审计 | `record`, `search_audit` |
| `cache` | TTL 内存缓存（5 秒默认） | `get`, `set`, `clear`, `invalidate` |
| `auth` | 用户鉴权 + RBAC + 数据隔离 | `get_current_user`, `check_permission`, `scope_filter`, `PERMISSIONS` |
| `i18n` | 国际化翻译引擎 | `t`, `detect_lang`, `get_translations` |
| `color` | CLI 彩色输出（ANSI） | `C.green`, `C.red`, `C.ok` |

### 文档与检索
| 模块 | 职责 | 关键接口 |
|------|------|----------|
| `extractors` | PDF/EPUB 元数据与正文抽取 | `parse_meta`, `extract_text` |
| `ingest` | 编排入库流程 | `register_ebook`, `ingest_ebook` |
| `retrieval` | 离线嵌入 + ANN 余弦检索 + 暴力回退 | `LocalEmbedder`, `RemoteEmbedder`, `Retriever.search_similar` |
| `search2` | 统一搜索（跨 6 实体类型） | `unified_search` |
| `sync2` | 离线同步引擎（变更日志 + push/pull + 冲突检测） | `push`, `pull`, `record_change`, `status` |
| `normalizer` | 源文档→规范文档归一化 | `detect_format`, `auto_decode` |

### AI 与智能
| 模块 | 职责 | 关键接口 |
|------|------|----------|
| `llm` | LLMProvider 抽象层 | `LLMProvider`, `get_provider`, `NoOpProvider`, `RemoteLLMProvider` |
| `llm.rag` | RAG 检索增强生成引擎 | `RAGEngine.ask`, `ask_stream`, `search_context` |
| `copilot` | AI Copilot 智能助手（意图识别 + 工具注册表 + 执行引擎） | `process`, `intents.parse`, `tools.call_tool` |
| `agents` | Agent 定义 CRUD + 执行引擎（工具链 + LLM 驱动） | `create_agent`, `run`, `run_with_llm` |
| `analytics` | 数据分析（患者分群 / 疗效分析 / 就诊预测 / 预约趋势） | `patient_cohorts`, `syndrome_efficacy`, `visit_forecast` |
| `knowledge` | 中医知识图谱（5 表 + 推理引擎 + 种子数据） | `inference.infer`, `herbs.search_herbs`, `formulas.formula_similarity` |
| `workflow` | 工作流引擎（状态机、3 步骤类型、事件触发） | `engine.run`, `triggers.on_event` |

### 业务模块
| 模块 | 职责 | 关键接口 |
|------|------|----------|
| `clinical` | 临床孪生：患者/病历/问诊/增量摘要/时间线/辨证脉络/AI辨证/疗效追踪 | `twin.build_summary`, `twin_v2.*`, `consult_chat.chat`, `diagnosis.suggest_formula`, `tracking.evaluate_efficacy` |
| `ops` | 门诊运营：排班/预约/就诊/随访 | `add_schedule`, `book_appointment`, `checkin_visit`, `cancel_appointment` |
| `course` | 课程运营：课程/课时/学员报名/成绩 | `add_course`, `enroll_student`, `record_grade` |
| `exam` | 中医考试：题库 CRUD | `add_question`, `generate`, `grade` |
| `wechat` | 微信公众号：文章/排期/粉丝 | `add_article`, `scan_due_schedules`, `sync_followers` |
| `community` | 知识社区：文章/评论/标签 | `articles.create_article`, `comments.add_comment` |
| `telemedicine` | 远程医疗：视频信令/电子处方 | `signaling.create_room`, `prescriptions.create_prescription` |

### 平台与集成
| 模块 | 职责 | 关键接口 |
|------|------|----------|
| `api` | REST API（std lib http.server, SSE, CORS） | `App.dispatch`, `serve` |
| `cli` | CLI 入口（argparse, 150+ 子命令, 彩色输出） | `main`, `build_parser` |
| `plugins` | 插件系统（基类 + 注册表 + 自动发现） | `PluginBase`, `registry.discover`, `intercept_request` |
| `webhook` | Webhook 事件推送（6 事件类型 + HMAC 签名） | `trigger`, `subscribe` |
| `notifications` | 通知系统（CRUD + SSE 推送） | `create`, `list_recent`, `unread_count` |
| `events` | SSE 事件总线（subscribe/broadcast） | `subscribe`, `broadcast` |
| `tenants` | 多租户管理（租户 CRUD + 成员管理） | `create_tenant`, `detect_tenant`, `add_member` |
| `integrations` | 集成中心（企微/钉钉机器人 + 状态检测） | `bot.send_all`, `status.check_all` |
| `reports` | 报表引擎（模板 CRUD + SQL 执行 + CSV 导出） | `execute`, `export_csv` |
| `compliance` | 合规认证检查清单（10 项） | `run_checklist`, `generate_report` |
| `retention` | 数据保留策略（5 表可配置保留天数） | `clean` |

### 运维与部署
| 模块 | 职责 | 关键接口 |
|------|------|----------|
| `replication` / `ha` | 双机热备与远程灾备 | `replay_from`, `ReplicaTarget`, `FailoverController` |
| `scheduler` | 定时调度（YAML 任务 + 后台循环） | `Scheduler`, `run_tasks` |
| `watch` | 目录监听自动入库 | `watch_and_ingest` |
| `openapi` | OpenAPI 3.0 规范生成 | `get_spec` |

### 数据源适配器
| 模块 | 职责 |
|------|------|
| `adapters.feishu` | 飞书文档拉取 |
| `adapters.base` | SourceAdapter Protocol |
| `obsidian` | Obsidian Vault 导入 |
| `quip` | Quip 归档导入 |
| `ima` / `ima_notes` / `ima_probe` | IMA 知识库同步 |
| `importer` | 老问诊系统数据导入（Excel/HTML） |

### 客户端
| 模块 | 职责 |
|------|------|
| `web/` | PWA Web UI（index.html/style.css/script.js + Service Worker） |
| `desktop/` | Electron 桌面壳（托盘/Ollama 检测/系统菜单） |
| `miniapp/` | 微信小程序（登录/预约/孪生/趋势） |

## 3. 数据模型（表）

### 核心表（8 张）
- `documents(canonical_id, title, current_version, source_ids, created_at, updated_at, doc_type, conflict, format, ingested, file_hash)`
- `document_versions(version_id, doc_id, content, format, origin, author, updated_at, hash, parent_version, note)`
- `attachments(id, doc_id, version_id, kind, path, hash)`
- `sync_states(source_id, doc_id, last_sync_at, etag, hash, direction)`
- `embeddings(doc_id, version_id, model, vector BLOB)`
- `docs_fts` — FTS5，`tokenize='trigram'`（中文子串检索）
- `files(sha256 PK, path, size, format, stored_at)`
- `ebook_meta(canonical_id, author, isbn, lang, page_count, publisher, published_date, cover_path, toc_json)`

### 业务表（40+ 张）
| 模块 | 表 |
|------|----|
| exam | `questions` |
| clinical | `patients`, `records`, `consultations`, `twin_versions`, `consult_sessions`, `consult_messages`, `record_struct`, `syndrome_vocab`, `followup_plans`, `followup_adherence` |
| ops | `schedules`, `appointments`, `visits` |
| course | `courses`, `lessons`, `enrollments`, `grades` |
| knowledge | `kg_herbs`, `kg_formulas`, `kg_syndromes`, `kg_methods`, `kg_relations` |
| workflow | `workflow_definitions`, `workflow_instances` |
| wechat | `wechat_articles`, `wechat_schedules`, `wechat_followers` |
| webhook | `webhook_subscriptions`, `webhook_deliveries` |
| sync | `sync_changes`, `devices` |
| telemedicine | `telemedicine_sessions`, `prescriptions` |
| community | `community_articles`, `community_comments` |
| agents | `agent_definitions`, `agent_schedules` |
| tenants | `tenants`, `tenant_members` |
| tags | `doc_tags`, `favorites` |
| auth | `users`, `auth_tokens`, `notifications`, `report_templates`, `report_jobs` |

所有业务表均接 `install_triggers` 纳入 WAL 复制。

## 4. 扩展点（全部已实现）

- **真实嵌入 / LLM**：`LLMProvider` + `RemoteLLMProvider`（OpenAI 风格）、`RemoteEmbedder`；`KHUB_LLM_URL` / `KHUB_EMBEDDING_URL` 控制
- **ANN 向量检索**：`sqlite-vec` 虚表，不可用时退回暴力余弦
- **AI Copilot**：8 工具意图识别 + 执行引擎 + LLM 驱动模式
- **Agent 平台**：自定义 Agent + 工具链编排
- **工作流引擎**：auto/condition/notify 步骤 + 事件触发
- **知识图谱推理**：5 张知识库表 + 证型→方剂→中药→归经→禁忌推导
- **统一搜索**：跨文档/患者/课程/中药/方剂/证型 6 实体
- **插件系统**：PluginBase + 自动发现 + 请求拦截
- **Webhook**：6 事件类型 + HMAC 签名 + 异步投递
- **多租户**：`X-Tenant-ID` 头检测 + 租户成员管理
- **国际化**：翻译引擎 + `Accept-Language` 检测 + Web UI 语言切换
- **离线同步**：变更日志 + push/pull + 冲突检测 + PWA Service Worker

## 5. 安全

- 网络：REST 默认 `127.0.0.1`；设 `KHUB_API_TOKEN` 后所有端点需 Bearer 令牌
- 多用户：JWT 登录 + RBAC（8 角色 × 12 类资源）+ 数据隔离（`scope_filter`）
- 注入：所有 SQL 参数化；ANN 表名白名单；静态资源路径校验
- PII：Fernet 加密（`KHUB_PII_ENCRYPT=1`）+ `audit.record` 审计留痕
- 并发：`check_same_thread=False` + `threading.RLock` 串行化写
- 审计：增强审计（details 字段）+ search_audit + 索引
- 数据保留：5 表可配置保留天数（`KHUB_RETENTION_*`）
- 合规：10 项检查清单 + 合规评分报告

> 完整的环境变量列表见 `docs/config.md`，部署说明见 `docs/deployment.md`，角色模型见 `docs/roles.md`。
