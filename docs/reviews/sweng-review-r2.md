# khub M1 计划 Round 2 审查 —— 修复验证

- 审查日期：2026-07-09
- 审查文件：`2026-07-07-khub-m1.md`（更新版）
- 范围：仅验证 Round 1 发现项的修复情况

---

## High 级别

**Finding**: 2.1 — CanonicalDoc 缺少 `etag` 字段，`OcrAdapter.normalize()` 传入 `etag=raw.etag` 导致 TypeError
| **Verdict**: fixed
| **Note**: `CanonicalDoc` 已增加 `hash: str = ""` 字段（`models.py` 行 370），`normalize()` 改为 `hash=raw.etag`（`ocr.py` 行 590），将 `RawDoc.etag` 映射到 `CanonicalDoc.hash`。两种用法一致，不再抛出 TypeError。

---

**Finding**: 2.2 — `detect_changes` 使用 `getattr(last_state, "hash", None)` 对 `sqlite3.Row` 不生效，始终返回 True
| **Verdict**: fixed
| **Note**: 实现改为 `state = dict(last_state)` + `state.get("hash") or state.get("etag")`（`base.py` 行 472–474）。`dict(last_state)` 将 `sqlite3.Row` 转为普通字典后访问，行为正确。

---

**Finding**: 1.4 — `test_secret_from_env` 使用 `load_config.secret("IMA_TOKEN")`，`load_config` 是函数非模块，AttributeError
| **Verdict**: fixed
| **Note**: 测试改为 `from khub.config import secret; assert secret("IMA_TOKEN") == "secret123"`（`test_config.py` 行 925–927），导入正确的符号。

---

## Medium 级别

**Finding**: 1.1 — `conftest.py` 中 `test_fts5_available` 为测试函数，pytest 不收集，静默跳过
| **Verdict**: fixed
| **Note**: 改为了 `@pytest.fixture(autouse=True)`（`conftest.py` 行 81–84），每个测试前自动执行。FTS5 不可用时在 fixture 阶段抛出 `sqlite3.OperationalError`，测试会快速失败。

---

**Finding**: 2.3 — `sync_source` 冲突分支未更新 `sync_states`，下次同步重复检测到冲突
| **Verdict**: fixed
| **Note**: 冲突分支新增 `self.store.set_sync_state(adapter.name, canon.source_id, canon.hash, canon.hash)`（`engine.py` 行 794），与普通更新分支行为一致，避免重复冲突版本。

---

**Finding**: 2.4 — `store_document` 更新已存在文档时忽略 `parent_version` 参数，始终用 `existing["current_version"]`
| **Verdict**: fixed
| **Note**: 已改为 `parent = parent_version if parent_version is not None else existing["current_version"]`（`db.py` 行 219），尊重调用方传入的 `parent_version`。

---

**Finding**: 5.1 — 所有数据库操作无异常处理，disk full / 锁冲突直接 traceback
| **Verdict**: not fixed
| **Note**: `SyncEngine.ingest`（`engine.py` 行 674–683）和 `sync_source`（行 685–702）仍无 try/except 包裹。`cli.py` 的 `_store()` 增加了配置加载异常处理，但引擎层和 CLI 入口的顶层异常捕获均未添加。`db.py` 的 `search()` 增加了 `sqlite3.DatabaseError` 捕获（行 273），但这是局部而非引擎级异常处理。建议在 `ingest`/`sync_source` 中包裹 try/except，将异常转换为 `SyncResult(status="error", message=...)`，并在 `main()` 顶层捕获。

---

**Finding**: 5.2 — `_store()` 配置缺失时静默回退
| **Verdict**: fixed
| **Note**: 配置不存在时打印 `"警告: 配置文件 ... 不存在，使用默认配置"` 到 stderr（`cli.py` 行 1062–1063）。配置存在但解析失败时抛出 `RuntimeError`（行 1066）。用户现在能感知到配置状态。

---

**Finding**: 5.3 — `OcrAdapter.pull()` 附件读取无 I/O 隔离，单文件失败影响整个源
| **Verdict**: fixed
| **Note**: 单个附件读取已包裹 `try/except (IOError, PermissionError)`（`ocr.py` 行 579–581），捕获异常时 `logging.warning` 并跳过该附件继续处理后续文件。

---

## Low 级别

**Finding**: 7.3 — 缺少 `__main__.py`，`python -m khub` 不可用
| **Verdict**: fixed
| **Note**: 已新建 `khub/__main__.py`（行 1038–1043），内容为 `from khub.cli import main; ... sys.exit(main())`。`pyproject.toml` 也配置了 `[project.scripts]` 入口（行 65–66）。

---

## 额外发现的次生问题

以下为 R2 中新发现的、与修复相关的问题：

**Finding (new)**: R1 中提及的 `_now()` 格式问题已修复（`db.py` 行 151 增加了 `.f` 毫秒和 `Z` 后缀），但 `Store.__init__` 末尾的冗余 `self.conn.commit()`（行 166，`executescript` 隐式 COMMIT 后）以及 `compute_hash` 截断（行 147 已改为完整 hexdigest）也已修复。✅

**Finding (reminder)**: R1 发现 4.1（`store_ingest_version` 仅测试存在）、4.2（`cur` 命名混淆）、4.5（冗余 commit）三个 info 级别项未在代码片段中看到明显修改，但属于代码质量而非功能正确性问题，不影响 M1 功能可用性。

---

## 总结

| 级别 | 总数 | 已修复 | 未修复 |
|------|------|--------|--------|
| high | 3 | 3 | 0 |
| medium | 6 | 5 | 1（5.1） |
| low | 1 | 1 | 0 |

**唯一未修复项**：5.1（DB 操作无异常处理）。可以考虑在 M1 中放宽此项要求，改为在 `test_e2e_ingest_query_cli` 中验证正常路径覆盖足够的 DB 操作；或由实现者在任务 5/6 中添加引擎级 try/except 包裹。
