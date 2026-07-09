# khub M1 架构评审报告

- **评审者**：CodeBuddy（架构评审模式）
- **日期**：2026-07-09
- **范围**：对照设计规格 `2026-07-07-khub-design.md` 评审实现计划 `2026-07-07-khub-m1.md`
- **状态**：有条件通过（4 high, 3 medium, 2 low findings）

---

## 1. 架构对齐

**Finding 1**：M1 计划中 `SyncEngine.ingest()` 包含硬编码的适配器名称检查 `if adapter.name != "ocr"`，违反复合层架构——Sync 引擎本应是"源无关"（source-agnostic）的。

设计规格第 6 节明确规定 Sync 引擎是"源无关"的，应由 `direction` 字段决定行为，而非适配器名称。该硬编码表明当前 `direction` 模型未覆盖"push-in 源不写 sync_states"这一语义，暴露了方向模型的设计缺口。

| 位置 | 代码 |
|------|------|
| `engine.py:633` | `if adapter.name != "ocr": self.store.set_sync_state(...)` |

- **Severity**：high
- **Recommendation**：在 `SourceAdapter` 中引入 `def should_track_sync_state(self) -> bool` 默认方法（push-in 返回 `False`，其余返回 `True`），或将 track 语义纳入 `direction` 枚举的元数据中。去除硬编码名称检查。

---

**Finding 2**：CLI 层将适配器实例化与配置耦合在一起，缺失适配器工厂/注册机制。

M1 计划中对适配器实例化直接写在 `cli.py` 中（`OcrAdapter(args.book)`），这在只有一个适配器需要实例化时可行。但 M2 加入 ima、Quip、Confluence 后，每个适配器有不同的构造参数（API token、base URL、vault path、inbox dir 等），`cli.py` 中的条件分支将膨胀。设计规格第 3 节的架构图展示的是一个"源无关"的引擎，但当前 CLI 到引擎的「实例化适配器→传给引擎」这一步是硬编码的。

- **Severity**：medium
- **Recommendation**：在 M1 中即引入一个轻量适配器工厂函数（`def make_adapter(source_cfg: dict) -> SourceAdapter`），通过 `source_cfg["type"]` 映射到对应适配器类，构造参数从配置字典提取。此工厂在 `engine.py` 或独立的 `adapters/factory.py` 中定义，CLI 只需从 config.yaml 读取配置列表即可。

---

**Finding 3**：CLI 测试使用了 `click.testing.CliRunner`，但 M1 实际实现使用 `argparse`。测试代码与实现代码框架不匹配。

`tests/test_cli.py` 中的测试用例如 `from click.testing import CliRunner` 和 `runner.invoke(cli, ["ingest", ...])` 是 click 的 API，但 M1 计划最终决定使用 `argparse`（第 1048 行注释说明"零额外依赖"）。两种框架的测试模式完全不同——click 可以函数式调用，argparse 通常通过 `subprocess.run` 测试。该不一致会导致测试失败且无法编译（缺少 click 依赖）。

- **Severity**：high
- **Recommendation**：统一测试模式。若用 argparse，测试改为 `subprocess.run([sys.executable, "-m", "khub.cli", ...])` 方式；若改为 click，需在 `pyproject.toml` 中加入 click 依赖。两种方式皆可，但不能混用。

---

## 2. 层次分离

**Finding 4**：`adapters/base.py` 中 `detect_changes` 方法直接依赖于 `db.compute_hash()`，引入自底向上的依赖。

```
models.py ← db.py ← engine.py ← cli.py
models.py ← adapters/base.py (通过 compute_hash)
```

`compute_hash` 是存储层的辅助函数，被适配器层调用——而适配器本应是独立于存储的纯数据转换层。如果未来适配器作为独立包发布或在无 Store 的环境中使用，该依赖会带来问题。

- **Severity**：low
- **Recommendation**：将 `compute_hash` 从 `db.py` 移至 `models.py` 或新建 `khub/utils.py`。`detect_changes` 需要它作为纯哈希工具函数，与 Store 类无关。这样适配器层不再依赖 db 层。

---

**Finding 5**：`engine.py` 中 `_current_hash` 方法直接访问 `self.store.conn.execute()`，绕过 `Store` 类的方法接口，破坏封装。

```python
def _current_hash(self, doc_id: str):
    v = self.store.conn.execute(
        "SELECT hash FROM document_versions WHERE doc_id=? ORDER BY version_id DESC LIMIT 1",
        (doc_id,)).fetchone()
```

`Store` 类已提供 `get_document`、`get_versions` 等公共方法，但引擎选择直接操作连接对象。如果未来 `Store` 更换底层存储（如换为 async 库或切换连接池），引擎代码需要同步修改。

- **Severity**：medium
- **Recommendation**：在 `Store` 上新增 `def get_current_hash(self, doc_id: str) -> str | None` 公共方法，引擎改为调用该接口。

---

**Finding 6**：层次分离总体评估——未发现循环依赖。

```
models        ← 无 khub 内部依赖（纯数据类）
adapters/base → models, db (compute_hash 见 Finding 4)
adapters/ocr  → adapters/base, models
adapters/obs  → adapters/base, models
db            → models
engine        → db, models
config        → 仅 yaml
cli           → 所有（编排层，可接受）
```

无循环依赖。编排层 `cli.py` 依赖所有下层模块，符合架构规范。**通过**。

- **Severity**：N/A
- **Recommendation**：无。

---

## 3. 接口设计

**Finding 7**：`SourceAdapter` 抽象基类缺少 `name` 和 `direction` 的契约保障。

在 `base.py` 中，`name` 和 `direction` 被定义为类级注解（`name: str`），但没有任何机制强制子类实现或验证它们。如果子类忘记设置 `direction`，`SyncEngine` 在 `if adapter.name != "ocr"` 这类逻辑中会得到属性缺失错误。

- **Severity**：medium
- **Recommendation**：使用 `@property` + `@abstractmethod` 装饰器确保子类必须实现这两个属性，或在 `SourceAdapter.__init_subclass__` 中进行验证。

---

**Finding 8**：`SourceAdapter.pull()` 返回 `list[RawDoc]`，但当适配器从远程 API（Quip/ima）拉取时，网络错误、认证失效、限流等异常场景缺少明确的错误契约。

设计规格第 5 节要求"单源失败隔离"——一个适配器异常不中断其它源。但 `pull()` 的签名没有区分"无文档"和"拉取失败"。当前引擎在 `adapter.pull()` 遇到异常时会直接冒泡至顶层。

- **Severity**：low（M1 OCR 适配器仅本地文件读取，无网络风险；M2 远程 API 适配器需处理）
- **Recommendation**：在 M1 中至少在 `SourceAdapter` 文档字符串（docstring）中明确约定：`pull()` 应将网络/认证异常包装为明确的适配器异常类型（如 `AdapterError`），引擎层捕获后记录并跳过该源。M2 前引入 `class AdapterError(Exception)`。

---

**Finding 9**：`SourceAdapter.push()` 的返回值类型是 `CanonicalDoc` 的合约尚未对齐。

在基类中 `push(self, doc: CanonicalDoc)` 未指定返回值类型；在测试中 `def push(self, doc): return None`；而在 `OcrAdapter` 中 `push()` 抛 `NotImplementedError`。设计规格中定义 `def push(self, doc: CanonicalDoc) -> SyncResult`。三者不一致。

- **Severity**：medium
- **Recommendation**：统一 `push()` 签名为 `def push(self, doc: CanonicalDoc) -> SyncResult`（与设计规格一致）。测试中的 dummy `push` 也改为返回 `SyncResult` 类型。

---

## 4. 可扩展性

**Finding 10**：缺乏适配器注册/发现机制，新增源类型需要修改多处代码。

在 M1 中增加一个 OCR 适配器需要：
1. 在 `khub/adapters/` 下创建文件
2. 在 `cli.py` 的 `sync` 子命令逻辑中手动添加 if/else（当前 M1 sync 命令输出固定信息，未联动适配器列表）
3. 在 `cli.py` 的 `main()` 中需要知道哪些源要同步
4. 在 `test_cli.py` 中增加测试

到 M2 阶段，支持 4 个源（ocr, obsidian, ima, quip），这种方式不可维护。

- **Severity**：high
- **Recommendation**：如前所述引入适配器工厂。具体模式：

```python
# adapters/factory.py
_ADAPTERS: dict[str, type[SourceAdapter]] = {}

def register(type_name: str, adapter_cls: type[SourceAdapter]):
    _ADAPTERS[type_name] = adapter_cls

def create(source_cfg: dict) -> SourceAdapter:
    cls = _ADAPTERS.get(source_cfg["type"])
    if cls is None:
        raise ValueError(f"未知源类型: {source_cfg['type']}")
    return cls.from_config(source_cfg)
```

CLI 改为遍历 `config.yaml` 中的 sources 列表，对每个源调用 `create(cfg)` 即可。

---

**Finding 11**：`direction` 枚举与设计规格不一致。

设计规格第 5 节定义了 `direction: str  # "two-way" | "read-only"`，而 M1 计划引入了第三个值 `"push-in"`。这是一个合理的扩展（push-in 是单写入的源，不同于 read-only 的轮询模式），但设计规格和接口定义间存在不一致，需要同步更新。

- **Severity**：low
- **Recommendation**：将设计规格中的方向定义更新为三种（`two-way` / `read-only` / `push-in`），并在 `SourceAdapter` 的文档字符串中明确每种方向的语义差异。

---

## 5. 数据流分析

**Finding 12**：OCR 数据流整体完整，但存在路径假设错误。

完整数据流追踪：

```
CLI: khub ingest --book /path/to/book
  → cli.py: main()
    → OcrAdapter(book_dir).pull()
      → 遍历 book_dir/*.md，读取内容，计算 SHA256[:16] 作为 etag
      → 扫描 book_dir/attachments/ 目录获取附件
      → 返回 [RawDoc(id=文件名.stem, title=文件名.stem, ...)]
    → SyncEngine.ingest(adapter)
      → adapter.normalize(raw)  → CanonicalDoc(...)
      → store.store_document(canon)
        → 插入/更新 documents 表
        → 插入 document_versions 行
        → 重建 FTS5 docs_fts
        → 插入 attachments 行
      → 返回 SyncResult("created", ...)

CLI: khub query "关键词"
  → store.search("关键词")
    → SELECT snippet(docs_fts, 2, '[', ']', '...', 10) FROM docs_fts WHERE MATCH ?
    → 返回 [(doc_id, title, snippet)]
  → 打印到 stdout
```

**关键问题**：`OcrAdapter.pull()` 假定一本书 = 一个目录，但 OCR 系统可能在一个 book_dir 目录下有多本书（多个 `.md` 文件），此时 `pull()` 返回的列表中有多本书，但 `OcrAdapter` 的构造函数只接受单个 `book_dir`。`sync_source` 每次只处理一个适配器实例，每次同步都重新创建适配器。这本身没问题，但 `ingest` 命令的 `--book` 指向的是"书目录"还是"产出目录"存在歧义——设计规格中的 `inbox` 概念（`config.yaml` 中的 `inbox: /home/keen/khub/inbox/ocr`）在 M1 计划中未被使用。

- **Severity**：medium
- **Recommendation**：明确 inbox 和 book_dir 的关系。建议在设计中引入"inbox 监听"语义：inbox 目录包含多个 book 子目录，OcrAdapter 接收 inbox 路径，从所有子目录中搜集产出书。M1 可简化实现，但术语应在 CLI 参数和文档中统一。

---

**Finding 13**：`ingest` 流程中缺失 `sync_states` 的写入，但 CLI 的 `sync` 命令在 M1 中不起作用。

在 `engine.py` 中，`ingest()` 方法对 OCR 适配器跳过 `set_sync_state`（同时跳过对其它适配器的写入——因为只有 OCR 适配器在 M1 中使用）。这意味着 `ingest` 进来的文档不会被 `sync_source` 识别为已同步，下次 `sync` 时会重新创建。虽然 M1 中 `sync` 命令只打印固定信息，但若开发者后续调试时手动调用 `sync_source` 会遇到问题。

- **Severity**：low
- **Recommendation**：即使对 push-in 源，`ingest()` 也应写入 sync_states，标记为"已录入"。或如 Finding 1 建议，让 `should_track_sync_state()` 决定。

---

## 6. 可伸缩性关注

**Finding 14**：M1 无内容去重策略，版本化存储可能导致大量磁盘占用。

每个文档版本存储完整的 `content` 文本。对于中医 OCR 书籍（Typical book：数万至数十万字），一次编辑产生 200KB+ 的新版本行。中医学 OCR 系统如产生数百本书、每本多次修订，`document_versions` 表的体积增长显著。

| 场景 | 估算 |
|------|------|
| 100 本书，每本 100KB，平均 5 个版本 | ~50 MB |
| 1000 本书，每本 200KB，平均 5 个版本 | ~1 GB |
| FTS5 索引额外增加约 50-80% 原始大小 | 额外 ~0.5-1.5 GB |

对个人使用而言，以上规模 SQLite 完全可以承载。但作为一个长期知识库，5-10 年后可能数百 GB。

- **Severity**：low（M1 非阻塞，但需在 M2/M3 前关注）
- **Recommendation**：在 M3 版本化优化时引入"content 外存化"选项：将大版本内容存为本地文件，`document_versions.content` 仅存储文件路径引用（类似 attachments 模式），或引入 zlib 压缩字段。

---

**Finding 15**：FTS5 中文分词缺少明确策略。

设计规格第 10 节已指出风险：FTS5 默认 tokenizer 按空白和标点分词，对中文效果很差。M1 计划在"步骤 2：验证 FTS5 可用"中仅验证 FTS5 扩展是否加载（`CREATE VIRTUAL TABLE t USING fts5(x)`），未验证中文分词效果。若不做处理，`khub query "伤寒论"` 在包含"伤寒论"全文的 FTS5 索引上可能返回零结果。

- **Severity**：high
- **Recommendation**：M1 中即增加一个验证测试：插入包含中文的文档，确认 FTS5 能匹配。若默认分词不可用，改为 `TRIGRAM` tokenizer（`CREATE VIRTUAL TABLE docs_fts USING fts5(doc_id, title, content, tokenize='trigram')`），或用 `unicode61` tokenizer 加 `tokenchars` 选项。也可在 M1 中使用 `LIKE '%keyword%'` 作为中文查询的降级方案。

---

**Finding 16**：SQLite 缺乏 WAL 模式和连接超时设置。

`Store.__init__` 使用默认的 `journal_mode=delete` 和 `timeout=5`。这对于并发读可能产生性能瓶颈（虽然 M1 是单用户 CLI 场景），但对于未来 M2 Web UI（FastAPI）的多线程访问，会导致 "database is locked" 错误。

- **Severity**：medium（M1 不阻塞，M2 前必须解决）
- **Recommendation**：在 `Store.__init__` 中启用 WAL 模式并设置 timeout：

```python
self.conn.execute("PRAGMA journal_mode=WAL")
self.conn.execute("PRAGMA busy_timeout=5000")
```

---

## 7. 架构决策评估

**Finding 17**：`CanonicalDoc` 中 `version` 字段与 `document_versions` 自增 `version_id` 存在概念混淆。

`CanonicalDoc` 有 `version: int = 1` 字段，但 `Store.store_document()` 创建版本时使用自增 `version_id`，且从未使用或设置 `doc.version` 字段。`documents.current_version` 存储的是 `version_id`（自增 ID）而非语义版本号。这可能导致"一个文档的版本 N 和 VERSION_ID N"之间的混淆。

- **Severity**：low
- **Recommendation**：明确 `version_id` 是自增全局唯一 ID（用于引用），`CanonicalDoc.version` 是语义上的文档版本号（从 1 递增的序列号）。若不需要语义版本号，从 `CanonicalDoc` 中移除该字段以免混淆。

---

**Finding 18**：`documents.source_ids TEXT` 列使用 JSON 数组存储多个源，但缺少索引，且插入时仅写入 `[source]`（单一源），违背了多源关联设计的初衷。

设计规格显示 `source_ids(JSON)` 用于多源关联，但 `store_document` 插入时仅写入 `json.dumps([doc.source])`，从未合并多个源。当一个文档被两个适配器识别（如同一个 Obsidian 笔记同时通过 OCR 入库），文档会以不同 canonical_id 重复存储。

- **Severity**：medium（多源关联是架构基础特性，M1 不为实现但应为后续预留）
- **Recommendation**：在 `store_document` 中加入简单的源 ID 去重逻辑：若文档已存在且新源不在已有 `source_ids` 中，追加而非覆盖。同时为未来实现文档 dedup（基于内容 hash 匹配多源同文）预留接口。

---

**Finding 19**：`search()` 仅返回 `(doc_id, title, snippet)`，缺少 `source` 信息。

用户通过 `khub query "keyword"` 知道"哪本书命中了"，但不知道来自哪个源（ocr/obsidian/ima），也无法直接定位到源头文件。

- **Severity**：low
- **Recommendation**：扩展 `search()` 的返回结果，包含 `source_ids` 信息。可以通过 JOIN `documents` 表实现，或修改 FTS5 内容表增加 source 字段。

---

## 8. Issue #1：CanonicalDoc 缺少 `etag` 字段

**Finding 20**：`OcrAdapter.normalize()` 向 `CanonicalDoc` 传递了 `etag=raw.etag` 关键字参数，但 `CanonicalDoc` 数据类没有 `etag` 字段。

```python
# khub/adapters/ocr.py:539-544
def normalize(self, raw: RawDoc) -> CanonicalDoc:
    return CanonicalDoc(
        canonical_id=f"ocr/{raw.id}",
        title=raw.title, content=raw.content, source="ocr",
        source_id=f"ocr/{raw.id}", etag=raw.etag,   # <-- TypeError! 无 etag 字段
        attachments=raw.attachments)
```

`RawDoc` 有 `etag` 字段（用于存储 HTTP ETag 或本地哈希），`CanonicalDoc` 有 `hash` 字段（用于存储内容哈希）。`OcrAdapter.pull()` 中 `etag` 实际上是一个内容 SHA256 哈希，应映射到 `CanonicalDoc.hash`。`detect_changes()` 已被设计为可使用 `raw.etag` 或 `compute_hash(raw.content)`，但 canonical doc 和 sync_states 之间传递的是 `hash`。

当前代码会在 `normalize()` 运行时抛出 `TypeError: __init__() got an unexpected keyword argument 'etag'`——这是一个**编译/运行时的阻塞性缺陷**。

**架构分析**：此问题反映了两个层次之间的契约断裂：
- `RawDoc.etag`：源级指纹（API ETag / 文件哈希）
- `CanonicalDoc.hash`：规范级内容指纹
- `sync_states.etag`：同步跟踪用存储的源级指纹
- `sync_states.hash`：同步跟踪用存储的内容指纹

当前架构意图是：`CanonicalDoc` 是中枢内部模型，不应携带源特定的 `etag`；etag 应保留在 `sync_states` 中。因此 `normalize()` 应将 `raw.etag` 映射为 `canon.hash` 而非传递 `etag=raw.etag`。

- **Severity**：high（阻塞性缺陷，normalize() 会抛 TypeError）
- **Recommendation**：两种修复方案：

**方案 A（推荐）**：修复 `OcrAdapter.normalize()`，将 `etag=raw.etag` 改为 `hash=raw.etag`：

```python
def normalize(self, raw: RawDoc) -> CanonicalDoc:
    return CanonicalDoc(
        canonical_id=f"ocr/{raw.id}",
        title=raw.title, content=raw.content, source="ocr",
        source_id=f"ocr/{raw.id}", hash=raw.etag,   # etag → hash 映射
        attachments=raw.attachments)
```

并在 `test_ocr_adapter.py` 中增加断言验证 `canon.hash == raw.etag`。

**方案 B（备选）**：如果架构要求 CanonicalDoc 保留源级 etag 用于变更追踪，则给 `CanonicalDoc` 增加 `etag: str = ""` 字段，并确保 `store_document` 将 etag 写入 `sync_states`（当前 `set_sync_state` 已接受 etag 参数）。**不推荐**——因为这会引入源级概念到中枢模型中。

---

## 综合评分

| 维度 | 评分 | 关键问题 |
|------|------|----------|
| 架构对齐 | B | 整体对齐，但 ingest 中的硬编码适配器名称检查需修正 |
| 层次分离 | A- | 无循环依赖；compute_hash 位置不当（minor） |
| 接口设计 | B- | 无 etag 字段阻塞；push 签名不一致 |
| 可扩展性 | C+ | 缺少适配器工厂；M2 扩展需要重构多处 |
| 数据流 | B | 主流程完整；inbox 语义需澄清 |
| 可伸缩性 | B | 个人规模无问题；中文 FTS5 和 WAL 必须 M1 解决 |
| 设计决策 | B | 多源 source_ids 和版本号语义需关注 |

**总体**：有条件通过。需先解决 4 个 high 严重度问题（Finding 1, 3, 15, 20）再进入实现。
