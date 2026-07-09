# khub M1 实施计划 — 多角色评审汇总报告

- **评审日期**: 2026-07-09
- **评审范围**: `docs/superpowers/specs/2026-07-07-khub-design.md` + `docs/superpowers/plans/2026-07-07-khub-m1.md`
- **评审角色**: 架构师(architect) / 软件工程师(sweng) / 安全工程师(netsec) / 运维工程师(ops) / 项目经理(pm)
- **状态**: **有条件通过** — 需先解决关键问题后进入实现

---

## 一、评审统计

| 角色 | High | Medium | Low | Info | 总计 |
|------|------|--------|-----|------|------|
| 架构师 | 4 | 7 | 2 | 0 | 20 |
| 软件工程师 | 3 | 7 | 7 | 3 | 20 |
| 安全工程师 | 0 | 3 | 3 | 2 | 8 |
| 运维工程师 | 6 | 11 | 5 | 3 | 25 |
| 项目经理 | 1 | 4 | 8 | 4 | 17 |
| **合计** | **14** | **32** | **25** | **12** | **90** |

---

## 二、跨角色共识的 High 问题（必须修复）

以下 4 个问题被至少两个角色独立发现，优先级最高：

### H1 — CanonicalDoc 缺少 etag 字段导致运行时 TypeError
- **发现者**: Architect(F20), SWENG(2.1)
- **描述**: `OcrAdapter.normalize()` 传入 `etag=raw.etag`，但 `CanonicalDoc` 数据类无该字段 → 运行时 `TypeError`
- **影响**: OCR 入库完全不可用
- **修复**: 将 `raw.etag` 映射到 `CanonicalDoc.hash`，或增加 `etag` 字段
- **ADR**: ADR-003

### H2 — CLI 测试框架与实现框架不匹配（click vs argparse）
- **发现者**: Architect(F3), SWENG(3.4), Ops(F1-2), PM(F2)
- **描述**: `tests/test_cli.py` 使用 `click.testing.CliRunner`，但实现用 `argparse`
- **影响**: 测试无法运行（缺少 click 依赖）；浪费 TDD 循环
- **修复**: 统一为 subprocess 测试模式，移除 click 引用

### H3 — FTS5 中文分词无明确策略
- **发现者**: Architect(F15), PM(F1)
- **描述**: 默认 tokenizer 对中文效果差，`khub query "伤寒论"` 可能零结果
- **影响**: 全文检索核心功能不可用
- **修复**: 使用 trigram tokenizer 或 unicode61 + tokenchars；增加中文检索验证测试
- **ADR**: ADR-006

### H4 — `detect_changes()` 使用 `getattr` 访问 `sqlite3.Row` 导致永远为 True
- **发现者**: SWENG(2.2)
- **描述**: `getattr(row, "hash", None)` 始终返回 None，变化检测失效
- **影响**: 每次 `sync_source` 都创建新版本；分支冲突逻辑也受影响
- **修复**: 改用 `row["hash"]` 索引方式访问

---

## 三、跨角色共识的 Medium 问题列表

| # | 问题 | 发现者 | 影响范围 |
|---|------|--------|----------|
| M1 | ingest 硬编码 `adapter.name != "ocr"` 违反复合层 | Architect(F1) | 扩展性 |
| M2 | 缺少适配器工厂/注册机制，M2 扩展需重构多处 | Architect(F10), PM | 架构 |
| M3 | Sync 引擎冲突分支未更新 sync_states → 重复冲突 | SWENG(2.3) | 正确性 |
| M4 | DB 操作无异常处理 → 直接冒泡给用户 | SWENG(5.1) | 可靠性 |
| M5 | `_store()` 配置缺失时静默回退 + 非法配置 YAML 异常 | SWENG(5.2), Ops | UX |
| M6 | OCR 附件 I/O 异常无隔离 → 单附件失败导致整源不可用 | SWENG(5.3) | 健壮性 |
| M7 | `test_secret_from_env` 调用签名错误 → 测试失败 | SWENG(1.4) | 测试 |
| M8 | FTS5 检查写在 conftest.py → 静默跳过 | SWENG(1.1) | 测试 |
| M9 | DB 文件无权限保护（默认 644） | Netsec, Ops | 安全 |
| M10 | 内容入库无大小限制 → OOM / 库膨胀 | Netsec(6) | 安全/可靠性 |
| M11 | FTS5 搜索无异常捕获 + 搜索词长度限制 | Netsec(6) | 安全/UX |
| M12 | 项目缺少 `__main__.py` 和 console_scripts 入口 | SWENG(7.3), Ops | 部署 |
| M13 | M1 无 WAL 模式 → M2 Web UI 时出现锁库 | Architect(F16) | 运维 |
| M14 | 无日志记录（`import logging` 零调用） | Ops(F3) | 运维 |
| M15 | 集成烟雾测试写入生产 DB 路径 | Ops(F2) | 安全/测试 |
| M16 | 无 schema 迁移策略 | Ops(F4), PM | 运维 |
| M17 | `sync` CLI 命令为占位空操作 | PM, Ops | UX |
| M18 | 完成定义仅"测试通过"，缺少验收清单 | PM(F6) | 质量 |
| M19 | `_current_hash()` 绕过 Store 直接操作用户连接 | Architect(F5) | 封装 |
| M20 | `push()` 返回值类型不一致（None vs SyncResult） | Architect(F9) | 接口 |
| M21 | `compute_hash` 应移至 utils.py（适配器依赖 db 层） | Architect(F4) | 架构 |

---

## 四、评分详情

| 维度 | 说明 | 评分 |
|------|------|------|
| **架构完整性** | 分层清晰，无循环依赖；适配器接口完备 | A- |
| **代码正确性** | 存在 3 个 blocking bug（etag、detect_changes、FTS5） | C+ |
| **测试覆盖** | 覆盖正常路径良好；边界/错误路径缺失 | B |
| **安全性** | 密钥管理合理；DB 无加密可接受；需加文件权限保护 | B |
| **运维准备** | 缺日志、缺迁移策略、CLI 测试/实现不匹配、入口点缺失 | C |
| **项目管理** | 范围对齐、任务粒度合理、里程碑清晰 | A- |
| **可扩展性** | 适配器工厂缺失、ingest 硬编码名称 | B- |

**总体评分**: **B (可交付，需先修复 4 个 High + 关键 Medium)**

---

## 五、最终推荐

1. **必须在实现前修复** 4 个 High 问题（H1-H4）
2. **建议在实现前或实现中修复** 约 12 个 Medium 问题（M1-M11 含安全/正确性）
3. **其余 Low 问题** 可纳入实现后迭代
4. 修复后的最终验收清单参见 PM 评审建议

### 下步行动
1. 创建决策日志（ADR）记录关键决议
2. 创建风险清单
3. 更新 M1 实施计划以包含修复
4. 进入实现阶段
