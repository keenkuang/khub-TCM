# khub M1 实现设计与计划 —— 代码质量审查

- 审查日期：2026-07-09
- 审查范围：`2026-07-07-khub-design.md`（设计规格）+ `2026-07-07-khub-m1.md`（实现计划）
- 审查性质：静态审查（仅读设计文档与代码片段，未运行）

---

## 1. TDD 一致性

**发现 1.1**：`conftest.py` 中包含测试函数 `test_fts5_available`。

- **Severity**: medium
- **说明**：`conftest.py` 文件专用于 pytest fixture 和钩子，pytest **不收集其中的测试函数**。该验证将静默跳过，FTS5 不可用时要到 `init_schema()` 运行时才报错。
- **Recommendation**: 将 `test_fts5_available` 移到 `test_db.py`，或使用 `pytest_configure` 钩子在 `conftest.py` 中做前置检查并 `pytest.exit()`。

**发现 1.2**：每个任务都遵循了「红 → 绿 → 提交」TDD 循环，测试先于实现编写。✅

**发现 1.3**：`test_obsidian_interface_present` 只检查了属性存在性而未验证方法签名可调用。

- **Severity**: low
- **Recommendation**: 补充 `callable(a.normalize)` 断言或在极端情况下实际调用一次（即使抛 `NotImplementedError`）。

**发现 1.4**：`test_secret_from_env` 调用形式 `load_config.secret("IMA_TOKEN")` 但在 `config.py` 中 `load_config` 是一个函数而非模块，`load_config.secret` 不存在。

- **Severity**: high
- **说明**：该测试将因 `AttributeError: 'function' object has no attribute 'secret'` 而失败。
- **Recommendation**: 将测试改为 `from khub.config import secret` 或 `from khub import config; config.secret("IMA_TOKEN")`。

---

## 2. 代码正确性（Bug 与边角情况）

**发现 2.1**：`CanonicalDoc` 缺少 `etag` 字段，但 `OcrAdapter.normalize()` 传入了 `etag=raw.etag`。

- **Severity**: high
- **说明**：`khub/models.py` 中 `CanonicalDoc` 是 dataclass，未定义 `etag` 字段。`ocr.py` 第 543 行调用 `CanonicalDoc(..., etag=raw.etag, ...)` 将抛出 `TypeError: __init__() got an unexpected keyword argument 'etag'`，导致 OCR 注入彻底不可用。
- **Recommendation**: 在 `CanonicalDoc` 中增加 `etag: str = ""` 字段，或将 `raw.etag` 映射到 `hash` 字段。

**发现 2.2**：`detect_changes()` 对 `sqlite3.Row` 使用 `getattr` 访问列值。

- **Severity**: high
- **说明**：`base.py` 第 432–433 行：
  ```python
  old = getattr(last_state, "hash", None) or getattr(last_state, "etag", None)
  ```
  `sqlite3.Row` 对象**不支持属性访问**（仅在 Python ≥ 3.12 的实验性实现中有限度支持），`getattr(row, "hash", None)` 始终返回 `None`，因此 `detect_changes` 对任何已同步文档都会**始终返回 `True`**，导致每次 `sync_source` 都产生新版本（无冲突时也如此）。
- **Recommendation**: 改为 `last_state["hash"] if "hash" in last_state.keys() else last_state["etag"]`，或使用 `dict(last_state).get("hash")`。

**发现 2.3**：`sync_source` 的冲突分支中，冲突后未更新 `sync_states`。

- **Severity**: medium
- **说明**：`engine.py` 冲突分支（`if hub_changed`）在创建 source 版本后调用 `mark_conflict`，但**没有调用 `set_sync_state`**。下一次 `sync_source` 时，`sync_states` 里的 hash 仍是旧值，`detect_changes` 会重复检测到变更，导致**每次同步都重复产生新冲突版本**。
- **Recommendation**: 冲突分支中也应调用 `self.store.set_sync_state(adapter.name, canon.source_id, canon.hash, canon.hash)`。

**发现 2.4**：`store_document` 在更新已存在文档时忽略 `parent_version` 参数。

- **Severity**: medium
- **说明**：`db.py` 第 191–192 行，当文档已存在时，`parent = existing["current_version"]`，不使用调用方传入的 `parent_version`。冲突场景中新建 source 版本时应以 `current_version`（即 hub 修改后的最新版本）为父版本——目前的行为在这一场景恰好是对的，但限制了引擎未来做版本树精确追踪的能力（例如基于特定旧版本做分支）。
- **Recommendation**: 将逻辑改为 `parent = parent_version if parent_version is not None else existing["current_version"]`。

---

## 3. 测试质量

**发现 3.1**：`test_conflict_creates_two_versions_and_flag` 依赖 `store_ingest_version` 来模拟 hub 修改，但未验证两个冲突版本的内容和 hash 值。

- **Severity**: low
- **Recommendation**: 断言 `v1["content"]` 和 `v2["content"]` 各为 "hub-edit" / "remote-edit"，确保 hash 不同。

**发现 3.2**：`test_sync_source_noop_when_unchanged` 依赖于 `detect_changes` 的正确性。由于发现 2.2 中的 bug，该测试在当前代码下也会**失败**（重复同步将创建新版本而非空操作）。

- **Severity**: high
- **说明**：测试依赖的底层实现有 bug，测试本身逻辑正确但**在 bug 修复前将持续失败**。

**发现 3.3**：缺少以下边界测试：

| 缺失测试 | 影响 |
|---------|------|
| `search()` 无匹配结果时返回空列表 | 空查询处理 |
| `get_document()` 文档不存在返回 `None` | 空安全 |
| `Store` 用不可写路径初始化 | 磁盘/权限错误隔离 |
| 大内容文档的 FTS5 检索（>100KB） | 检索性能/截断 |
| `normalize` 收到空 title / 空 content | 适配器健壮性 |
| 同一秒内多次 `store_document` 的 `updated_at` 精度 | 时间排序 |
| 空附件目录 | OCR 适配器边界 |

- **Severity**: medium
- **Recommendation**: 补充以上边界测试，确保测试覆盖率覆盖正常路径、空路径和异常路径。

**发现 3.4**：CLI 测试使用了 `click.testing.CliRunner` 的代码片段（`tests/test_cli.py` 第 960–962 行），但正式实现使用 `argparse`。

- **Severity**: low
- **说明**：计划中已注明"正式实现按 argparse 走，测试对应调整"。但文档中未展示调整后的测试代码，存在实现与测试不同步的风险。
- **Recommendation**: 确认最终的 CLI 测试使用 `subprocess` 调用 `python -m khub.cli`（如任务 10 烟雾测试所示），并删除 `CliRunner` 引用。

---

## 4. Python 惯用法与类型问题

**发现 4.1**：`store_ingest_version` 是无意义的简化封装。

- **Severity**: info
- **说明**：
  ```python
  def store_ingest_version(self, doc: CanonicalDoc) -> int:
      return self.store.store_document(doc)
  ```
  只为了测试而存在。暴露了"为测试加方法"的反模式。
- **Recommendation**: 测试中直接调用 `eng.store.store_document(hub_doc)` 并删除该方法。

**发现 4.2**：`db.py` 第 180 行命名混淆：`cur = self.conn`——变量名 `cur` 暗示它是一个 cursor，实际上它引用的是 connection 对象。用 `connection` 调用 `cur.execute()` 虽然可行（connection 代理 execute），但意图不清晰。

- **Severity**: info
- **Recommendation**: 命名改为 `con = self.conn` 或 `conn = self.conn`。

**发现 4.3**：`detect_changes` 类型标注 `Optional[object]` 过于宽泛。

- **Severity**: low
- **说明**：`object` 无法提供任何类型安全保障。实际期望的类型是 `Optional[sqlite3.Row]`。
- **Recommendation**: 改为 `from sqlite3 import Row; last_state: Optional[Row]`，并在方法内部用 `last_state["hash"]` 等索引方式访问。

**发现 4.4**：`compute_hash` 截断 SHA256 到 16 个 hex 字符（64 位）。

- **Severity**: low
- **说明**：对于一个个人知识库（预计 < 10^5 文档），64 位冲突概率可以接受（约 10^-9 @ 10^5 条）。但对于 hash 在版本树中承担去重和变更检测关键角色，使用完整 SHA256 的成本极低且更安全。
- **Recommendation**: 使用完整 64 字符 hexdigest，或在配置中提供截断长度选项。

**发现 4.5**：`executescript` 隐式 COMMIT 后紧跟显式 `self.conn.commit()`。

- **Severity**: info
- **说明**：`conn.executescript()` 在开始执行前会隐式发送一条 COMMIT。之后的显式 `commit()` 是冗余操作。
- **Recommendation**: 删除第 177 行的 `self.conn.commit()`。

---

## 5. 错误处理

**发现 5.1**：所有数据库操作均无异常处理。

- **Severity**: medium
- **说明**：如果磁盘满、数据库锁定（多进程并发）、或权限不足，`sqlite3.OperationalError` 将直接向上冒泡，**无任何用户友好的错误消息**，在 CLI 中会以 traceback 形式暴露给用户。
- **Recommendation**: 在 `SyncEngine` 的 `ingest`/`sync_source` 方法中包裹 try/except，将异常转换为 `SyncResult(status="error", message=...)`，并确保 CLI 入口也捕获顶层异常。

**发现 5.2**：`_store()` 隐式静默回退。

- **Severity**: medium
- **说明**：`cli.py` 第 1005–1007 行：
  ```python
  cfg = load_config(CONFIG_PATH) if os.path.exists(CONFIG_PATH) else {"db": "/home/keen/khub/khub.db"}
  ```
  - 如果 `CONFIG_PATH` 存在但内容非法 YAML → 未捕获的 `yaml.YAMLError`
  - 如果 `CONFIG_PATH` 不存在 → 完全静默回退到默认 DB 路径，用户不知道在用什么配置
- **Recommendation**: 在缺失配置时打印警告（`print(f"Warning: {CONFIG_PATH} not found, using defaults", file=sys.stderr)`），对非法配置抛出带上下文的错误。

**发现 5.3**：`OcrAdapter.pull()` 中附件读取未处理 I/O 异常。

- **Severity**: medium
- **说明**：`ocr.py` 第 534 行 `f.read_bytes()` 在附件文件被占用/权限不足时抛出 `PermissionError`/`IOError`，导致**整个源的 `pull()` 失败**（适配器失败隔离应只影响单源而非单文件）。
- **Recommendation**: 对单个附件包裹 try/except，捕获异常时记录日志并跳过该附件继续。

**发现 5.4**：`OcrAdapter.__init__` 不做 `book_dir` 有效性验证。

- **Severity**: low
- **说明**：如果传入的路径不存在，`pull()` 只是返回空列表，调用方无法区分"目录为空"和"路径错误"。
- **Recommendation**: 在 `__init__` 或 `pull()` 开始处验证 `self.book_dir.is_dir()`，不满足时报错。

---

## 6. 预审已知问题验证

| 已知问题 | 状态 | 说明 |
|---------|------|------|
| `CanonicalDoc` 缺少 `etag` 字段 | **确认，未修复** | 见发现 2.1 |
| `_now()` 秒级精度 | **确认，未修复** | `time.strftime("%Y-%m-%dT%H:%M:%S")` 无毫秒。影响：同一秒内多个文档的 `updated_at` 相同，损失排序精度；也缺少时区后缀（无 `Z`）。 |
| `_store()` 缺失配置时错误不清晰 | **确认，未修复** | 见发现 5.2。静默回退 + 非法配置触发 YAML 异常。 |

**关于 `_now()` 的额外说明**：当前格式 `"2026-07-09T12:34:56"` 缺少时区标识符。严格 ISO 8601 UTC 应为 `"2026-07-09T12:34:56Z"`。建议改为带毫秒和 `Z` 的格式以提升可读性和排序准确性。

---

## 7. M1 规格覆盖度

**已覆盖的 M1 需求：**
- SQLite + FTS5 schema、`document_versions` 版本化 — Task 1, 6 ✅
- 适配器统一接口 — Task 3 ✅
- Obsidian 适配器 stub — Task 7 ✅
- OCR 入库适配器（push-in）— Task 4 ✅
- CLI：`sync` / `query` / `ingest` / `ls` / `conflicts` / `version` — Task 9 ✅
- Sync 引擎 + 冲突多版本 — Task 5, 6 ✅
- 测试 — Task 1–10 ✅

**遗漏或需关注的项：**

**发现 7.1**：`sources` 表从未被写入。

- **Severity**: low
- **说明**：`db.py` 创建了 `sources` 表（第 157–158 行），但全计划中没有任何代码向其中插入数据（配置加载不写入 `sources` 表，引擎初始化也不做）。该表在 M1 持续为空。
- **Recommendation**: 这本身不阻塞 M1 功能（引擎直接从 `sync_states` 和 `documents` 恢复工作），但建议在 `SyncEngine.__init__` 中增加可选注册逻辑，或明确记录"`sources` 表当前仅供前瞻使用"。

**发现 7.2**：`sync --source` 子命令在当前实现中仅打印占位消息。

- **Severity**: low（M1 设计行为）
- **说明**：`cli.py` 第 1026 行 `print("sync 完成（M1 仅支持 ocr 源）")`。这意味着 `khub sync` 不会自动遍历 config.yaml 中的源来执行同步。M1 用户只能通过 `khub ingest --book <dir>` 来使用 OCR 适配器。
- **Recommendation**: 确保该行为在计划中明确标注为 M1 范围限制，或在 M2 计划中安排 `sync` 使用配置中的源列表。

**发现 7.3**：缺少 `__main__.py` 入口点。

- **Severity**: low
- **说明**：项目没有 `khub/__main__.py`，`python -m khub` 将失败。用户必须使用 `python -m khub.cli`。
- **Recommendation**: 添加 `khub/__main__.py`：`from khub.cli import main; import sys; sys.exit(main())`，并在 `pyproject.toml` 中增加 `[project.scripts]` 入口：`khub = "khub.cli:main"`。

---

## 总结

| 严重级别 | 数量 | 关键项 |
|---------|------|--------|
| **high** | 3 | 发现 2.1（CanonicalDoc 缺 etag → TypeError），发现 2.2（getattr 不可用于 sqlite3.Row → detect_changes 永远为真），发现 1.4（load_config.secret 调用错误 → 测试失败） |
| **medium** | 7 | 发现 1.1（FTS5 测试写入 conftest → 静默跳过），发现 2.3（冲突未更新 sync_states → 重复冲突），发现 2.4（parent_version 被忽略），发现 5.1/5.2/5.3（DB/配置/附件错误处理缺失） |
| **low** | 7 | 发现 1.3/3.1/3.2/3.3/3.4/4.4/5.4 |
| **info** | 3 | 发现 4.1/4.2/4.5 |

**必须在实现前修复的 3 个 high 级别问题**，否则项目无法在 M1 达到可用状态。特别是发现 2.1 和 2.2 直接影响 OCR 适配器写入和同步引擎的核心逻辑。
