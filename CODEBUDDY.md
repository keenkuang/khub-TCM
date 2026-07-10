# CODEBUDDY.md

This file provides guidance to CodeBuddy Code when working with code in this repository.

## 项目概览

khub 是一个「个人知识中枢」，当前主体能力是 **PDF/EPUB 电子书管理 + 全文/向量检索**，并搭建了三个业务骨架（中医考试、患者数字孪生、门诊运营）以及一个双机热备/灾备层。所有上层系统共用同一套地基（`documents` / `document_versions` / `embeddings` / `docs_fts` / `LLMProvider` / 受管库目录），业务模块只新增独立表，不改动核心表。

核心设计原则（贯穿全代码，改代码前先读 `docs/architecture.md` §1）：
1. **二进制不进 SQLite**：原文件存受管库目录（按 sha256 分桶），DB 只存元数据/文本/索引/向量。
2. **核心表稳定，业务模块只加表**。
3. **业务逻辑与传输层解耦**：核心是可导入的 Python 库；`cli.py` 与 `api.py` 都只是消费者。
4. **LLM 抽象、延迟绑定**：所有智能能力走 `LLMProvider` 接口，离线用 `NoOpProvider` 兜底。
5. **默认安全**：API 绑 localhost；PII 模块启用加密落盘 + 审计。

## 常用命令

```bash
# 安装（含测试依赖用 dev；pdf/ann/crypto 为可选能力）
pip install -e .
pip install -e ".[dev,pdf,ann,crypto]"   # dev=pytest, pdf=pypdf, ann=sqlite-vec, crypto=cryptography

# 跑全部测试（仓库根运行；pyproject 已设 pythonpath=["."]，直接用 khub.* 导入）
python3 -m pytest -q
# 仅跑单个测试文件
python3 -m pytest tests/test_db.py -q
# 跑单个测试函数
python3 -m pytest tests/test_db.py::test_store_document_creates_tables -q
# 按关键字筛选
python3 -m pytest -k "ebook" -q

# 覆盖率（需先装 pytest-cov：pip install pytest-cov）
python3 -m pytest --cov=khub -q

# 进入 Python 交互验证核心库
python3 -c "from khub.db import Store; s=Store(':memory:'); print(s)"
```

> ⚠️ 测试数量：当前实际 **502** 个用例（smoke 253 / full+slow+net 249）。

### pytest marker 分类（已注册并标注于各测试文件）

`pyproject.toml` 已注册 `smoke` / `full` / `slow` / `net` 四个 marker，并打在测试文件顶部的 `pytestmark` 上：

- `net`（26 个）：走外部服务代码路径的用例——`test_llm_provider`(RemoteLLMProvider)、`test_quip`、`test_obsidian`、`test_ima*`、以及 `test_retrieval_ann`(RemoteEmbedder)。即使这些用例用 fake `urlopen` / 本地文件 mock 掉网络，数据源适配器仍统一归 `net` 以便离线跳过。
- `slow`（74 个）：重 IO/索引/向量/灾备演练/容器校验——入库建索引（`test_ingest_ebook`）、向量重建（`test_retrieval`）、复制（`test_replication`）、双机演练（`test_ha_drill`）、端到端（`test_integration_e2e`）、Docker 校验（`test_docker_*`）、以及 `test_retrieval_ann`。
- `full`（10 个）：长耗时套件子集——`test_ingest_ebook` / `test_ha_drill` / `test_integration_e2e`（同时带 `slow`）。
- `smoke`（187 个）：无重 IO/索引的核心快速单测（其余所有文件）。

常用组合：`pytest -m smoke`（快速）、`pytest -m "not net and not slow"`（等价 smoke）、`pytest -m net`、`pytest -m slow`。

## 启动与运行

```bash
export KHUB_DB=~/.khub/khub.db
export KHUB_LIBRARY=~/.khub/library
khub serve --port 8000          # REST API（默认 127.0.0.1），Web UI 在 /
khub <subcommand> --help        # 全部子命令见 README「CLI 用法」一节
```

整个 CLI 是单一入口 `khub = "khub.cli:main"`（`pyproject.toml`），所有子命令在 `khub/cli.py` 的 `build_parser()` 中用 argparse 注册。`dr`（灾备）、`ha`（高可用）、`schedule`、`desktop`、各数据源 sync 等都在同一个 parser 里。

## 高层架构（需跨文件理解的「大图」）

请求/数据流分层（自上而下）：

```
cli.py  ──┐
          ├──► 核心库（可独立 import 的 Python 模块）
api.py  ──┘        │
                   ├─ ingest.py        编排：register_ebook(仅登记) / ingest_ebook(抽文本+索引)
                   ├─ storage.ManagedLibrary   受管库：hash 分桶落盘、去重、move/copy
                   ├─ extractors/        pdf.py / epub.py：parse_meta + extract_text
                   ├─ db.Store           SQLite + FTS5(trigram) + 版本化，所有读写入口
                   ├─ retrieval          LocalEmbedder(离线) / Retriever(暴力余弦)
                   │                      + ANN(sqlite-vec 虚表；KHUB_DISABLE_ANN=1 退回暴力)
                   ├─ llm/               LLMProvider 抽象；NoOpProvider / RemoteLLMProvider
                   └─ 业务模块：exam / clinical / ops（各自独立表，不碰核心表）
数据源适配器（push-in/pull）：quip / obsidian / ima / ima_notes / sync_engine / watch
运维/可靠性：replication.py + ha/（双机热备、WAL、快照、SSH/S3 副本）
安全：crypto.PIICipher(Fernet) + audit（PII 读取审计）
```

关键跨文件机制（改之前务必理解）：

- **入库两阶段**：`register_ebook` 只把原文件存进受管库 + 写 `ebook_meta`/`files`（不抽文本）；`ingest_ebook` 才抽正文、建 FTS、向量化写入 `embeddings`。CLI 的 `add` 是 register，`ingest` 是 ingest。数据源（Quip/Obsidian/IMA/KZOCR）走 `documents` 表直接 `store_document`，等价于「已入库」。
- **版本化文档模型**：`documents`(canonical) → `document_versions`(多版本) → `attachments`。`models.py` 的 `CanonicalDoc`/`RawDoc`/`Attachment`/`SyncResult` 是跨层传递的容器；`normalizer.normalize` 把各源格式归一为 `RawDoc`。
- **LLM 延迟绑定**：任何「智能」功能（twin 摘要、考题生成、semantic 检索）都只依赖 `llm.get_provider()` 返回的 `LLMProvider`。设 `KHUB_LLM_URL` 即走真实模型，否则 `NoOpProvider` 返回占位/模板。**新增智能能力时务必走这个接口，不要硬依赖某个实现**。
- **向量检索双实现**：默认离线 `LocalEmbedder`（n-gram 特征）；设 `KHUB_EMBEDDING_URL` 走 `RemoteEmbedder`（OpenAI 风格 `/v1/embeddings`）。`embeddings.model` 字段用作 sqlite-vec 虚表名，经白名单 `[A-Za-z0-9_]` 校验防注入——改表名拼接逻辑时不能绕过该白名单。
- **PII 安全开关**：`clinical` 的患者/病历/问诊涉及 PII。`crypto.PIICipher` 默认透传（不加密），设 `KHUB_PII_ENCRYPT=1` + `KHUB_PII_KEY`(或 `KHUB_PII_KEY_FILE`) 才加密落盘；每次 PII 读取经 `audit.record_access` 留痕。测试默认走透传，加密路径用 `monkeypatch.setenv` 局部开启。
- **REST API 鉴权**：设 `KHUB_API_TOKEN` 后**所有**端点（含 GET）都要 `Authorization: Bearer`。API 层是「薄层」（`khub/api.py`，标准库 `http.server`，零依赖），不应承载业务逻辑。
- **并发模型**：单 `Store` 连接跨线程（`ThreadingHTTPServer`）访问，以 `check_same_thread=False` + `threading.RLock` 串行化写。不要在别处再开一个共享连接写同一个 DB。

## 测试约定（写/改测试时遵守）

- 模块级测试用 `Store(":memory:")` 内存库，不落盘；每个测试自建实例避免状态泄漏。
- 零网络：外部请求必须 mock（`test_quip` 用 `MockResponse`、`test_llm_provider` 用 fake `urlopen`）。
- 中文检索：trigram 处理中文，3+ 字符走 FTS `MATCH`，<3 字符自动 `LIKE` 回退。
- 测试独立、异常隔离：单个函数测试；错误（入库失败/网络不通）不打断主流程，仅 warning。

## 重要文档索引

- `docs/architecture.md` — 数据模型与模块职责（改架构前必读）
- `docs/testing.md` — 测试策略（注意其中 marker/bandit/mypy 部分已过时，见上）
- `docs/config.md` — 全部环境变量（`KHUB_DB` / `KHUB_LIBRARY` / `KHUB_LLM_URL` / `KHUB_PII_ENCRYPT` 等）
- `docs/deployment.md` / `docker-compose.yml` — 部署与 Docker（nginx 反代 + HTTPS，PII 加密默认开）
- `docs/disaster_recovery.md` + `docs/ha_dr/` — 双机热备/灾备（`khub dr` / `khub ha`）
- `docs/roles.md` — 交互角色模型（医生/护士/前台/患者等）
