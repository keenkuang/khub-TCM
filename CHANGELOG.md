# 变更日志

## [0.2.1] — 2026-07-09

### 修复（M1 代码评审）

#### 核心存储 / 并发
- `Store` 连接改为 `check_same_thread=False` + `isolation_level=None`，并用 `threading.RLock` 串行化所有写操作，修复 REST 服务（`ThreadingHTTPServer`）跨线程共享连接导致的 `ProgrammingError` 与并发写入损坏风险。
- 修复 `sqlite3.connect` 误用未展开的 `path`（曾导致 `~/x.db` 落到工作目录而非家目录的数据丢失隐患）。
- 修复 `transaction()` 与隐式事务冲突（显式 `BEGIN` + `isolation_level=None`，并修正 `replay_from` 缺失的 `BEGIN`，恢复回放中途异常整体 rollback）。
- 删除 `Store.search` 被新版分页 `search` 覆盖而产生的死代码，并保留 `search_old` 作为兼容薄封装（委托给新版 `search`）。
- 快照（`make_snapshot_db`）排除复制记账表 `replication_log` / `lsn_seq` / `ha_state`，避免恢复库复用主库 lsn 序列器与角色/锁状态，升主后产生重复/错乱 lsn。

#### 安全
- REST 鉴权从「仅写操作」扩展为「设置 `KHUB_API_TOKEN` 后所有端点（含读）均需 Bearer 令牌」，避免本地任意进程裸读病历/问诊 PII。
- ANN 向量表名由 `model` 经白名单（`[A-Za-z0-9_]`）校验，防建/删表 SQL 注入。
- 定时调度命令由 `shell=True` 改为 `shell=False`（`shlex` 拆词），防命令注入。
- PII Fernet 密钥在加载时即校验格式，非法密钥给出明确错误而非在写入时崩溃。
- 检索 `/search`、`/semantic` 的 `page`/`k` 参数非法时安全回退默认，避免 500。

#### 子系统正确性
- 考题生成：提示并要求模型以 JSON/标签格式返回，解析出题干/选项/答案/解析；无模型时退回占位题干。
- 考题判分：用户答错且配置 LLM 时真正调用 provider 复核，而非返回死逻辑。
- `cosine` 相似度对不等长向量显式校验，避免 `zip` 静默截断导致错误结果。
- `watch` 文件读取改用 `with open`，修复文件句柄泄露。

### 文档同步
- `pyproject.toml` 版本 0.1.0 → 0.2.1，并补 `khub.ha` 子包（此前漏装）；`khub/__init__.py` 版本同步。
- `systemd/khub.service`：将模板占位 `{{KHUB_BIN}}` 替换为实际可执行文件路径并说明渲染方式。
- `README.md`：CLI/REST 补全 `query`、`dr *`、`ha *`、`feishu-sync`、`ima-*` 等命令与 `/health`、`/stats`、`/documents/{cid}`、`/web/*` 端点；测试数 31 → 182；安全章节补充鉴权/注入防护。
- `docs/config.md`：新增 `KHUB_API_TOKEN`/`KHUB_PII_KEY_FILE`/`KHUB_EMBED_MODEL`/`IMA_*` 等环境变量；澄清核心**不读取**全局 `config.yaml`（仅调度器用 `tasks.yaml`）。
- `docs/api.md`：补充 `GET /documents/{cid}` 与 `/web/*` 端点，版本号同步。
- `docs/architecture.md`：模块表补齐 `sync_engine`/`crypto`/`audit`/`replication`/`ha`/`scheduler`/`watch`/`normalizer`/数据源适配器等；扩展点标记 ANN/加密/真实模型为「已实现」并补充并发安全说明。

### 测试
- 182 个测试全部通过（`tests/` 目录，2 个跳过），端到端覆盖全链路。

---

## [0.2.0] — 2026-07-07

### 新增

#### P0 — KZOCR 入库收尾
- `/documents` REST 端点支持 OCR 文档直接入库，配套 `doc-add` CLI 子命令
- 短查询自动降级为 SQL `LIKE` 回退，确保无向量索引时仍可检索
- 端到端验证链路：OCR 识别 → 入库 → 查询

#### P1 — 入库向量化与 Web UI
- 入库存档文件自动完成文本提取与向量化（FTS5 + 向量双索引）
- 轻量 Web UI：`GET /` 控制台、`GET /documents` 文档浏览、`GET /conflicts` 冲突管理
- `khub watch` 命令监听目录，新文件自动入库

#### P2 — 向量检索升级
- `sqlite-vec` ANN 近似最近邻检索，替代暴力全量比对
- `RemoteEmbedder` 支持挂载真实嵌入模型（通过 HTTP API）
- `GET /semantic` 语义检索端点，WebUI 新增语义检索按钮

#### P3 — 真实 LLM 驱动
- `RemoteLLMProvider` 兼容 OpenAI `/v1/chat/completions` 接口
- `get_provider()` 默认返回远程真实模型（环境变量配置）
- 孪生摘要生成、考题生成默认由真实 LLM 驱动，带本地模板兜底

#### P4 — 安全与灾备
- PII 敏感字段 Fernet 对称加密落盘（患者/病历/问诊记录）
- 访问审计日志：记录每次 PII 读取操作的 `actor + action + timestamp`
- 灾备/热备规划接口：`ReplicationManager` + `WALLog` 变更日志 + `LocalFileReplica` 本地文件副本推送

#### P5 — 真实数据源接入
- Quip 归档文档导入（`khub quip ingest`）
- Obsidian Vault 导入（`khub obsidian import`）
- 定时调度器：YAML 任务定义、后台循环触发、异常隔离
- CLI 子命令：`quip`、`obsidian`、`scheduler`

#### M5 桌面 GUI
- Electron 桌面套壳：`desktop/main.js` + `package.json` + `run.sh`
- `khub desktop` CLI 命令支持浏览器模式和 Electron 原生窗口模式

### 测试
- 182 个测试全部通过（`tests/` 目录）
- 端到端集成测试覆盖全链路：患者→病历→问诊→孪生→电子书→KZOCR→检索→PII 加密→审计
- 整体行覆盖率 73%，核心模块 >85%

---

## [0.1.0] — 2026-07-07

### 新增

#### 设计与规划
- khub knowledge-hub 设计方案：架构、模块划分、数据流
- UI 分层设计：CLI / Web / GUI
- M1 实现计划（khub + writing-plans 双视角）
- 技术路线图扩展：EMR / 问诊模块
- 角色交互模型：医生 / 护士 / 规培生 / 前台 / 保安 / 患者 / 家属

#### 核心存储（M1）
- SQLite + FTS5 版本化存储引擎：文档多版本管理、全文检索
- `khub` 包结构：模块化分层（db / models / storage / api / cli）
- 数据库初始化 schema 与迁移
- 文档存储自动化测试

#### 电子书入库（M2）
- 受管库系统：注册、元数据管理、列表查询
- 文件存储层：归档复制、哈希去重、源文件移动
- EPUB 正文抽取与元数据解析
- 电子书封面提取（EPUB 完整支持，PDF best-effort）
- 未知格式优雅拒绝

#### 检索（M3）
- 离线 `LocalEmbedder`：确定性输出、L2 归一化向量
- 暴力向量检索：存储向量并返回最近邻
- 索引时读取电子书版本内容

#### 考试子系统（M5）
- 题目 CRUD（创建、查询、更新、删除）
- LLM 题目生成桩（`LLMProvider` 抽象接口）
- 自动判分（精确匹配）

#### 孪生子系统（M6）
- 患者管理（CRUD）
- 病历记录
- 问诊记录
- 孪生摘要生成与持久化

#### 门诊运营（M7）
- 排班管理
- 预约管理
- 就诊记录
- 运营流程端到端 CRUD

#### API 与 CLI
- REST API 挂载：注册 / 入库 / 检索 / 考试 / 孪生 / 运营
- CLI 命令封装：`khub` 命令行工具
- 健康检查端点

#### 基础架构
- 项目 README、架构文档、测试策略
- 打包脚本与构建系统
- LLMProvider 抽象：`NoopProvider` / `FakeProvider` / 注册机制
- 安全默认值

### 变更
- 初始版本，无前置变更

### 修复
- 初始版本，无前置修复
