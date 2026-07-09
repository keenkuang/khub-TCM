# 实现前评审（Implementation-Readiness）— 双机热备 & 远程灾备

> 评审对象：第 3 轮定稿 `docs/disaster_recovery.md`（vFinal.3）+ **真实代码**（`replication.py` / `db.py` / `clinical/*` / `ops/store.py`）。
> 评审角色：产品经理 / 顶级架构师 / 顶级软件设计师（三个独立 agent，均实际读代码）。
> 性质：不重审设计，而是审"vFinal.3 能否在现有代码上无坑落地、P0 是否真能作为 MVP 交付"。
> 结论：可落地，但先解决 3 件架构前提 + 修订 P0 范围；已产出 P0 分步实现清单（见第三节）。

---

## 一、三视角评审记录（要点）

### 1.1 产品经理
- **P0 不是单个 MVP，是一组功能**：现有代码仅 `LocalFileReplica` 全功能、`SshReplica` 半成品；`lsn_seq`/全局 lsn/多版本保留/恢复校验/`dr verify`/PITR **全部缺失**，`replication_log` 无 `lsn` 列，临床表根本没走 WAL。
- **用户验收清单（可勾选）**：①`khub dr init --target file://...` 一条命令配好；②`dr verify` 5 分钟内打印 integrity_check=ok/行数/lsn/FTS 抽样；③误删后 `dr restore --to 快照` 找回；④`dr status` 显示上次成功备份。
- **"异地"错觉**：FileReplica 是同机另一目录，**不算灾备**；CLI/文档须区分"本地副本（防误删）" vs "真正灾备（SshReplica，防机器坏/勒索）"。
- **PITR 最易翻车**：语句级回退操作路径太长，个人用户首屏可用的是"多版本快照回退"，PITR 应标高级项。
- **硬伤**：现有 `push_pending` 已 `mark_applied` 丢弃 WAL，而 PITR 需**保留全量 WAL 历史**，否则 P0 的 PITR 落空。
- **建议**：P0 先交付 `FileReplica + 多版本快照 + 恢复校验 + dr verify`（真 MVP）；`SshReplica` 与 `PITR` 降为 P0.5/P1。警示语须进 CLI（`dr init` 提示"本副本在 X 机器上，非异地"）。

### 1.2 顶级架构师
- **先解决 3 件事才敢动 P0**：①手动 `_replicate` 与新增触发器会**双记**；②`replication_log` 缺 `lsn` 列 + `lsn_seq` 表全缺失；③`conn.backup()` 快照必须改 ATTACH 才能排除 `ha_state`。
- **代码 vs 设计差异**：现有全靠域模块手动调 `_replicate`（`db.py:147`/`patients.py:21`/`ops/store.py` 等多处），与"仅 Primary 装触发器自动记账"直接冲突。
- **BLOB**：`documents` 无 BLOB 列，payload 纯 JSON 安全；但 `embeddings.vector` 是 BLOB 且未入 WAL（派生数据，符合设计）。
- **`replay_from`/`register_replayer`**：现有是 `apply_changes` + `_DISPATCH` 懒加载全局 dict，缺 `Lock`、缺 `UnknownTableError` 隔离（现静默跳过），签名已对；"不二次触发"现靠绕过 `record_change`，`recursive_triggers=OFF` 需补。
- **快照排除 ha_state**：`ha_state` 存在（`key/value`）；`export_snapshot` 表清单固定且漏 `embeddings/vec_meta/files/ebook_meta`；须改 ATTACH 逐表跳过。
- **架构级风险**：①触发器 vs 手动双写是头号坑（P0 须先冻结"删手动/触发器短路"决策）；②FTS/vec 重建时机——现有内联维护与"批量后统一重建"冲突，建议回放用内联、仅 PITR 整库恢复后做一次 `rebuild_fts/vec`；③升主后 lsn 前缀必须立即续新 epoch；④`sqlite_vec` 不可用时 `vec0` 建表失败，重建前须判可用性；⑤WAL 写失败仅告警不阻塞与"同事务原子"有张力——触发器内 `UPDATE lsn_seq` 失败会连带主事务回滚，需 `WHEN` 守卫或分离 lsn 分配。

### 1.3 顶级软件设计师
- **逐符号差异表**（见原报告）：`lsn_seq`/`lsn` 列缺失；`record_change`→`manual_record_change`(内联 lsn 分配)；`_DISPATCH`→`register_replayer`(Lock+导入期+UnknownTableError)；`apply_changes`→`replay_from`(按 lsn 排序+幂等+隔离)；`conn.backup`→ATTACH 逐表；`export_snapshot` 表清单补全。
- **双记消除方案（5 处手动调用点）**：`db.py:147`、`patients.py:21`、`records.py:24`、`consultations.py:27`、`ops/store.py:22/34/48/51`。删除 `_replicate` 调用，触发器挂到各自 `init()` 末尾（这些表是运行时建的，不只 `db.init_schema`）。过渡期保留 `_replicate` 但加 `TRIGGERS_INSTALLED` 开关，确认 WAL 正常后再删，避免空窗。
- **P0 分步实现清单**（可勾选）：①`replication_log` 加 lsn + 新增 `lsn_seq`/`next_lsn()`；②`record_change`→`manual_record_change`；③`install_triggers(conn,table)`（取列、json_object、BLOB base64）+ 挂入各 `init()`；④删 5 处手动 `_replicate`；⑤`register_replayer`(Lock)+`replay_from`+`UnknownTableError` 隔离；⑥`push_snapshot` 改 ATTACH 跳 `ha_state`；⑦`export_snapshot` 表清单补全；⑧新增 `dr verify`。
- **坑点**：BLOB base64 还原；docs_fts/vec 不进 WAL，恢复后 `rebuild_fts/vec`（vec 分块后台）；备机 `recursive_triggers=OFF`；lsn 升主续新 epoch；§13 五条单测在 pytest+真 SQLite 下可写，难点仅在触发器在 :memory 事务边界，建议用临时文件库验证。

---

## 二、评审决策记录（需先解决 / 需修订设计）

| # | 来源 | 类型 | 结论 |
|---|------|------|------|
| I1 | 架构师/设计师 | 架构前提 | 先消除"手动 `_replicate` vs 触发器"双记：触发器装 Primary，过渡期 `TRIGGERS_INSTALLED` 开关，确认后删手动分支 |
| I2 | 架构师 | 架构前提 | `replication_log` 补 `lsn` 列 + 新增 `lsn_seq` 分配器（同事务） |
| I3 | 架构师 | 架构前提 | 快照改 ATTACH 逐表 `INSERT…SELECT` 跳 `ha_state`；补全 `export_snapshot` 表清单 |
| I4 | PM | 设计修订 | **P0 拆分**：P0a = FileReplica + 多版本快照 + 恢复校验 + `dr verify`（真 MVP）；SshReplica 与 PITR 降为 P0b/P1 |
| I5 | PM | 设计修订 | **WAL 保留策略**：PITR 要求保留全量 WAL 历史，现有 `mark_applied` 丢弃须改为"归档保留 + 保留窗口"，否则 PITR 落空 |
| I6 | 架构师 | 设计修订 | **lsn 原子性张力**：触发器内 `UPDATE lsn_seq` 失败会回滚主事务，与"WAL 失败仅告警"矛盾 → lsn 分配与主写入解耦（独立轻路径或 `WHEN` 守卫），明确取舍 |
| I7 | PM | 设计修订 | **本地副本 vs 真正灾备**：CLI/文档明确区分，防误导；警示语进 `dr init` |
| I8 | 架构师 | 风险 | FTS/vec 重建时机：回放路径用内联维护，仅 PITR 整库恢复后做一次 `rebuild_fts/vec`（vec 分块后台） |
| I9 | PM | 验收 | 用户可勾选验收清单（init/verify/restore/status）须落地为 CLI 与测试 |

---

## 三、修订稿 = P0 分步实现清单（ actionable）

> 落地依据：vFinal.3 + 上述决策。P0 先交付 **P0a（真 MVP）**，再 **P0b**。

**P0a — 本地副本 + 多版本快照 + 恢复校验（防误删）**
- [x] `db.py`：`replication_log` 加 `lsn` 列；新增 `lsn_seq` 表与 `next_lsn()`（同事务，按 I6 解耦分配）。
- [x] `replication.py`：`record_change`→`manual_record_change`（内联 lsn）。
- [x] `replication.py`：新增 `install_triggers(conn, table)`（取列 / `json_object` / BLOB `base64`），挂入各域 `init()`；加 `TRIGGERS_INSTALLED` 过渡开关。
- [x] 删除 5 处手动 `_replicate` 调用（过渡期开关保护）；`0.2.2` 进一步删除 dead `Store._replicate`。
- [x] `replication.py`：`register_replayer`（`threading.Lock` + 导入期注册 + `UnknownTableError` 隔离）；`apply_changes`→`replay_from`（按 lsn 排序 / 幂等 UPSERT / 隔离未知表）。
- [x] `ReplicationManager.push_snapshot`：`conn.backup`→ATTACH 逐表 `INSERT…SELECT` 跳过 `ha_state` / `replication_log` / `lsn_seq`（见 `db.make_snapshot_db`，由 `_EXCLUDE_TABLES` 控制）；`export_snapshot` 表清单补全（embeddings/vec_meta/files/ebook_meta/attachments/sync_states）。
- [x] `LocalFileReplica`：多版本快照保留最近 N 份。
- [x] 新增 `khub dr verify`（integrity_check + 行数 + lsn + FTS 抽样 + manifest）+ `dr status`/`dr init`/`dr restore --to`。
- [x] §13 五条单测落地（同事务落 log / 备机不重入 / 幂等 / 未知表隔离 / tick 全转换）。
- [x] **WAL 解耦（M2/A5，`0.2.2`）**：业务写只写 `wal_staging`，`WalFlusher` 独立连接 best-effort 落 `replication_log`；WAL 写失败仅告警不阻塞业务写。

**P0b — 异地灾备 + PITR（防机器坏/勒索）**
- [x] `SshReplica`（SFTP put 临时名 + rename 原子替换；凭证走 `SSH_AUTH_SOCK`/600）。
- [x] WAL 保留策略（I5）：`Store.prune_wal` 归档窗口（`KHUB_WAL_KEEP` / `KHUB_WAL_KEEP_DAYS`）已在 `0.2.3` 实现——推送后自动清理已 applied 的旧 WAL，本地文件随窗口收敛；PITR 因走副本 `fetch_changes` 不受影响（详见 CHANGELOG 0.2.3）。
- [x] PITR：`replay_from` 回放至 `lsn<=target`（语句级容忍半事务），附用户剧本（高级项）。
- [x] CLI 警示：区分"本地副本"与"异地灾备"，`dr init` 提示机器归属与每季演练。

**P1（双机热备）**
- [x] `FailoverController` + `tick()->Decision` + 双故障域 + 写租约 + `reconcile` + `resolve_split_brain` + `--self-test` + `ha status`/告警/剧本 + `S3Replica`（均已在 `khub/ha/` 落地，`test_ha.py` 31 passed）。
