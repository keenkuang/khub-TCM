# 远程灾备与双机热备 — 定稿设计文档（vFinal.2）

> 文档状态：本文件为**权威定稿设计**。已融合：
> - 第 1 轮三角色（产品经理 / 顶级架构师 / 顶级软件设计师）评审全部修订（`docs/ha_dr/review_round1.md`）；
> - 新一轮（替代原始会话因限流失落的轮次）三角色评审全部修订（`docs/ha_dr/review_round2.md`）。
> 评审与修订完整存档见 `docs/ha_dr/`。

## 0. 非技术决策者摘要（人话版）

本方案帮你做两件事，各自代价：

1. **远程灾备（优先做）**：定期把整个知识库自动备份到另一台机器 / 云盘，并且**保留最近 N 份历史快照**，你手滑删了、改坏了，能回到过去的某个时间点。代价：配一次 SSH/对象存储，平时不用管。
2. **双机热备（其次做）**：两台机器，一台挂了另一台能顶上。代价：**切换后需要你手动改一下客户端连的地址/端口**（本应用不自动漂移 IP）；日常是自动检测、不自动切换，避免误切。

真实痛点排序：**数据丢失（误删/改坏/机器坏）＞ 机器宕机**。所以先做好"不丢"，再做"顶得上"。

## 1. 目标与范围

为 khub 个人知识中枢构建一套**仅依赖 Python 标准库 + scp 即可搭建**的灾备与高可用方案。

- **RPO 尽可能小（不丢数据）**：每次关键变更都记录到 WAL 变更日志，备机/灾备端持续回放；并支持**时间点恢复（PITR）**。
- **RTO 分钟级**：主库宕机时，人工或（保守的）自动切换至备机，分钟级恢复服务。
- **零外部依赖**：传输层基于 SSH/SCP 或 HTTPS（标准库）。可选对象存储（S3 兼容）增强，不引入 Docker / K8s / 云 SDK。

### 明确超出应用层范围（列为运维 / 外部要求）
- **集群 VIP / ARP 漂移**：由 keepalived / VRRP 或客户端重试承担；**切换后客户端连接地址/端口需人工调整，应用不自动漂移**。
- **真实 STONITH（断电 / 锁共享盘）**：应用层无法做物理围栏；应用层做到"看到更高 epoch 立即降级停写"。
- **真实跨网络脑裂的端到端验证**：靠 `--self-test` 注入链路故障做集成级自测 + 运维演练，不替代真人演练。

## 2. 背景

khub 使用 SQLite 单文件主存储，辅以 FTS5 全文索引与 sqlite-vec 向量索引。SQLite 并发写入有限，双机方案设计为 **active-passive**：

- **Primary（主动方）**：运行服务、接受读写、持写租约，变更经触发器落入 WAL。
- **Standby（热备）**：静默同步，不对外服务；经双故障域确认后升为 Primary。
- **Disaster Recovery（异地）**：快照 + WAL 增量，仅灾难恢复，不做热切换。

## 3. 总体架构：两个独立模块

| 模块 | 数据温度 | 切换 | 核心机制 |
|------|----------|------|----------|
| 双机热备 | 热数据 | 故障自动（保守，默认人工确认）/ 人工 | 心跳 + 写租约 + WAL 实时回放 |
| 远程灾备 | 半冷数据 | 纯人工 | 周期快照(多版本) + WAL 增量 + 恢复校验 + PITR |

共用：`replication_log`（触发器强制写入 + 全局 `lsn`）、`apply_changes` 分发表、`Transport` 抽象。

## 4. 模块 1 — 双机热备（热数据）

### 4.1 角色与集群访问点
- `active` / `passive`；谁 active 谁绑定服务端口（VIP 由外部提供）。初始角色由配置/持久化状态决定。

### 4.2 心跳（参考群晖：双机各一独立网口，网线直连）
- **默认通道：HTTP 轮询 `/ha/heartbeat`**（直连链路）。
- **可选：SSH 推送 / 共享文件心跳**（标可选）。
- 业务 LAN 的 `service_addr` 探活用于第二故障域判定。

### 4.3 提升判定 —— 双独立故障域（防脑裂）
提升 **Primary** 的安全默认（两条同时满足，或 quorum 确认对端死）：
1. 直连心跳链路超时 **且**
2. 业务 LAN 对端 `service_addr` 不可达（双独立故障域同时证实对端已死）。

- 单一链路丢失 → 只进 `degraded`，**绝不提升**。
- 删除 `QuorumChecker`（2 节点无第三方恒"未知→不提升"）；epoch fencing 防双 active；旧主见更高 epoch 立即降级停写。

### 4.4 写租约（防双写窗口 / 灰故障）
- active 每次心跳续租；续不上立即停写。
- 超时一律 `time.monotonic()` + 探针 socket timeout。

### 4.5 脑裂、分歧与 reconcile
- **已知可接受风险**：两节点链路全断且各自存活时，分区期可能双写。应用层无真实 STONITH，明确声明此风险。
- 重连先做分歧检测（比较 `lsn` / epoch）；若已分歧 → 进 **safe mode**，由人工决策。
- **`khub ha reconcile --left --right`**：按 `lsn` 二分出分歧点、列出冲突行、生成人工决策报告（覆盖/保留/合并建议）。
- **`resolve_split_brain(keep)`**：safe mode 的显式退出 API——人工选定新主后落定 `epoch`、清除分歧标志。

### 4.6 状态机（完备）
`active → (心跳丢失单域) → degraded → (双域证实对端死) → promoting → active(新)`；`active/passive → (分歧) → safe_mode → (resolve_split_brain) → active/passive`。`tick()` 为纯决策函数。

### 4.7 自测
- `--self-test` 注入链路故障做集成级自测。

## 5. 模块 2 — 远程灾备（半冷数据）

- 补全 `SshReplica` / `S3Replica` / `FileReplica` 的 `push_snapshot` / `push_changes` / `fetch` / `health`。
- 新增恢复路径 `apply_changes` + `pull_and_replay`。
- 由 `schedule` 周期触发即"半冷"：定时推快照 + 持续追加 WAL 增量。
- **多版本快照 + PITR**：保留最近 N 份快照（覆盖"误删/改坏想回退"），支持按时间点恢复。
- **恢复校验（MVP 必带）**：恢复后校验 **行数 + 全局 `lsn` + FTS 检索抽样（`rebuild_fts` 后）**，三项通过才算可用；备份不校验等于没备。

## 6. WAL 变更日志 —— 强制写入 + 全局逻辑序号

### 6.1 机制替代约定（关键修订）
被复制的每张表建 **`AFTER INSERT/UPDATE/DELETE` 触发器**，自动以 `json_object(...)` 落 `replication_log`，与主写入**天然同事务、不可绕过**。`record_change()` 退为可选 API（供非表写入或手动补记）。这杜绝了"绕过 `store_document` 直写导致静默漏记"的路径。

```sql
CREATE TABLE replication_log(
    id      INTEGER PRIMARY KEY AUTOINCREMENT,  -- 节点内序号，不可跨节点比较
    lsn     INTEGER NOT NULL,                    -- 全局逻辑序号，单调分配，一致性判据
    op      TEXT,
    table_name TEXT,
    row_id  TEXT,
    payload TEXT,                                -- JSON
    at      TEXT,
    applied INTEGER DEFAULT 0
);
```

### 6.2 事务归属契约（代码层）
- 业务写入由 `@with_txn` 装饰器统一开启并提交事务；触发器在事务内落 WAL。
- `record_change()` 不持有连接，从 `store` 取当前活跃连接 `execute`；**调用前必须已 `BEGIN`**；异常随主事务整体回滚。
- `replication_log` 自身写入**短路**（不二次 `record_change`），防循环。

### 6.3 回放（分发表）
- 备机/灾备端 `pending()` 按 `lsn` 拉取未回放记录 → `apply_changes()` 回放 → `mark_applied()`。回放**幂等**（UPSERT）。
- **`register_replayer(table, fn)`**：按 `table_name` 注册回放函数，统一签名 `(store, op, row_id, payload)`；未知表抛 `UnknownTableError`。回放知识下沉各域，禁巨型 if/else。
- 备机回放**不**二次触发 `record_change`。

## 7. 快照一致性与派生索引

- 快照必须用 `conn.backup()` 产出一致性副本再传输，**禁直接拷活库**（防半写页）。
- **快照恢复排除 `ha_state`**（epoch/角色/租约），避免破坏 fencing 不变量。
- **派生索引显式注册表**：`DERIVED_INDEXES = {"fts": rebuild_fts, "vec": rebuild_vec}`；回放后统一重建。FTS5 虚表不进 WAL，须 `rebuild_fts`（FTS 写入走触发器或 `INSERT OR REPLACE` 保证幂等）；向量索引 `rebuild_vec` 按需。

## 8. 安全

- **PII 加密**：`crypto.py` 在 `KHUB_PII_ENCRYPT=1` 时自动加密 PII；快照与 WAL 存密文。
- **传输加密**：WAL/快照经 TLS 或 SSH，禁明文。
- **命令执行安全**：ssh 走 list 传参、禁 `shell=True`；scp 整文件到临时名后**同一连接 `rename`** 原子替换（防半传）；WAL 追加用 `flock`（非 rename，避免丢并发追加）。
- **凭证管理**：走 `SSH_AUTH_SOCK` / 权限 `600` 的 key 文件，禁硬编码、禁写入 `ha_state`。

## 9. 接口合约（`khub/replication.py` + `khub/db.py`）

| 符号 | 说明 |
|------|------|
| `Change` | 变更记录 dataclass |
| `WALLog` | WAL 管理器（`pending(lsn)` / `mark_applied`；不内部 commit） |
| 触发器 | 各复制表 `AFTER` 触发器自动落 `replication_log`（主机制） |
| `record_change(store, op, table, row_id, payload)` | 可选补记 API，须在事务内调用 |
| `register_replayer(table, fn)` | 注册回放函数，签名 `(store, op, row_id, payload)` |
| `apply_changes(store, changes)` | 分发表回放，幂等，未知表抛 `UnknownTableError` |
| `export_snapshot()` / `conn.backup()` | 一致性快照（排除 `ha_state`） |
| `import_snapshot_manifest()` | 验证并持久化快照元数据 |
| `ReplicaTarget` | 备机/灾备接口（`push_snapshot` / `push_changes` / `fetch` / `health`），**组合 `Transport` + 路径/凭证** |
| `Transport` | **只解决字节如何到对端**（scp/https），不持有业务语义 |
| `FailoverController` | 心跳判定 + 双故障域 + epoch fencing + 写租约 + safe mode + `resolve_split_brain` |
| `ha_state` 表 | 持久化角色 / epoch / 租约时间戳（不进快照恢复） |
| `tick(now, probe_heartbeat, probe_lan)` | 纯决策，可注入 `now()` + 两个可 mock 探针 |

- `HeartbeatChannel` 与 `Transport` 职责正交；`Transport` 只服务字节传输。
- 状态转换见 §4.6。

## 10. 可观测性（告警与状态）

- **`khub ha status`**：人类可读输出当前角色、最后同步时间戳、对端不可达已持续时长、是否 safe mode、建议动作。
- **切换告警须含 5 字段**：① 当前角色 ② 最后同步时间 ③ 对端失联时长 ④ safe mode 状态 ⑤ 建议动作。
- 配套**故障剧本文档**（何时手动切、怎么改客户端地址、reconcile 怎么用）。

## 11. 交付分期

- **P0 — 远程灾备（MVP，优先）**：多版本快照 + WAL 增量 + 恢复校验（行数+lsn+FTS抽样）+ PITR + `SshReplica`/`S3Replica`/`FileReplica`。
- **P1 — 双机热备（保守完整）**：`FailoverController`（默认人工确认、自动只检测）+ 双故障域提升 + 写租约 + `apply_changes` 回放 + `reconcile` 工具 + `--self-test` + `ha status`/告警/剧本。

## 12. 未覆盖 / 未来工作

- 自动 leader election 集群化。
- 强冲突检测（向量时钟）。
- 快照压缩（gzip/zstd）与清理策略细化。
- 增量快照（只传变更页）。
- 整个 DB 的 TDE / `sqlite3_key`（SEE）评估。
- RPO/RTO 指标与分歧重做流程的运维手册化。
