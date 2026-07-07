# khub 架构与数据模型

## 1. 设计原则

1. **二进制不进 SQLite**：原文件存受管库目录（按 sha256 分桶），DB 只存元数据/文本/索引/向量。DB 保持小巧，备份 = 复制整个 `~/.khub/`。
2. **核心表稳定，业务模块只加表**：`documents` / `document_versions` / `attachments` / `sync_states` / `embeddings` / `docs_fts` / `files` / `ebook_meta` 是地基；考试/孪生/运营各自新增独立表，不改动核心。
3. **业务逻辑与传输层解耦**：核心是可导入的 Python 库；CLI 与 REST API 都是消费者，可随意叠加。
4. **LLM 抽象、延迟绑定**：所有智能能力走 `LLMProvider` 接口，当前 `NoOpProvider` 占位，未来换实现不碰业务。
5. **默认安全**：API 绑 localhost；PII 模块启用加密落盘 + 审计。

## 2. 模块与职责

| 模块 | 职责 | 关键接口 |
|------|------|----------|
| `db.Store` | SQLite + FTS5(trigram) + 版本化、文件/元数据登记、检索 | `store_document`, `search`, `add_ebook`, `list_ebooks`, `upsert_file` |
| `storage.ManagedLibrary` | 受管库目录：sha256 落盘、去重、move/copy | `store`, `path_for_hash` |
| `extractors` | PDF/EPUB 元数据与正文抽取 | `parse_meta`, `extract_text` |
| `ingest` | 编排入库流程 | `register_ebook`（目录）, `ingest_ebook`（入库） |
| `retrieval` | 离线嵌入 + 暴力余弦检索 | `LocalEmbedder`, `Retriever.index_document/index_ebook/search_similar` |
| `llm` | LLM 抽象层 | `LLMProvider`, `get_provider`, `register_provider`, `NoOpProvider` |
| `api` | 薄 REST（http.server） | `App.dispatch`, `serve` |
| `exam` | 中医考试：题库 CRUD + 生成/评判（占位） | `add_question`, `generate`, `grade` |
| `clinical` | 患者数字孪生体：patients/records/consultations/twin | `add_patient`, `add_record`, `add_consultation`, `build_summary`/`persist_summary` |
| `ops` | 门诊运营：排班/预约/就诊 | `add_schedule`, `book_appointment`, `checkin_visit` |

## 3. 数据模型（表）

核心：
- `documents(canonical_id, title, current_version, source_ids, created_at, updated_at, doc_type, conflict, format, ingested, file_hash)`
- `document_versions(version_id, doc_id, content, format, origin, author, updated_at, hash, parent_version, note)`
- `attachments(id, doc_id, version_id, kind, path, hash)`
- `sync_states(source_id, doc_id, last_sync_at, etag, hash)`
- `embeddings(doc_id, version_id, model, vector BLOB)`
- `docs_fts` — FTS5，`tokenize='trigram'`（中文子串检索）
- `files(sha256 PK, path, size, format, stored_at)`
- `ebook_meta(canonical_id, author, isbn, lang, page_count, publisher, published_date, cover_path, toc_json)`

业务（各自独立）：
- `questions(id, kind, stem, options JSON, answer, explanation, source_doc, created_at)`
- `patients(id, name, gender, born, created_at)`
- `records(id, patient_id, visit_date, diagnosis, prescription, note, created_at)`
- `consultations(id, patient_id, date, chief_complaint, tongue_pulse, differentiation, plan, created_at)`
- `schedules(id, date, doctor, slot)` / `appointments(id, patient_id, date, doctor, status, created_at)` / `visits(id, appointment_id, patient_id, checkin_at, note)`

## 4. 扩展点（未来实现的位置）

- **真实嵌入 / LLM**：实现 `LLMProvider`（如 OpenAI / 本地模型 / 国产模型），`register_provider` 注册后，`retrieval` / `exam.generator` / `exam.grader` / `clinical.twin` 自动生效，无需改业务代码。
- **ANN 向量检索**：替换 `Retriever.search_similar` 的暴力实现为 `sqlite-vec` 或独立向量库；接口不变。
- **封面/向量化入库**：在 `ingest_ebook` 中补 `extract_cover` 与逐块 `embeddings` 写入（当前仅整篇文本）。
- **加密落盘**：对 `patients`/`records`/`consultations`/`twin` 启用 SQLCipher 或文件系统加密 + 访问审计。

## 5. 安全

- 网络：REST 默认 `127.0.0.1`；远程仅 API 层加认证。
- 注入：FTS `MATCH ?` 参数化；非法查询 `search()` 兜底返回 `[]`。
- 数据：本地文件；PII 模块（M6）启用加密 + 审计；备份 = 复制 `~/.khub/`。
- 去重：sha256 防同文件多份冗余与泄漏面扩大。

> 电子书入库/存储的详细设计见 `plan_ebook.md`。
> 角色、需求与交互模型（医生/护士/实习/前台/保安/患者/家属）见 `roles.md`。
