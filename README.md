# khub

个人知识中枢（knowledge hub），当前聚焦 **PDF/EPUB 电子书管理**，并预留了临床业务系统的地基：

- **电子书管理**：受管库目录 + 元数据解析 + 全文检索（中文 trigram）+ 向量检索（离线可跑）。文件可"入库"也可仅做"目录登记"。
- **患者数字孪生体管理系统**（骨架已搭）：以患者为中心聚合病历子系统、问诊子系统及未来子系统。
- **门诊运营管理系统**（骨架已搭）：排班 / 预约 / 就诊流。
- **中医考试培训系统**（骨架已搭）：题库 + RAG 出题 / 判分。

所有上层系统共用同一套地基：`document_versions` + `embeddings` + `docs_fts` + `LLMProvider` + 受管库目录，互不修改核心表。

## 快速开始

```bash
cd khub-m1
python3 -m pip install -e .        # 安装（含 PyYAML；pypdf 可选，用于 PDF 正文抽取）
python3 -m pytest -q               # 跑全部测试（31 个，无需联网）
```

### CLI 用法

```bash
export KHUB_DB=~/.khub/khub.db
export KHUB_LIBRARY=~/.khub/library

khub add path/to/book.epub            # 注册到受管库（不入库，仅目录+元数据）
khub list                             # 列出已注册电子书
khub ingest ebook:<sha256>            # 入库：抽正文 + 建 FTS 索引
khub patient-add p1 张三 --gender 男 --born 1980-01-01
khub record-add p1 --diagnosis 太阳病 --prescription 桂枝汤
khub consult-add p1 --chief 发热 --diff 表虚
khub twin-summary p1                  # 生成患者数字孪生摘要
khub ops-book p1 2026-07-10 王医生    # 预约挂号
khub exam-gen 少阳证                  # 生成一道中医考题
khub serve --port 8000               # 启动 REST API（默认 127.0.0.1）
```

### REST API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/ebooks` | 列出电子书 |
| POST | `/ebooks/register` `{path, move?}` | 注册一本 |
| POST | `/ebooks/{cid}/ingest` | 入库（抽文本+索引） |
| GET  | `/search?q=关键词` | 全文检索（中文子串） |
| POST | `/exam/questions` | 新增考题 |
| GET  | `/exam/questions?kind=` | 列出考题 |
| POST | `/exam/generate` `{topic}` | 生成考题（占位） |
| POST | `/clinical/patients` | 登记患者 |
| GET  | `/clinical/patients` | 列出患者 |
| POST | `/clinical/records` | 新增病历 |
| POST | `/clinical/consultations` | 新增问诊 |
| POST | `/clinical/twin/{pid}/summarize` | 生成孪生体摘要 |
| POST | `/ops/schedules` | 新增排班 |
| POST | `/ops/appointments` | 预约 |
| POST | `/ops/visits` | 签到就诊 |
| GET  | `/ops/appointments?date=` | 列出预约 |

> 角色、需求与交互模型（医生/护士/实习/前台/保安/患者/家属）见 `docs/roles.md`。

## 目录结构

```
khub/
  db.py            # Store：SQLite + FTS5(trigram) + 版本化 + files/ebook_meta
  models.py        # CanonicalDoc / RawDoc / Attachment / SyncResult
  storage.py       # ManagedLibrary：sha256 分桶落盘、去重
  extractors/      # pdf.py / epub.py：parse_meta + extract_text（epub 零依赖）
  ingest.py        # register_ebook（目录）/ ingest_ebook（入库）
  retrieval.py     # 离线 LocalEmbedder + Retriever（暴力余弦）
  llm/             # LLMProvider 抽象 + NoOpProvider（占位）
  api.py           # 薄 REST 层（标准库 http.server，零依赖）
  cli.py           # add / list / ingest / serve / patient-add / record-add / consult-add / ops-book / exam-gen / twin-summary
  exam/            # M5 中医考试系统（题库+生成+评判，占位）
  clinical/        # M6 患者数字孪生体（patients/records/consultations/twin）
  ops/             # M7 门诊运营（schedules/appointments/visits）
docs/
  plan_ebook.md    # 电子书入库/存储详细设计
  architecture.md  # 系统架构与数据模型
  testing.md       # 测试策略与运行方式
```

## 当前状态

| 模块 | 状态 | 说明 |
|------|------|------|
| 电子书 不入库 | ✅ 完成 | 受管库 + 元数据 + 去重 |
| 电子书 入库 | ✅ 完成 | 正文抽取 + FTS(trigram) |
| 向量检索 | ✅ 骨架 | 离线 LocalEmbedder；真实嵌入待接 LLMProvider |
| REST API | ✅ 完成 | 标准库实现，零依赖 |
| LLMProvider | ✅ 抽象 | NoOp 占位；真实实现待接 |
| 考试/孪生/运营 | 🟡 骨架 | 表结构 + CRUD + LLM 占位，待接真实模型 |
| 封面/向量化入库 | ⬜ 待做 | M2 收尾 |
| ANN 向量检索 | ⬜ 待做 | 升级 sqlite-vec / 向量库 |

## 安全

- REST API 默认绑定 `127.0.0.1`；远程访问只在 API 层加认证，不动核心。
- FTS 查询参数化，无注入；非法查询兜底返回空。
- 涉及 PII（病历/孪生体）时启用加密落盘 + 访问审计（见 `docs/architecture.md` §安全）。

详见 `docs/architecture.md` 与 `docs/testing.md`。
