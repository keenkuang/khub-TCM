# khub 设计文档：PDF/EPUB 入库与存储 + 未来扩展路线图

> 状态：设计稿（未实现）
> 适用范围：khub 个人知识库。本文件描述电子书入库/存储方案，并预留未来中医考试培训系统的地基。
> 设计原则：二进制不进 SQLite；入库/不入库双模式；扩展模块（LLM、考试）独立分层，不污染核心库表。

---

## 一、PDF/EPUB 入库与存储方案

### 1.1 存储分层

```
受管库目录 library_root/        ← 配置文件指定，例如 ~/.khub/library/
  └─ <sha256前2位>/<sha256>.pdf|.epub
SQLite khub.db                  ← 只存 元数据 + 抽取文本 + 索引 + 向量
```

- 文件按 `sha256` 分桶存放，天然去重：相同文件只落盘一份。
- DB 只记 `path + sha256`，未来 `library_root` 可整体迁到对象存储，上层无感。
- 二进制**绝不**以 BLOB 存入 SQLite（避免 DB 膨胀、备份变慢）。

### 1.2 Schema 调整（基于现有表扩展）

现有表：`documents` / `document_versions` / `attachments` / `sync_states` / `embeddings` / `docs_fts`。

新增/调整：

```sql
-- 原文件登记表（按内容哈希去重，跨版本共享）
CREATE TABLE files(
  sha256 TEXT PRIMARY KEY,
  path TEXT,
  size INTEGER,
  format TEXT,          -- 'pdf' | 'epub'
  stored_at TEXT);

-- 电子书专属元数据（不污染通用 documents 表）
CREATE TABLE ebook_meta(
  canonical_id TEXT PRIMARY KEY,
  author TEXT,
  isbn TEXT,
  lang TEXT,
  page_count INTEGER,
  publisher TEXT,
  published_date TEXT,
  cover_path TEXT,
  toc_json TEXT);       -- 章节大纲，JSON

-- 正文文本独立表，供 FTS5 external-content 引用（正文只存一份）
CREATE TABLE doc_text(
  doc_id TEXT,
  version_id INTEGER,
  title TEXT,
  content TEXT);

-- docs_fts 改为 external content，不再自己存文本
CREATE VIRTUAL TABLE docs_fts USING fts5(
  title, content, content='doc_text', content_rowid='rowid');

-- 向量切块（支持语义检索，按块存）
CREATE TABLE chunks(
  id INTEGER PRIMARY KEY,
  doc_id TEXT,
  version_id INTEGER,
  idx INTEGER,
  text TEXT,
  offset INTEGER);
```

`documents` 表增加列：`format TEXT`、`ingested INTEGER DEFAULT 0`、`file_hash TEXT`（→ `files.sha256`），`doc_type` 取值增加 `'ebook'`。

> 说明：`embeddings` 表已存在（`doc_id, version_id, model, vector`），改为按 `chunks.id` 关联即可，无需新建。

### 1.3 入库流程（状态机）

```
扫描到文件
  → 计算 sha256，files 表注册（已存在则复用路径，不重复落盘）
  → 解析元数据（标题/作者/页数/ISBN）→ 写 documents + ebook_meta
  │
  ├─ 不入库(ingested=0)：仅元数据可检索，结束
  │
  └─ 入库(ingested=1)
        → 抽取正文（PDF: pypdf / pdfminer；EPUB: zipfile 读 OPF + spine）
        → 切块 写 chunks
        → 建 FTS5 索引（doc_text + docs_fts）
        → 向量化 写 embeddings（按 chunk 关联）
        → 封面图提取 存 attachments(kind='cover')
        → 生成新 version_id
           判重：文件 sha256 未变则不新建版本，仅更新元数据
```

### 1.4 模块划分

| 模块 | 职责 |
|------|------|
| `khub/storage.py` | 受管库目录管理：`store_file()` 按哈希落盘、`path_for_hash()` |
| `khub/extractors/pdf.py` | `parse_meta()` / `extract_text()` |
| `khub/extractors/epub.py` | `parse_meta()` / `extract_text()` / `parse_toc()` |
| `khub/ingest.py` | 编排上面的流程，产出 `CanonicalDoc` + 写库 |
| `khub/models.py` | 已有 `CanonicalDoc`，新增 `EbookMeta` 等数据结构 |

依赖：`pypdf`（PDF）；EPUB 用标准库 `zipfile`（不引重依赖）；向量化模型按 config 指定。

### 1.5 规模/性能要点

- 二进制在磁盘，DB 始终保持小巧 → 备份/查询快。
- FTS5 **external-content**：正文只存一份（在 `doc_text`），FTS 只建索引。
- 大书切块后向量化，避免单条超长文本。
- 索引：`documents(doc_type, ingested)`、`files(sha256)`、`chunks(doc_id)`。
- 去重：文件级靠 `sha256`；版本级靠"文件哈希未变则不新建版本"。

---

## 二、未来扩展：中医考试培训系统（地基预留，不现在实现）

### 2.1 为什么现在不用动核心 schema

考试系统本质是**上层应用模块**，底层只依赖三样东西：已抽取的文本、向量（`embeddings`）、全文索引（`docs_fts`）。这三者当前 khub 的 `document_versions` + `embeddings` + `docs_fts` 已覆盖。一个 RAG 式题库/答疑流程是：

```
题目 → 检索相关中医文献（向量 + FTS）→ 拼上下文 → 调 LLM 生成/判分
```

检索端已具备，缺的"调 LLM"和"出题/判分"都是独立模块，不进核心库表。

### 2.2 现在就要留好的两个接口（低成本、高收益）

**A. LLM provider 抽象层（现在只定义接口，不实现）**

`khub/llm/__init__.py` 定义 Protocol，背后可换 OpenAI / 本地模型 / 国产模型，避免被某一家锁死：

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class LLMProvider(Protocol):
    def complete(self, prompt: str, **kwargs) -> str: ...
    def embed(self, text: str) -> list[float]: ...
```

**B. 向量检索能力（真正的坑，选型时记一笔）**

SQLite 当前把 embedding 存成 BLOB，但**没有原生近似最近邻（ANN）检索**。等题目/语料到万级，纯 Python 暴力算余弦会变慢。现在就预留切换点：

- 当前：`BLOB + 暴力检索` 跑通 MVP。
- 将来：上 `sqlite-vec` 扩展，或独立向量库（Chroma / Qdrant）。
- 切换只在"检索实现"层发生，不影响入库/存储层。

### 2.3 考试专属数据（以后单开，不污染现在）

- 题库（MCQ、病案分析、答案、解析）做成独立 `questions` 表，或独立 `doc_type='question'`，**不往 `documents` 塞考试字段**。
- 中医领域特化（证型、方剂、经络 tagging）做成**元数据标签层**，挂在 `metadata` 字段或独立 `tags` 表，不进核心表。

### 2.4 扩展路线图（时间顺序）

| 阶段 | 内容 | 是否动核心 schema |
|------|------|-------------------|
| M1 | SQLite + FTS5 + 版本化 | 是（基础） |
| M2 | PDF/EPUB 入库/存储（本文 §1，不入库闭环已完成） | 是（按 §1.2 扩展） |
| M3 | 全文检索 + 向量检索（暴力版）对外接口 | 否 |
| M4 | `LLMProvider` 抽象 + 一家实现接入 | 否（独立层） |
| M5 | 中医题库 `questions` 表 + RAG 出题/判分 | 否（独立表/模块） |
| M6 | 病历系统 `records` 表 + 问诊 `consultations` 表（复用检索/LLM） | 否（独立表/模块） |
| M7 | 向量检索升级到 ANN（sqlite-vec / 向量库） | 否（仅检索实现切换） |

> 所有上层模块（考试 / 病历 / 问诊）的共同地基：`document_versions` + `embeddings` + `docs_fts` + `LLMProvider`。它们只新增自己的表，不修改核心库表。

---

## 三、下一步建议

1. 先把 M1 缺失的 `khub/db.py` 补完（已完成）。
2. 按 §1 实现 M2（不入库闭环已完成；下一步补"入库"：全文/向量/封面）。
3. §2 的 LLM provider 接口现在只占个位，不写实现。

## 四、对外接口（API）策略

核心逻辑已做成**可导入的 Python 库**（`khub.db.Store`、`khub.storage.ManagedLibrary`、`khub.ingest.register_ebook` 等），CLI 只是它的一个消费者。因此：

- 现在：以**库 API + CLI** 为对外接口，足够本地/脚本调用，不做 HTTP 避免过度设计。
- 将来要远程/UI 调用时：在 `khub/api/` 加一层**薄 REST（如 FastAPI）**，直接调用现有函数，不重写业务逻辑。
- 原则：业务逻辑与传输层解耦，先有稳定库 API，HTTP 按需叠加。

