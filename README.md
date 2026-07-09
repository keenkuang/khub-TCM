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
python3 -m pytest -q               # 跑全部测试（182 个，无需联网）
```

### CLI 用法

```bash
export KHUB_DB=~/.khub/khub.db
export KHUB_LIBRARY=~/.khub/library

khub add path/to/book.epub            # 注册到受管库（不入库，仅目录+元数据）
khub list                             # 列出已注册电子书
khub ingest ebook:<sha256>            # 入库：抽正文 + 建 FTS 索引
khub doc-add --title 伤寒论 --file 产出.md --source-id kzocr-xxx   # 直接入库一份文档（KZOCR/OCR 产出）
khub watch /path/to/kzocr-out --interval 3   # 监听目录，KZOCR 产出 .md 落盘即自动入库
khub query 桂枝汤                    # 全文检索（支持分页/来源过滤）
khub quip-sync --token xxx [--root ROOT]    # 从 Quip 拉取文档归档到本地库
khub obsidian-import /path/to/vault          # 导入 Obsidian vault（.md 目录）
khub feishu-sync                      # 同步飞书文档
khub ima-note-sync                    # 拉取 IMA 笔记
khub ima-sync                        # 同步 IMA 文档
khub ima-probe --once                # 探测 IMA API 配额状态（单次）
khub ima-probe                       # 持续科学探测配额规律
khub schedule --config tasks.yaml            # 运行定时调度器
khub desktop                                  # 启动桌面 GUI（浏览器模式）
khub desktop --electron                       # 启动桌面 GUI（Electron 原生窗口，需先 npm install electron）
khub patient-add p1 张三 --gender 男 --born 1980-01-01
khub record-add p1 --diagnosis 太阳病 --prescription 桂枝汤
khub consult-add p1 --chief 发热 --diff 表虚
khub twin-summary p1                  # 生成患者数字孪生摘要
khub ops-book p1 2026-07-10 王医生    # 预约挂号
khub exam-gen 少阳证                  # 生成一道中医考题
khub serve --port 8000               # 启动 REST API（默认 127.0.0.1，含轻量 Web UI 于 /）
khub dr init                         # 灾备：初始化快照仓库
khub dr push [--target ssh://...]    # 灾备：推送快照到异地
khub dr status                       # 灾备：查看快照/lsn 状态
khub dr list-snapshots               # 灾备：列出可用快照
khub dr restore --to <lsn|snapshot>  # 灾备：按 lsn/快照恢复到指定时间点
khub ha status                       # 高可用：查看节点角色/状态
khub ha promote                      # 高可用：提升为本机为 Primary
khub ha demote                       # 高可用：降级为 Standby
khub ha run                          # 高可用：启动备机回放循环
khub ha reconcile                    # 高可用：检测并协调主备差异
khub ha resolve <id>                 # 高可用：解决脑裂
khub ha self-test                    # 高可用：自检
```

### REST API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/ebooks` | 列出电子书 |
| POST | `/ebooks/register` `{path, move?}` | 注册一本 |
| POST | `/ebooks/{cid}/ingest` | 入库（抽文本+索引） |
| GET  | `/` | 轻量本地 Web UI（文档浏览 / 检索 / 冲突清单） |
| GET  | `/health` | 健康检查（版本 / 文档数 / 运行时长） |
| GET  | `/stats` | 数据看板（总数 / 各来源 / 今日入库 / 最近文档） |
| GET  | `/documents` | 列出全部文档 |
| GET  | `/documents/{cid}` | 获取单篇文档（最新版本全文，截断至 100k 字符） |
| GET  | `/conflicts` | 列出冲突文档 |
| GET  | `/search?q=关键词` | 全文检索（中文子串；<3 字符自动退回 LIKE；支持 page/per/source） |
| GET  | `/semantic?q=关键词&k=5` | 语义检索（向量 / ANN，接真实模型后质量提升） |
| GET  | `/web/*` | 静态资源（路径穿越已防护） |
| POST | `/documents` `{title, content, source?, source_id?, format?, metadata?}` | 直接入库一份文档（KZOCR/OCR 产出，不依赖原始文件） |
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

### 接真实模型（可选）

向量与 LLM 默认离线兜底，配置环境变量即切换为真实模型（无需改代码）：

| 变量 | 作用 |
|------|------|
| `KHUB_EMBEDDING_URL` | 嵌入服务基址（OpenAI 风格 `/v1/embeddings`），启用后语义检索走真实向量 |
| `KHUB_EMBED_DIM` / `KHUB_EMBED_API_KEY` / `KHUB_EMBED_MODEL` | 嵌入维度 / 鉴权 / 模型名 |
| `KHUB_LLM_URL` | LLM 服务基址（OpenAI 风格 `/v1/chat/completions`），启用后孪生摘要/考题生成走真实模型 |
| `KHUB_LLM_API_KEY` / `KHUB_LLM_MODEL` | LLM 鉴权 / 模型名 |
| `KHUB_DISABLE_ANN` | 设为 `1` 时语义检索退回暴力余弦 |

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
| 向量检索 | ✅ 升级 | ANN：sqlite-vec 虚拟表近似检索（已装 0.1.9），不可用时退回暴力余弦 |
| 真实嵌入 | ✅ 接入 | `RemoteEmbedder` 调用 `/v1/embeddings`（llama.cpp/远端）；设 `KHUB_EMBEDDING_URL` 即启用 |
| 语义检索 API | ✅ 完成 | `GET /semantic` + Web UI「语义」按钮 |
| REST API | ✅ 完成 | 标准库实现，零依赖 |
| 轻量 Web UI | ✅ 完成 | M2 要求：GET / 文档浏览/检索/冲突；仅绑 127.0.0.1 |
| 目录监听自动入库 | ✅ 完成 | `khub watch <dir>`：KZOCR 产出 .md 落盘即入库（幂等） |
| LLMProvider | ✅ 真实接入 | `RemoteLLMProvider` 调 `/v1/chat/completions`（llama.cpp/远端）；设 `KHUB_LLM_URL` 即启用，否则 NoOp 兜底 |
| 孪生摘要 | ✅ 真实驱动 | `build_summary` 用真实模型；无模型时聚合病历/问诊生成模板兜底 |
| 考试生成 | ✅ 真实驱动 | `generate` 用真实模型出题；无模型时返回占位题干 |
| 封面/向量化入库 | ✅ 完成 | 入库自动抽封面 + 建向量索引 |
| KZOCR 入库链路 | ✅ 完成 | `/documents` 端点 + `doc-add` CLI + KZOCR 推送客户端打通 |
| 短查询检索 | ✅ 完成 | <3 字符（如方剂名"麻黄"）自动 LIKE 回退 |
| ANN 向量检索 | ✅ 完成 | sqlite-vec 虚拟表（余弦），入库自动维护；`KHUB_DISABLE_ANN=1` 退回暴力 |
| PII 加密落盘 | ✅ 完成 | Fernet 对称加密，覆盖患者姓名/性别/出生/诊断/处方/主诉/辨证/方案等；设 `KHUB_PII_ENCRYPT=1`+`KHUB_PII_KEY` 启用，默认关闭 |
| 访问审计 | ✅ 完成 | `audit_log` 表记录每次临床 PII 读取事件（read_patient/read_records/read_twin 等） |
| 灾备/热备规划 | ✅ 完成 | `docs/disaster_recovery.md` + `khub/replication.py`（ReplicaTarget 契约 + WALLog + Snapshot + LocalFileReplica 参考实现） |
| Quip 文档归档 | ✅ 完成 | `khub quip-sync` + `khub/quip.py`：递归拉取 Quip 文档入库；mock 测试覆盖 |
| Obsidian 导入 | ✅ 完成 | `khub obsidian-import` + `khub/obsidian.py`：.md 目录扫描入库；内容变更检测幂等 |
| 定时调度 | ✅ 完成 | `khub schedule` + `khub/scheduler.py`：YAML 配置 + 后台循环执行 khub 命令 |
| 搜索高亮/分页/过滤 | ✅ 完成 | 关键词 `<mark>` 高亮，20 篇/页翻页，来源下拉过滤 |
| 数据看板 | ✅ 完成 | 首页顶部统计卡片（总文档/各源/今日入库/最近文档） |
| 优雅关闭 | ✅ 完成 | SIGTERM/SIGINT → httpd.shutdown() |
| 桌面 GUI | ✅ 完成 | Electron 套壳 (`desktop/main.js` + `desktop/package.json` + `desktop/run.sh`)，`khub desktop` 浏览器模式 |

## 安全

- REST API 默认绑定 `127.0.0.1`；一旦设置环境变量 `KHUB_API_TOKEN`，**所有**端点（含读）均需 `Authorization: Bearer <token>`，避免本地任意进程裸读病历/问诊等 PII。未设置则不鉴权（仅本地使用）。
- FTS 查询参数化，无注入；非法查询兜底返回空。
- ANN 向量表名由 `model` 经白名单校验（仅 `[A-Za-z0-9_]`），防建/删表 SQL 注入；定时调度命令以 `shell=False` 执行，防命令注入。
- 涉及 PII（病历/孪生体）时启用加密落盘 + 访问审计（见 `docs/architecture.md` §安全）。PII 加密默认关闭，需 `KHUB_PII_ENCRYPT=1` + `KHUB_PII_KEY`（或 `KHUB_PII_KEY_FILE`）启用；docker-compose 默认开启。

详见 `docs/architecture.md` 与 `docs/testing.md`。
