# 第 2 轮（新一轮）三角色评审记录 — 双机热备 & 远程灾备

> 说明：原始会话的第 2、3 轮因 `429 限流` 未留存正文（见 `README.md`）。本文件是**重新发起的一轮三角色评审**，用于替代缺失轮次、补全把关。
> 评审对象：第 1 轮定稿 `docs/disaster_recovery.md`（vFinal）。
> 评审角色：产品经理 / 顶级架构师 / 顶级软件设计师（三个独立 agent）。
> 结论：三视角均"方向认可、需修订"，共 3 个高严重度 + 6 个中 + 若干低。修订稿已并入 `docs/disaster_recovery.md`（vFinal.2）。

---

## 一、评审记录（三视角原始意见）

### 1.1 产品经理
- **高 · 痛点命中不全**：只覆盖"机器/异地损坏"，遗漏个人最高频丢失场景"误删 / 手滑覆盖 / 改坏想回退"。应明确 P0 是否含多版本快照或时间点恢复（PITR）。
- **高 · 范围声明对决策者不透明**：VIP/STONITH 超出范围，但没说清后果——切换后"客户端怎么指向新主"要用户自己搞定。须声明"切换后需人工改客户端连接地址/端口"。
- **中 · 恢复校验强度存疑**："抽样"未定义比例/表/FTS 是否参与；对个人用户 FTS 搜索分歧才是可感知的"恢复失败"，校验须含 `rebuild_fts` 后检索抽样。
- **中 · 告警不够救火用**：须含 5 字段——当前角色、最后同步时间戳、对端失联时长、是否 safe mode、建议动作。
- **中 · P1 自动切换对个人过重**：建议 P1 默认"人工确认切换，自动只检测不提升"。
- **低 · 非技术决策者摘要缺失**：§1 应加"人话版"说明两件事与各自操作成本。

### 1.2 顶级架构师
- **高 · "同事务"无强制约束**：`record_change` 钩入各模块只是**约定**，绕过 `store_document` 的写入（孪生体后台生成、管理脚本、测试 fixture、`conn.execute` 直写、未来模块）会静默漏记。→ 应改用 **DB 触发器**（`AFTER INSERT/UPDATE/DELETE` 自动落 `replication_log`，天然同事务），`record_change` 退为可选 API。
- **高 · 跨节点 `max_replication_id` 语义错误**：`replication_log.id` 各节点独立 `AUTOINCREMENT`，恢复校验跨节点比对无意义，会误判一致。→ 引入全局逻辑序号 `lsn` 单调分配。
- **中 · 脑裂残留 + safe mode 不可操作**：双故障域防不了"两节点链路全断且各自存活"，分区期双写是已知可接受风险，但 `safe mode` 只说"人工定主"却无比对/合并工具，运维无法落地。→ 补 `khub ha reconcile --left --right`（按 `lsn` 二分分歧、列冲突行、生成决策报告）。
- **中 · 派生索引与 `ha_state` 快照污染**：`conn.backup()` 把 `ha_state`（epoch/角色/租约）一起拷走，备机恢复会覆盖 epoch 破坏 fencing；向量索引重建含糊。→ 快照排除 `ha_state`；显式 `DERIVED_INDEXES = {fts: rebuild_fts, vec: rebuild_vec}` 注册表。

### 1.3 顶级软件设计师
- **高 · `record_change` 事务归属未契约化**：谁开事务、谁 commit、异常回滚时半截写入怎么办无约束。→ `@with_txn` 装饰器统一 commit；`record_change` 从 `store` 取活跃连接 `execute`，调用前必须已 `BEGIN`。
- **高 · `apply_changes` 分发表机制缺约定**：未定义注册接口与回放函数签名，易退化成全局 dict 竞争。→ `register_replayer(table, fn)`，统一签名 `(store, op, row_id, payload)`，未知表抛 `UnknownTableError`。
- **高 · 派生索引幂等遗漏**：仅 `rebuild_fts` 不够，UPSERT 主表后 FTS 用 `INSERT` 会脏；须约定回放后统一 `rebuild_fts`/`rebuild_vec`，FTS 走触发器或 `INSERT OR REPLACE`。
- **中 · `FailoverController` 状态机不完备**：`safe_mode` 退出条件（如何落 `epoch`、清分歧标志）未定义，会"进入后无法自拔"。→ 补状态图与 `resolve_split_brain(keep)` 显式 API。
- **中 · WAL 表自身是否复制**：备机回放会循环写自己的 `replication_log`。→ 备机回放不二次 `record_change`；`record_change` 对 `table_name='replication_log'` 短路。
- **中 · `Transport` 与 `ReplicaTarget` 重叠**：两者职责模糊。→ `Transport` 只解决"字节到对端"，`ReplicaTarget` 组合 `Transport` + 路径/凭证。
- **低 · 安全落地细节**：scp 整文件到临时名后须**同一连接 `rename`** 原子替换；WAL 追加用 `flock` 而非 rename；凭证走 `SSH_AUTH_SOCK` / `600` key 文件，禁硬编码、禁写入 `ha_state`。
- **低 · `tick()` 纯决策须注入依赖**：除 `now()` 还须注入 `probe_heartbeat()` / `probe_lan()` 两个可 mock 探针。

---

## 二、评审修订记录（方案据此改动）

| # | 来源 | 严重度 | 问题 | 修订动作 |
|---|------|--------|------|----------|
| N1 | 架构师 | 高 | "同事务"只靠约定，存在静默漏记路径 | 改用 **DB 触发器**自动落 `replication_log`（天然同事务），`record_change` 退为可选 API |
| N2 | 架构师 | 高 | 跨节点 `max_replication_id` 比对无意义 | 引入全局逻辑序号 **`lsn`**（随写入单调分配，不依赖 PK）作一致性判据 |
| N3 | 设计师 | 高 | `record_change` 事务归属无契约 | 由 `@with_txn` 统一 commit；从 `store` 取活跃连接；调用前须已 `BEGIN` |
| N4 | 设计师 | 高 | `apply_changes` 分发无契约 | `register_replayer(table, fn)` + 统一签名 `(store, op, row_id, payload)`；未知表抛 `UnknownTableError` |
| N5 | 设计师 | 高 | 派生索引幂等遗漏 | 回放后统一 `rebuild_fts`/`rebuild_vec`；FTS 走触发器/`INSERT OR REPLACE` |
| N6 | 架构师 | 中 | 脑裂残留 + safe mode 不可操作 | 明确分区双写为已知风险；补 `khub ha reconcile --left --right` 决策工具 |
| N7 | 架构师 | 中 | 快照污染 `ha_state` / 向量重建含糊 | 快照恢复**排除 `ha_state`**；显式 `DERIVED_INDEXES` 注册表 |
| N8 | 设计师 | 中 | `FailoverController` 状态机不完备 | 补状态图 + `resolve_split_brain(keep)` 显式退出 API |
| N9 | 设计师 | 中 | WAL 表自身复制会循环 | 备机回放不二次 `record_change`；`replication_log` 自身写入短路 |
| N10 | 设计师 | 中 | `Transport` 与 `ReplicaTarget` 重叠 | `Transport` 只管字节传输；`ReplicaTarget` 组合 `Transport` + 路径/凭证 |
| N11 | PM | 高 | 痛点遗漏"误删/想回退" | P0 明确含**多版本快照保留 N 份 / 时间点恢复（PITR）** |
| N12 | PM | 高 | 切换后果对决策者不透明 | §1 声明"切换后需人工改客户端连接地址/端口，应用不自动漂移" |
| N13 | PM | 中 | 恢复校验强度不足 | 校验固定为：行数 + `lsn` + **FTS 检索抽样（rebuild 后）** |
| N14 | PM | 中 | 告警不可救火 | 告警须含 5 字段：角色/最后同步时间/对端失联时长/safe mode/建议动作 |
| N15 | PM | 中 | P1 自动切换对个人过重 | P1 默认"人工确认切换，自动只检测不提升" |
| N16 | PM | 低 | 非技术决策者摘要缺失 | §1 新增"人话版"摘要 |
| N17 | 设计师 | 低 | 安全落地细节 | scp 临时名同连接 `rename` 原子替换；WAL 追加 `flock`；凭证走 `SSH_AUTH_SOCK`/600 key 文件 |
| N18 | 设计师 | 低 | `tick()` 不可单测 | 注入 `now()` + `probe_heartbeat()` + `probe_lan()` 可 mock 探针 |

---

## 三、修订后的修订稿（第 2 轮定稿要点）

> 完整修订稿见 `docs/disaster_recovery.md`（vFinal.2）。本节约其要点：

1. **强制 WAL（机制替代约定）**：对被复制表建 `AFTER INSERT/UPDATE/DELETE` 触发器自动落 `replication_log`，天然同事务、不可绕过；`record_change` 退为可选 API，调用须已在事务内（由 `@with_txn` 统一 commit）。
2. **全局逻辑序号 `lsn`**：替代各节点独立 `id` 作为一致性判据，恢复校验用 `lsn` 而非 `max(replication_id)`。
3. **`apply_changes` 分发表**：`register_replayer(table, fn)`，统一签名 `(store, op, row_id, payload)`，未知表抛 `UnknownTableError`；备机回放不二次 `record_change`，`replication_log` 自身写入短路。
4. **派生索引显式注册**：`DERIVED_INDEXES = {fts: rebuild_fts, vec: rebuild_vec}`，回放后统一重建；FTS 走触发器/`INSERT OR REPLACE` 保证幂等。
5. **快照不污染 `ha_state`**：恢复时排除 `ha_state`（epoch/角色/租约），避免破坏 fencing 不变量。
6. **脑裂与分歧可操作**：明确分区期双写为已知可接受风险；提供 `khub ha reconcile --left --right` 按 `lsn` 二分分歧、列冲突、生成决策报告；`resolve_split_brain(keep)` 显式退出 safe mode。
7. **PITR / 多版本快照**：P0 含保留最近 N 份快照，支持时间点恢复，覆盖"误删/改坏想回退"。
8. **范围与运维诚实化**：切换后需人工改客户端地址/端口；P1 默认人工确认、自动只检测；告警含 5 字段；§1 附非技术摘要。
9. **安全落地**：scp 临时名同连接 `rename` 原子替换、WAL 追加 `flock`、凭证走 `SSH_AUTH_SOCK`/600 key 文件。
10. **`tick()` 可单测**：注入 `now()` + `probe_heartbeat()` + `probe_lan()`。
