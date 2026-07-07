# khub — 个人知识库中枢 设计规格

- 日期：2026-07-07
- 状态：待实现（已通过头脑风暴评审）
- 作者：用户 + CodeBuddy（superpowers-zh brainstorming 技能产出）

## 1. 目标

构建一个**本地优先**的个人知识库中枢：

- 从多个来源（ima、Quip、Obsidian、中医书籍 OCR 系统、未来的本地/云端知识库如 Confluence）聚合文档。
- 作为**备份/归档**（不丢任何内容）与**知识库中枢**（可检索、未来可语义问答）。
- 支持**双向同步**（按源配置），冲突时**保留多版本历史**，绝不静默覆盖。
- 分阶段演进：先全文检索，后接本地模型做语义检索/RAG。

## 2. 非目标（YAGNI）

- 不做多用户/权限系统（纯个人使用）。
- 第一版不做语义检索（M4 再做，但数据模型预留）。
- 不做复杂的冲突自动合并（保留多版本，人工裁决）。
- 不绑定特定笔记 App 作为唯一规范存储（中枢自身即规范存储）。

## 3. 架构总览

```
            ┌──────────── 源适配器（每源一个）────────────┐
 ima ───────┤  pull / push / normalize / detect_changes   │
 Quip ──────┤                                             │
 Obsidian ──┤  统一接口 → 规范文档模型                     │
 OCR 系统 ──┤                                             │──→ Sync 引擎（源无关）
 Confluence─┤                                             │        │
 其它 KB ───┤                                             │        ↓
            └─────────────────────────────────────────────┘   SQLite + FTS5
                                                         本地库 khub.db
                                                              │
                                                         全文检索 / 未来向量检索
```

- **本地存储**：SQLite 单文件 + FTS5 全文虚表。
- **Sync 引擎**：源无关，比对 hub 与源状态，决定 pull/push，冲突建版本。
- **CLI**：驱动 sync / query / ingest / 检视。
- **配置**：`config.yaml` + 密钥走环境变量/本地密钥文件（不进仓库）。

## 4. 数据模型（SQLite）

库文件：`/home/keen/khub/khub.db`（路径可在 config 覆盖）。

| 表 | 字段要点 | 说明 |
|----|---------|------|
| `sources` | id, type, name, direction(`two-way`/`read-only`), config_ref | 源注册 |
| `documents` | canonical_id, title, current_version, source_ids(JSON), created_at, updated_at | 规范文档 |
| `document_versions` | version_id, doc_id, content(或引用路径), format, origin(`hub`/`source`), author, updated_at, hash, parent_version, note | **版本历史；冲突新建版本** |
| `attachments` | id, doc_id, version_id, kind, path/uri, hash | 扫描图/OCR文本/附图等 |
| `sync_states` | source_id, doc_id, last_sync_at, etag, hash | 增量比对状态 |
| `embeddings` | doc_id, version_id, model, vector(BLOB) | **预留**，M4 填 |

- 版本策略：任何写入先算 hash；若与上一版本相同则跳过；若 hub 与某源都改过（hash 均变且互不相同）→ 新建两个版本（分别标记 origin），并置 `documents.conflict=1`，不覆盖。

## 5. 源适配器接口

每个适配器实现统一接口（Python 抽象基类）：

```python
class SourceAdapter:
    name: str
    direction: str  # "two-way" | "read-only"
    def pull(self) -> list[RawDoc]: ...        # 列表+正文+附件+元数据
    def push(self, doc: CanonicalDoc) -> SyncResult: ...  # 写回（read-only 抛 NotImplementedError）
    def normalize(self, raw) -> CanonicalDoc: ...          # 转规范模型
    def detect_changes(self, raw, last_state) -> bool: ... # etag/hash/updated_at
```

- 密钥/凭证从环境变量或本地密钥文件读取，绝不写入 `config.yaml` 或仓库。
- 单源失败隔离：一个适配器异常被捕获并记录，不中断其它源。

### 来源清单

| 源 | 类型 | 方向 | 状态 | 备注 |
|----|------|------|------|------|
| ima | API | two-way | M2 | 需验证接口可用性 |
| Quip | API | two-way（实际 read-only） | M2 | **明年下线 → 抢在下线前全量拉取归档** |
| Obsidian | 文件系统(.md) | two-way | **接口 M1 定义，装好后实现** | 当前未安装；mtime+hash 检测 |
| 中医 OCR 系统 | 入库接口(CLI/监听/HTTP) | push-in | M1/M2 | 产出一本→入一本 |
| Confluence（未来） | REST API | two-way | M3 | 本地实例 |
| 其它知识库（未来） | 通用适配器占位 | 待定 | M3+ | 接口预留 |

## 6. Sync 引擎

- 对每个启用源：拉取远端状态 → 与 `sync_states` + `documents` 比对。
- 单向/只读源只 pull；双向源按 `direction` 决定是否需要 push hub 改动。
- 冲突判定：自上次同步以来，hub 与源都发生变化且内容不一致 → 新建版本分支（origin 分别标记），置 `conflict` 标记，留待人工检视（`khub conflicts`）。
- 所有写操作走版本化，绝不 UPDATE 覆盖既有内容。

## 7. CLI 与配置

CLI 子命令：

- `khub sync [--source X]`：同步（全量或指定源）
- `khub query "关键词"`：FTS5 全文检索，返回命中文档/片段
- `khub ingest --book <dir>`：OCR 系统调用，将一本产出书入库
- `khub ls [--source X]`：列出文档
- `khub conflicts`：列出冲突版本
- `khub version <doc>`：查看某文档版本历史

`config.yaml` 示例结构：

```yaml
db: /home/keen/khub/khub.db
sources:
  - type: obsidian
    name: my-vault
    direction: two-way
    path: /home/keen/Documents/vault      # 安装后填
  - type: ima
    name: ima
    direction: two-way
    # creds via env: IMA_TOKEN
  - type: quip
    name: quip
    direction: read-only
    # creds via env: QUIP_TOKEN
  - type: ocr
    name: tcm-ocr
    direction: push-in
    inbox: /home/keen/khub/inbox/ocr
```

## 8. 分期实现

- **M1（先跑通，不依赖 Obsidian）**
  - SQLite + FTS5 schema、`document_versions` 版本化
  - 适配器统一接口 + **Obsidian 适配器 stub（接口定义，装好即补）**
  - **OCR 入库适配器**（push-in，立即有端到端价值）
  - CLI：`sync` / `query` / `ingest` / `ls` / `conflicts` / `version`
  - Sync 引擎 + 冲突多版本
  - 单测 + 用临时 vault / 测试库验证
- **M2**
  - ima 适配器、Quip 适配器（read-only 抢救，全量归档）
  - OCR 入库接口完善（监听目录 / 可选 HTTP）
  - **轻量本地 Web UI**（浏览 / 全文检索 / 冲突处理，仅监听 127.0.0.1）
- **M3**
  - Obsidian 完整适配器（安装后）、Confluence 适配器、通用适配器
  - 定时调度（cron / 内置 scheduler）
- **M4**
  - 填 `embeddings`，向量检索，接本地 `llama.cpp` 做语义问答/RAG
- **M5**
  - **桌面 GUI**（Electron / Tauri 等，可选）：在 Web UI 之上包壳，提供原生体验。视需求与精力再上，不阻塞前序阶段。

## 12. 界面形态（CLI / Web / GUI，分步实现）

用户确认三者都要，但分步落地：

- **CLI（M1）**：首选交互与自动化入口，`sync` / `query` / `ingest` / `ls` / `conflicts` / `version`。脚本、cron、OCR 系统都走 CLI。
- **Web UI（M2）**：轻量本地服务（FastAPI/Flask + 极简前端），浏览器访问，提供：文档浏览/树、全文检索结果与片段、冲突清单与版本对比、写回触发。只读浏览+检索为主，复杂写回仍由 CLI/适配器完成。仅监听 `127.0.0.1`，不外暴露。
- **桌面 GUI（M5）**：在 Web UI 之上套壳（Electron/Tauri），原生窗口体验。可选、最后做。

设计原则：内核（Sync 引擎 + SQLite + 适配器）与界面解耦——所有界面都只是调用同一套 CLI/内部 API，不在 UI 层重复业务逻辑。

## 9. 测试策略

- 适配器单测：mock API / 临时文件，验证 pull/push/normalize/detect_changes。
- Sync 引擎单测：构造 hub 改 + 源改的冲突场景，断言生成多版本、不覆盖。
- FTS 查询单测：插入样例文档，断言检索命中。
- 集成烟雾测试：用隔离测试 vault + 测试库，不碰真实数据。

## 10. 风险与待确认

- **Quip 下线时间窗**：需尽快确认具体下线日期，M2 优先全量拉取。
- **ima 接口可用性**：M2 前需实测 ima 是否有可用 API/导出能力（用户已确认“都有 API”）。
- **密钥管理**：明确用 env 还是本地密钥文件；不进仓库、不进 config.yaml。
- **Obsidian 未安装**：M1 仅定义接口；完整实现在其安装后进行。
- **中文分词**：FTS5 默认按空白/标点切词，中文需确认分词效果（必要时用 trigram 或外部分词）。

## 11. 与本机已搭环境的协同

- khub 项目目录挂 `CODEBUDDY.md` / `HERMES.md`，可由 CodeBuddy 或 Hermes 驱动开发与运维。
- 复用本机已有 Python（miniconda3 / python3.11）与本地模型（llama.cpp，M4 语义检索）。
