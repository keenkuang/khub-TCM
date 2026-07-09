# khub M1 架构评审报告 — 第二轮

- **评审者**：CodeBuddy（架构评审模式，R2）
- **日期**：2026-07-09
- **范围**：验证 R1 七项发现（3 high, 3 medium, 1 low）在更新计划 `2026-07-07-khub-m1.md` 中的修复情况 + 新增架构问题检查

---

## 一、R1 发现验证

### F1（high）：ingest 中硬编码适配器名称检查

- **Finding**：`engine.py` 的 `ingest()` 中有 `if adapter.name != "ocr"` 跳过 sync_states 写入，违反复合层"源无关"架构
- **Verdict**：**fixed**
- **Note**：硬编码名称检查已删除。`ingest()` 现在对所有适配器无条件写入 sync_states（`engine.py:681`），不再根据适配器名称做分支。原推荐方案 A（`should_track_sync_state()`）未被采用，改为更简方案——始终写入 sync_states。对 push-in 源而言这能正常工作，也解决了 R1 Finding 13（sync_states 缺失）的问题。确认通过。

---

### F2（medium）：缺失适配器工厂

- **Finding**：CLI 层硬编码适配器实例化（`OcrAdapter(args.book)`），M2 多源后难以维护
- **Verdict**：**partially fixed**
- **Note**：更新计划在末尾新增了"适配器工厂（推迟至 M2）"章节（第 1178-1194 行），提供了工厂接口的完整预留设计（`register()` / `create()` 模式），并明确标记为 M2 范围。CLI 中 `OcrAdapter` 和 `ObsidianAdapter` 的硬编码实例化在 M1 中保留未改。鉴于该问题 severity 为 medium 且 M1 只有一个 OCR 源，推迟至 M2 是可接受的折衷——只要 M2 实施前确实实现工厂并将 CLI 中的硬编码迁移过去。

---

### F3（high）：CLI 测试框架不匹配（click vs argparse）

- **Finding**：测试用 `click.testing.CliRunner` 但实现用 `argparse`，测试无法编译
- **Verdict**：**fixed**
- **Note**：测试已完全改用 `subprocess.run` + `python -m khub.cli`（第 1003-1025 行），零额外依赖。无 click 引用残留。实现与测试框架一致。

---

### F5（medium）：`_current_hash` 绕过 Store API

- **Finding**：引擎直接访问 `self.store.conn.execute()` 获取最新 hash，破坏封装
- **Verdict**：**fixed**
- **Note**：`Store` 新增了 `get_current_hash(doc_id)` 公共方法（`db.py:277-281`）。`engine.py:787` 已改为调用 `self.store.get_current_hash(canon.source_id)`。不再绕过 Store 接口。

---

### F11（low）：direction 枚举不一致（push-in 未定义）

- **Finding**：设计规格定义 `"two-way" | "read-only"`，但计划引入了 `"push-in"` 未同步
- **Verdict**：**fixed**
- **Note**：`base.py:453` 注释已明确列出三种方向（`"two-way" | "read-only" | "push-in"`）。`OcrAdapter` 设为 `direction = "push-in"`，`ObsidianAdapter` 设为 `direction = "two-way"`。`config.yaml.example` 的 sources 配置也包含了所有三种方向。注意：设计规格文件 `2026-07-07-khub-design.md` 本身未在本次评审范围内验证，建议确认该文件也已同步更新。

---

### F16（medium）：SQLite 缺少 WAL 模式

- **Finding**：`Store.__init__` 使用默认 `journal_mode=delete` 和 `timeout=5`
- **Verdict**：**fixed**
- **Note**：`db.py:162-163` 已添加：
  ```python
  self.conn.execute("PRAGMA journal_mode=WAL")
  self.conn.execute("PRAGMA busy_timeout=5000")
  ```
  与推荐方案一致。M2 多线程场景不再阻塞。

---

### F20（high）：CanonicalDoc 缺少 `etag` 字段 — `normalize()` 会抛 TypeError

- **Finding**：`OcrAdapter.normalize()` 传递 `etag=raw.etag` 但 `CanonicalDoc` 无 `etag` 字段
- **Verdict**：**fixed**
- **Note**：已采用 R1 推荐的方案 A——`normalize()` 将 `etag=raw.etag` 改为 `hash=raw.etag`（`ocr.py:590`）。`CanonicalDoc` 中有 `hash: str = ""` 字段（`models.py:370`），映射正确。TypeError 不再发生。

---

## 二、新增架构问题

### NF1（new，medium）：CLI `ls` 命令绕过 Store API

- **Finding**：`cli.py:1096` 访问 `store.conn.execute(...)` 直接执行 SQL，未使用 `Store` 的公共方法。这与 R1 F5 模式相同——下层模块的私有成员被上层直接访问。
  ```python
  # cli.py:1096 — 绕过 Store API
  for row in store.conn.execute("SELECT canonical_id, title FROM documents"):
  ```
- **Severity**：medium
- **Recommendation**：在 `Store` 上新增 `def list_documents(self, source_id: str | None = None) -> list[dict]` 公共方法，CLI 改为调用该接口。防止未来 Store 底层变更（如连接池切换、async 化）时 CLI 需要同步修改。

### NF2（minor）：`set_sync_state` etag 和 hash 使用相同值

- **Finding**：`engine.py` 多处调用 `self.store.set_sync_state(adapter.name, canon.source_id, canon.hash, canon.hash)`，将 `canon.hash` 同时作为 `etag` 和 `hash` 参数传入。从架构上讲，`etag` 应是源级指纹（如 HTTP ETag），`hash` 是内容指纹。对于 push-in OCR 源二者相同，但 M2 引入 read-only/two-way 源（Quip API ETag ≠ 内容 hash）时需要区分。
- **Severity**：low
- **Recommendation**：在 M2 引入远程 API 适配器前，将引擎中的 `set_sync_state` 调用改为明确区分两个参数：`etag` 从适配器获取（`raw.etag` 或适配器提供的指纹），`hash` 使用 `canon.hash`。当前方案对 M1 无害，但需在 M2 前修正。

---

## 三、综合评估

| R1 发现 | Severity | 状态 | 说明 |
|---------|----------|------|------|
| F1 — 硬编码适配器检查 | high | fixed | 已删除，改为无条件写入 sync_states |
| F2 — 缺失适配器工厂 | medium | partially fixed | 接口已设计并标记为 M2 TODO，CLI 硬编码保留 |
| F3 — CLI 测试框架不匹配 | high | fixed | click → subprocess，框架一致 |
| F5 — _current_hash 绕过 | medium | fixed | Store.get_current_hash() 已实现并使用 |
| F11 — direction 枚举 | low | fixed | 三种方向统一标注 |
| F16 — 无 WAL 模式 | medium | fixed | journal_mode=WAL + busy_timeout=5000 |
| F20 — CanonicalDoc 缺 etag | high | fixed | 方案 A：hash=raw.etag |
| NF1 — CLI ls 绕过 Store API | new | medium | `store.conn.execute()` 在 CLI 中直接使用 |
| NF2 — set_sync_state etag/hash | new | low | 两参同值，M2 前需处理 |

**R2 总体状态：6 fixed / 1 partially fixed / 2 new findings**

原 R1 的 3 个 high 严重度阻塞问题（F1、F3、F20）均已正确修复。F2（适配器工厂）的 deferred 方案可接受但需 M2 严格执行。新增 NF1 值得在 M1 中优先修正（与 F5 同模式，修复成本低）。
