# 变更日志

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
- 97 个测试全部通过（`tests/` 目录）
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
