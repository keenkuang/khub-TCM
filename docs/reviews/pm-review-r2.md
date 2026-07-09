# PM Review R2: khub M1 计划 — R1 发现项修复验证

- 评审日期：2026-07-09
- 基于计划：`2026-07-07-khub-m1.md`
- 验证对象：R1 评审 (`pm-review.md`) 中的 8 项发现

---

## 验证结果

### 1. FTS5 可用性回退路径 (high)
**R1 发现**：计划含 FTS5 可用性检查，但未定义回退策略的验收标准。

**检查点**：运行时检查已添加 → 回退决策？
**当前计划**：任务 1 步骤 3 预期说明中写道：
> 预期：PASS。若 FTS5 不可用，停止并向用户报告（需换编译版 sqlite 或用 LIKE 回退——本期假设 FTS5 可用）。

`_ensure_fts5()` 方法已实现运行时检查，不可用时抛出 `RuntimeError` 并附带安装指引。

**Verdict**: partial
**Note**: 运行时检测 (`_ensure_fts5`) 已添加且附带错误安装指引，符合"最小阻断"要求。但"LIKE 回退"仅在注释中提及，无实际实现路径，也无硬性决策记录（"M1 不实现回退"vs"M2 补 LIKE 回退"）。如果团队对 FTS5 不可用的容忍度是"阻断即可"，则此项可通过；如果需要自动降级路径，仍需补充。

---

### 2. CLI 测试框架不匹配 (medium)
**R1 发现**：测试代码使用 `click.testing.CliRunner`，实现使用 `argparse`，存在冲突。

**检查点**：click → subprocess 已修正？
**当前计划**：任务 9 测试 (`tests/test_cli.py`) 使用 `subprocess.run` 调用 `python -m khub.cli`，实现使用 `argparse`，二者一致。计划明确标注"用 `argparse` 而非 click 以零额外依赖；测试用 subprocess 调用 `python -m khub.cli`。"

**Verdict**: fixed ✅
**Note**: 测试方式与实现完全对齐，无框架冲突。CLI 入口通过 `pyproject.toml` 的 `[project.scripts]` + `khub/__main__.py` 双重支持。

---

### 3. sync 为占位实现 (medium)
**R1 发现**：`khub sync` 打印占位文字"sync 完成（M1 仅支持 ocr 源）"，无实际行为，可能误导用户认为同步已完成。

**检查点**：占位信息改进？
**当前计划**：任务 9 `cli.py` 中 `sync` 分支改为：
> `print("M1 仅支持 OCR push-in 源，请使用 \`khub ingest --book <目录>\` 替代 sync。其他源的 sync 功能在 M2 实现。")`

验收清单中也包含 `khub sync` → 输出非错误提示（友好提示）。

**Verdict**: fixed ✅
**Note**: 新提示明确指出了替代命令（`khub ingest --book`），并将 sync 功能归入 M2 范围，消除了误导风险。验收清单中也有对应项。

---

### 4. 验收清单缺失 (medium)
**R1 发现**：缺少显式验收清单，DoD 仅隐含于"测试全部通过"。

**检查点**：任务 10 已补充验收清单？
**当前计划**：任务 10 步骤 3 新增了完整的 "M1 验收清单"，包含 8 个手动验收项：
- `pytest -v` 全部通过
- `khub ingest --book <含 .md 的真实目录>` → created
- `khub query "关键词"` → 返回结果
- `khub conflicts` → "无冲突"
- `khub ls` → 列出文档
- `khub version <doc_id>` → 列出版本
- `khub sync` → 友好提示
- 不存在 book 目录 → 非零退出码 + 明确错误

**Verdict**: fixed ✅
**Note**: 验收清单覆盖了 R1 推荐的边界条件（不存在目录错误处理）和功能验证项。对比 R1 推荐还多了尝试不存在的 book 目录测试——内容比推荐的更完整。

---

### 5. 任务 10 tempfile.mkdtemp 无清理 (low)
**R1 发现**：集成烟雾测试使用 `tempfile.mkdtemp()` 无清理逻辑。

**检查点**：已统一为 `tmp_path` fixture？
**当前计划**：任务 10 的端到端测试使用 `def test_e2e_ingest_query_cli(tmp_path)`，无任何 `tempfile.mkdtemp()` 调用。所有测试均使用 pytest 的 `tmp_path` fixture。

**Verdict**: fixed ✅
**Note**: `tmp_path` 统一使用，无手动清理问题。

---

### 6. 完成定义 (DoD) 验收清单 (medium)
**R1 发现**：DoD 需显式化，建议加验收清单而非仅"测试通过"。

**检查点**：验收清单已添加到 DoD？
**当前计划**：同 #4。任务 10 步骤 3 的验收清单即为显式的 DoD 标准。

**Verdict**: fixed ✅
**Note**: 验收清单使 DoD 从隐性变为显式，覆盖手动验证和边界条件。R2 建议补充：考虑在计划开头或结尾的"自检"部分也引用该验收清单，形成闭环。

---

### 7. 范围差距：配置加载未列在设计规格 M1 中 (low)
**R1 发现**：配置加载模块（任务 8）在设计规格 M1 段落未明确列出。

**检查点**：设计规格中补充说明 or 计划中有注释说明此为超范围项？
**当前计划**：任务 8（配置加载）已完整实现（config.py + config.yaml.example + 测试），但计划中未标注此项超出原设计规格范围。

**Verdict**: not fixed ❌
**Note**: 配置模块本身被纳入是正确且必要的决策，但计划中没有任何注释说明"此项超出设计规格 M1 范围"。R1 建议"在设计规格的 M1 段落中补一句 `config 加载`"的文档对齐工作未被执行。建议在计划开头的"范围"或"架构"段落中注明此项，保持两文档对齐。

---

### 8. 适配器工厂推迟但 TODO 未记录 (low)
**R1 发现**：CLI 中硬编码 `OcrAdapter`/`ObsidianAdapter`，需要记录适配器注册机制推迟到 M2 的决策。

**检查点**：TODO 已记录？
**当前计划**：计划末尾新增独立章节 "适配器工厂（推迟至 M2）"，含完整代码桩和接口预留，明确指出 M2 引入工厂模式。

**Verdict**: fixed ✅
**Note**: 适配器工厂的推迟决策已清晰文档化，包含注册/创建接口的代码桩和 defer 理由（M2 新增源时引入）。同时也为 `SourceAdapter` 增加了 `from_config` 方法的预期扩展点（工厂中 `cls.from_config(source_cfg)` 调用预留）。

---

## 汇总

| # | 发现 | Severity | Verdict |
|---|------|----------|---------|
| 1 | FTS5 回退路径 | high | partial — 运行时检测 + 报错已实现，LIKE 回退仅注释提及无实现决策 |
| 2 | CLI 测试框架不匹配 | medium | fixed — subprocess + argparse 统一 |
| 3 | sync 占位误导 | medium | fixed — 提示改为止明确引导到 ingest |
| 4 | 验收清单缺失 | medium | fixed — 8 项验收清单已添加 |
| 5 | tempfile.mkdtemp 未清理 | low | fixed — 统一 tmp_path |
| 6 | DoD 未显式化 | medium | fixed — 验收清单即 DoD |
| 7 | 配置加载超范围未标注 | low | not fixed — 无文档对齐注释 |
| 8 | 适配器工厂 TODO 未记录 | low | fixed — 清晰文档化推迟决策 |

## 结论

8 项 R1 发现中 **6 项已修复**，**1 项部分修复**（FTS5 回退路径仍需决策），**1 项未修复**（配置加载范围标注）。整体修复率 75%，M1 计划质量较 R1 有显著提升。建议在实施前解决 FTS5 回退路径的决策问题，并在计划中补一条范围注释。
