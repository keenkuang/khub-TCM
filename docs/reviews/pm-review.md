# PM Review: khub M1 实现计划

- 评审日期：2026-07-09
- 评审对象：`2026-07-07-khub-design.md` (设计规格) × `2026-07-07-khub-m1.md` (实现计划)
- 评审范围：M1 阶段项目管理维度

---

## 1. 范围校验 (Scope Validation)

- **Finding**: 计划覆盖了设计规格中 M1 声明的全部交付项（SQLite+FTS5、版本化、适配器接口、OCR 适配器、Obsidian stub、CLI 六子命令、Sync 引擎+冲突、单测），无遗漏。
- **Severity**: info
- **Recommendation**: 无。范围对齐良好。

---

- **Finding**: 计划在规格 M1 范围之外额外纳入了配置加载模块（任务 8：config.py + config.yaml.example + 环境变量密钥），这在设计规格"分期实现"M1 段落中未明确列出，但属于 CLI 可运行的必要前置依赖。
- **Severity**: low
- **Recommendation**: 将配置加载纳入是合逻辑的，建议在设计规格的 M1 段落中补一句「config 加载」以便两处文档对齐。这不影响交付，但二者作为参考标准应一致。

---

- **Finding**: 设计规格 M1 要求 CLI 支持 `sync` 子命令，但计划中任务 9 的 CLI 实现里 `sync` 仅打印占位文字"sync 完成（M1 仅支持 ocr 源）"，不执行任何实际同步操作。用户调用 `khub sync` 会得到一个空操作结果。
- **Severity**: medium
- **Recommendation**: 要么让 `khub sync` 在 M1 中实际遍历已配置的源（至少 OCR push-in 可做 get-effective-pull + store），要么将 `sync` 的命令行行为改为有意义的提示（如"OCR 为 push-in 源，无需 sync；其他源待 M2 实现"）。当前占位文字可能让用户误以为同步已完成。

---

## 2. 任务依赖 (Task Dependencies)

- **Finding**: 计划中任务 1（骨架+FTS5）和任务 2（数据模型）为顺序排列，这是正确的——任务 1 的 `db.py` 在步骤 6 中 `from .models import CanonicalDoc`，因此必须在任务 2 的 `models.py` 就位后才能正常工作。无法并行。
- **Severity**: info
- **Recommendation**: 计划当前顺序已正确。如果未来要为提速并行化，需要将 `CanonicalDoc` 的接口定义为任务 2 优先产出的前置条件，或者让 `db.py` 暂时使用本地类型并后续替换。当前 M1 规模小，顺序执行即可。

---

- **Finding**: 任务 5（Sync 引擎基础同步）依赖任务 4（OCR 适配器）和任务 1（Store），任务 6（冲突多版本）依赖任务 5。任务的线性依赖关系在计划中表达清楚，无缺失。
- **Severity**: info
- **Recommendation**: 可考虑在任务 5 和任务 6 的标题或描述中标注前置依赖，以减少实现时的上下文切换成本。当前依赖关系仅可通过文件结构推断。

---

## 3. 里程碑 (Milestones)

- **Finding**: 每个任务以可独立验证的 Commit 结束，提交信息遵循 Conventional Commits 格式且描述了明确的原子增量。这是优秀的实践。
- **Severity**: info
- **Recommendation**: 继续保持。

---

- **Finding**: 任务 5 的 Commit 提交不完整的 Sync 引擎（无冲突处理），紧接着任务 6 的 Commit 补充冲突处理。两个 Commit 之间系统处于"可同步但不冲突检测"的状态，不是一个可展示的里程碑。
- **Severity**: low
- **Recommendation**: 考虑合并任务 5 和任务 6 为一个 Commit（`feat(M1): sync engine with conflict multi-version`），使每个里程碑交付的功能是完整的。或者调整任务 5 的 Commit 表述为 `feat(M1): sync engine ingest (partial)` 以明确其不完整性。

---

## 4. 风险识别 (Risk Identification)

- **Finding**: FTS5 可用性为假设前提。计划中包含 FTS5 可用性检查，但未定义回退策略的验收标准。若系统 sqlite3 缺少 FTS5 编译，M1 无法交付。
- **Severity**: high
- **Recommendation**: 在任务 1 的步骤 2/3 中增加明确的分支路径：如果 FTS5 不可用，是"停止并报告用户安装 FTS5 版 sqlite3"，还是"回退到 LIKE 查询方案并延迟 FTS5 到 M2"。建议写下具体决策并记入规格。

---

- **Finding**: CLI 测试代码（任务 9 步骤 1）使用 `click.testing.CliRunner`，但实际实现改用 `argparse`。计划中已注明这一不一致性，但未明确测试编写者应使用哪个测试框架。
- **Severity**: medium
- **Recommendation**: 在任务 9 的测试步骤中直接用实际的测试方式（`subprocess.run`）写测试用例，而不是先写基于 click 的测试再临时纠正。或统一使用 click。当前的设计会导致实现者在步骤 1 写一套测试，步骤 2 运行失败，步骤 3 发现实现与测试框架不匹配，需要回头重写测试——浪费一个 TDD 循环。

---

- **Finding**: 无数据库 schema 迁移策略。M1 创建了 schema，但在 M2–M5 中如果 schema 发生变化，当前没有版本化迁移机制。个人工具的迁移需求较低，但不记录决策本身有风险。
- **Severity**: low
- **Recommendation**: 在 `Store.__init__` 中加一个 `schema_version` 机制（或至少记录一条设计决策：M1–M5 采用 schema destroy+recreate vs 手动 migrate 脚本），避免后续阶段无意中破坏已入库数据。

---

- **Finding**: 集成烟雾测试（任务 10）使用 `tempfile.mkdtemp()` 无清理逻辑。测试多次运行后会在 `/tmp` 留下垃圾。
- **Severity**: low
- **Recommendation**: 使用 `pytest` 的 `tmp_path` fixture 替代 `tempfile.mkdtemp()`，或增加 `shutil.rmtree` 清理。这与测试代码风格一致（其余测试均使用 `tmp_path`）。

---

## 5. 估算合理性 (Estimation Reasonability)

- **Finding**: 10 个任务 × 各 4-5 步（TDD 红-绿-重构-提交），粒度一致、节奏可预测。每个任务的目标是单一 Python 文件或 2-3 个文件的联动，工作单元大小合理。
- **Severity**: info
- **Recommendation**: 估算合理。如果实施者熟练，每任务约 30-60 分钟，M1 总计约 5-10 小时纯编码时间（含测试）。建议用此估算设定首次冲刺预期。

---

- **Finding**: 任务 10（集成烟雾测试与收尾）仅 3 步，明显短于其他任务。其作用更像是验收步骤而非开发任务。
- **Severity**: low
- **Recommendation**: 将任务 10 降级为任务 9 的收尾步骤，或改称为"M1 验收"(M1 Acceptance) 以反映其性质差异。当前它与其他 9 个开发任务并列，在进度跟踪中可能产生误导（会看起来只剩 1 个任务，实际是 1 个验证步骤）。

---

## 6. 完成定义 (Definition of Done)

- **Finding**: 计划的 DoD 仅隐含于"全部测试通过"。缺少以下维度：(a) 端到端手动验证（如 `khub ingest --book <real-dir>; khub query <keyword>` 在真实目录上通过）；(b) 边界条件验证（如空目录、不存在目录、超大文件、非 UTF-8 编码）；(c) 错误路径验证（如密钥缺失、YAML 格式错误、只读适配器调用 `push`）。
- **Severity**: medium
- **Recommendation**: 在任务 10 中显式定义 M1 验收清单：

  ```
  - [ ] pytest 全部通过
  - [ ] 手动运行 `khub ingest --book <含 .md 的真实目录>` → 输出 created
  - [ ] 手动运行 `khub query "关键词"` → 返回结果
  - [ ] 手动运行 `khub conflicts` → 输出"无冲突"
  - [ ] 手动运行 `khub ls` → 列出文档
  - [ ] 手动运行 `khub version <doc_id>` → 列出版本
  - [ ] 尝试 `khub sync` → 输出非错误提示
  - [ ] 尝试不存在的 book 目录 → CLI 返回非零退出码且给出明确错误
  ```

---

## 7. 干系人价值 (Stakeholder Value)

- **Finding**: OCR 入库 + FTS5 全文检索构成有意义的端到端闭环。用户可在 M1 结束后将 KZOCR 系统的产出书目录通过 `khub ingest` 导入并搜索，这是可感知的交付价值。
- **Severity**: info
- **Recommendation**: M1 的可用性很好。在 M1 交付说明中强调这一端到端流程，让用户立即看到成果。

---

- **Finding**: `khub sync` 在 M1 中为占位实现，而它却是 CLI 的第一个子命令。用户大概率会先敲 `khub sync` 然后得到一个空操作结果，这会降低第一印象。
- **Severity**: medium
- **Recommendation**: 见范围校验中的同步建议（Finding #1）。若 `sync` 在 M1 无法实现有意义的行为，考虑将其从 M1 CLI 中暂时移除并增加使用说明（"M1 仅支持 ingest + query；sync 将在 M2 支持多个源后上线"），避免用户预期落差。

---

## 8. 差距分析 (Gap Analysis)

- **Finding**: 设计规格 M1 要求「单测 + 用临时 vault / 测试库验证」。计划覆盖了单测且使用 tmp_path 隔离临时目录，但未显式覆盖"用临时 vault 验证"——虽然 tmp_path 可模拟 vault 结构，但 Obsidian 专用的端到端测试（如创建一个临时 `.obsidian/` 目录结构、验证适配器正确识别）未在 M1 中定义。
- **Severity**: low
- **Recommendation**: 在任务 7（Obsidian 适配器）中补充一个测试，验证当传入有效（但不存在的）vault 路径时 `pull()` 抛出正确错误。当前测试仅覆盖 `vault_path=None` 的情况，未覆盖"vault 路径存在但 Obsidian 未安装"的边界。

---

- **Finding**: 设计规格中 M1 的「适配器统一接口」在计划中定义为 Python ABC（任务 3），但未包含适配器注册/发现机制（如按 `type` 字符串自动加载适配器）。CLI 中硬编码了 `OcrAdapter` 和 `ObsidianAdapter` 的引用——这在仅有 2 个适配器时可行，但说明计划在「适配器发现的通用性」上较设计规格有所简化。
- **Severity**: low
- **Recommendation**: 当前规模的简化是可接受的。建议在任务 8（config 加载）或任务 9（CLI）旁边加一条注释/TODO，明确适配器注册机制推迟到 M2（当有 ≥3 个适配器时）。避免后续阶段忘记这个设计决策。

---

## 总结

| 维度 | 评估 | 关键改进 |
|------|------|---------|
| 范围校验 | ✅ 对齐良好 | 补 config 到设计规格；sync 占位行为需明确 |
| 任务依赖 | ✅ 正确顺序 | 无变更必要 |
| 里程碑 | ✅ 高质量 Commit | 可考虑合并任务 5/6 |
| 风险识别 | ⚠️ 中等 | FTS5 回退路径未定义；CLI 测试框架不一致 |
| 估算合理性 | ✅ 合理 | 5-10 人时 |
| 完成定义 | ⚠️ 需显式化 | 建议加验收清单而非仅"测试通过" |
| 干系人价值 | ✅ 端到端有价值 | sync 占位可能影响第一印象 |
| 差距分析 | ✅ 差距小 | 适配器注册机制需记录后续决策 |

**总体判研：M1 实现计划结构清晰、范围正确，可以执行。** 上述 medium 及以上发现建议在开始编码前解决，其余可纳入后续迭代改进。
