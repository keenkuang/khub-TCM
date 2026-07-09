# 远程灾备与双机热备 — 定稿设计文档（vFinal.3）

> 文档状态：本文件为**权威定稿设计**。已融合三轮三角色（产品经理 / 顶级架构师 / 顶级软件设计师）评审全部修订：
> - 第 1 轮：`docs/ha_dr/review_round1.md`
> - 第 2 轮（替代原始会话限流失落轮次）：`docs/ha_dr/review_round2.md`
> - 第 3 轮（纯设计复审）：`docs/ha_dr/review_round3.md`
> 评审与修订完整存档见 `docs/ha_dr/`。

## 0. 非技术决策者摘要（人话版）

本方案帮你做两件事，各自代价：

1. **远程灾备（优先做）**：定期把整个知识库自动备份到另一台机器 / 云盘，且**保留最近 N 份历史快照**，你手滑删了、改坏了、甚至中了勒索加密、或者库文件自己损坏打不开，都能回到过去的某个时间点。代价：配一次 SSH/对象存储，平时不用管。
2. **双机热备（其次做）**：两台机器，一台挂了另一台能顶上。代价：**切换后需要你手动改一下客户端连的地址/端口**（本应用不自动漂移 IP）；日常是自动检测、不自动切换，避免误切。**不演练=切换必手忙脚乱**，建议每季做一次切换演练。

真实痛点排序：**数据丢失（误删/改坏/机器坏/勒索/损坏）＞ 机器宕机**。所以先做好"不丢"，再做"顶得上"。

## 1. 目标与范围

为 khub 个人知识中枢构建一套**仅依赖 Python 标准库 + scp/SFTP 即可搭建**的灾备与高可用方案。

- **RPO 尽可能小（不丢数据）**：每次关键变更都记录到 WAL 变更日志，备机/灾备端持续回放；并支持**时间点恢复（PITR）**与**多版本快照**。
- **RTO 分钟级**：主库宕机时，人工（默认）或保守自动切换至备机，分钟级恢复服务。
- **零外部依赖**：传输层基于 SSH/SCP/SFTP 或 HTTPS。可选对象存储（S3 兼容）增强，不引入 Docker / K8s / 云 SDK。

### 明确超出应用层范围（列为运维 / 外部要求）
- **集群 VIP / ARP 漂移**：由 keepalived / VRRP 或客户端重试承担；**切换后客户端连接地址/端口需人工调整，应用不自动漂移**。
- **真实 STONITH（断电 / 锁共享盘）**：应用层无法做物理围栏；应用层做到"看到更高 epoch 立即降级停写"。
- **真实跨网络脑裂的端到端验证**：靠 `--self-test` 注入链路故障 + 运维演练，不替代真人演练。

## 2. 背景

khub 使用 SQLite 单文件主存储，辅以 FTS5 全文索引与 sqlite-vec 向量索引。SQLite 并发写入有限，双机方案设计为 **active-passive**：

- **Primary（主动方）**：运行服务、接受读写、持写租约，变更经触发器落入 WAL。复制触发器**仅装在 Primary**。
- **Standby（热备）**：静默同步，不对外服务；回放时 `PRAGMA recursive_triggers=OFF` 避免触发器重入；经双故障域确认后升为 Primary。
- **Disaster Recovery（异地）**：快照 + WAL 增量，仅灾难恢复，不做热切换。

## 3. 总体架构：两个独立模块

| 模块 | 数据温度 | 切换 | 核心机制 |
|------|----------|------|----------|
| 双机热备 | 热数据 | 故障保守自动（**默认人工确认**，自动只检测不提升）/ 人工 | 心跳 + 写租约 + WAL 实时回放 |
| 远程灾备 | 半冷数据 | 纯人工 | 周期快照(多版本) + WAL 增量 + 恢复校验 + PITR |

共用：`replication_log`（Primary 触发器强制写入 + 全局 `lsn`）、`replay_from()` 分发表、`Transport` 抽象。

## 4. 模块 1 — 双机热备（热数据）

### 4.1 角色与集群访问点
- `active` / `passive`；**应用绑定本地服务端口，VIP 由外部提供**。初始角色由配置/持久化状态决定。**切换后用户需手动改客户端连接地址/端口**。

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
- **已知窗口（非"可接受风险"，以 PITR 兜底）**：两节点链路全断且各自存活时，**分区期内旧主持续对外写**——fencing 仅保护"重连后"瞬间，该窗口须明示。PITR 是唯一数据兜底手段。
- 重连先做分歧检测（比较 `(epoch, local_seq)`）；若已分歧 → 进 **safe mode**，由人工决策。
- **`khub ha reconcile --left --right`**：按 `(epoch, local_seq)` 二分出分歧点、列出冲突行、生成人工决策报告（覆盖/保留/合并建议）。
- **`resolve_split_brain(keep: Role)`**：safe mode 的显式退出 API——人工选定新主后落定 epoch、清除分歧标志、以新 epoch 前缀续接 `replication_log`。

### 4.6 状态机（完备，`tick` 纯决策）
状态：`active` / `passive` / `degraded` / `promoting` / `safe_mode`。
转换：`active →(单域心跳丢失)→ degraded →(双域证实对端死)→ promoting → active(新)`；`active/passive →(分歧)→ safe_mode →(resolve_split_brain)→ active/passive`。
- **`tick(now, probe_heartbeat, probe_lan) -> Decision`**：纯决策函数，**无副作用**，返回 `Decision(state, actions)`（actions 如 `promote/alarm/reconcile`）。`now`、`probe_heartbeat`、`probe_lan` 均可注入便于单测。

## 5. 模块 2 — 远程灾备（半冷数据）

- 补全 `SshReplica` / `S3Replica`（P1）/ `FileReplica` 的 `push_snapshot` / `push_changes` / `fetch` / `health`。
- 新增恢复路径 `replay_from(changes)` + `pull_and_replay`。
- 由 `schedule` 周期触发即"半冷"：定时推快照 + 持续追加 WAL 增量。
- **多版本快照 + PITR**：保留最近 N 份快照（覆盖误删/改坏/勒索/损坏想回退），支持按时间点恢复（恢复快照后 `replay_from` 回放至 `lsn<=target`，粒度语句级容忍半事务）。
- **防勒索 / 防损坏**：远端副本设为不可改写 + 多版本保留；恢复前 `PRAGMA integrity_check` 校验库完整性。
- **恢复校验（MVP 必带）**：恢复后校验 **`PRAGMA integrity_check` + 行数 + 全局 `lsn` + FTS 检索抽样（rebuild 后）**，并写 **manifest**（lsn/行数/FTS 样本）供离线比对；提供 **`khub dr verify`** 人类可读报告（通过/失败+原因）。三项通过才算可用；备份不校验等于没备。

## 6. WAL 变更日志 —— 强制写入 + 全局逻辑序号

### 6.1 机制：Primary 触发器（仅装 Primary）
被复制的每张表建 **`AFTER INSERT/UPDATE/DELETE` 触发器**，由**代码随 schema 生成**（避免新增列漏记），自动以 `json_object(...)` 落 `replication_log`，与主写入**天然同事务、不可绕过**。触发器逻辑最小化；BLOB 列先 `base64()` 再入 `json_object`（json1 不表示 BLOB，否则损坏）；**WAL 写失败仅告警、不阻塞主事务**（明确取舍：牺牲极小分歧风险换主库可用性）。

```sql
CREATE TABLE replication_log(
    id      INTEGER PRIMARY KEY AUTOINCREMENT,  -- 节点内序号，不可跨节点比较
    lsn     INTEGER NOT NULL,                    -- (epoch<<48)|local_seq，全局可比
    op      TEXT,
    table_name TEXT,
    row_id  TEXT,
    payload TEXT,                                -- JSON（BLOB 已 base64）
    at      TEXT,
    applied INTEGER DEFAULT 0
);
CREATE TABLE lsn_seq(seq INTEGER NOT NULL);  -- 单一分配器，与主写入同事务
```

### 6.2 全局逻辑序号 `lsn`（真实来源）
- `lsn = (epoch << 48) | local_seq`。`local_seq` 由持租约者经 `lsn_seq` 表分配：触发器内 `UPDATE lsn_seq SET seq=seq+1 RETURNING seq`，与主事务同提交。
- **`manual_record_change()`**（原 `record_change` 改名，非主路径）复用同一 `lsn_seq` 分配器，保证主备 lsn 同源可比。
- `reconcile` 按 `(epoch, local_seq)` 比较，分区期 epoch 不同使两条时间线天然分片、可判主从。

### 6.3 回放（分发表）
- 备机 `pending()` 按 `lsn` 拉取未回放记录 → `replay_from(changes)` 回放 → `mark_applied()`。回放**幂等**（UPSERT）。
- **`register_replayer(table, fn)`**：**仅模块导入期**调用，内部 `_REPLAYERS` 加 `threading.Lock`；运行时注册抛 `RuntimeError`（防与回放线程竞争全局 dict）。统一签名 `(store, op, row_id, payload)`；未知表抛 `UnknownTableError`，调用方**隔离该表 + 告警/降级**而非整体崩溃。
- 备机回放**不**二次触发 WAL：执行前 `PRAGMA recursive_triggers=OFF`（或 `triggers=OFF` 会话）；且 `replication_log` 自身写入短路（不二次 `manual_record_change`）。

## 7. 快照一致性与派生索引

- 快照**不**用 `conn.backup()` 整体拷贝（无法排除 `ha_state`）；改用 **ATTACH 临时库 + 逐表 `INSERT INTO tgt SELECT * FROM main` 跳过 `ha_state`**，产出一致性副本再传输（防半写页、防污染 fencing）。
- 恢复后 `replication_log` 以**新 epoch 前缀续接**并清除 `applied`，避免升主后 lsn 与原主区间冲突。
- **派生索引显式注册表**：`DERIVED_INDEXES = {"fts": rebuild_fts, "vec": rebuild_vec}`；回放**批量完成后统一重建**，错开读锁。FTS5 虚表不进 WAL，须 `rebuild_fts`（FTS 写入走触发器或 `INSERT OR REPLACE` 保证幂等）；向量索引 `rebuild_vec` 大数据量下**分块 / 低峰后台**重建，文档标注阻塞成本。
- **PITR 边界**：恢复最近快照后 `replay_from` 回放至 `lsn<=target`；粒度=语句级容忍半事务，或仅允许快照边界恢复。

## 8. 安全

- **PII 加密**：`crypto.py` 在 `KHUB_PII_ENCRYPT=1` 时自动加密 PII；快照与 WAL 存密文。
- **传输加密**：WAL/快照经 TLS 或 SSH/SFTP，禁明文。
- **命令执行安全**：ssh 走 list 传参、禁 `shell=True`；**原子替换用 SFTP `put` 临时名 + `rename`**（或 ssh `mv`），非 scp 直传；本地 WAL 追加用 `flock`（非 rename，避免丢并发追加）。
- **凭证管理**：走 `SSH_AUTH_SOCK` / 权限 `600` 的 key 文件（生成即 `chmod 600`），禁硬编码、禁写入 `ha_state`、代码不打印 key 路径。

## 9. 接口合约（`khub/replication.py` + `khub/db.py`）

| 符号 | 说明 |
|------|------|
| `lsn_seq` 表 | 单一 lsn 分配器，与主写入同事务 |
| 触发器（仅 Primary） | 各复制表 `AFTER` 触发器自动落 `replication_log`（主机制） |
| `manual_record_change(store, op, table, row_id, payload)` | 可选补记 API，复用 `lsn_seq`，须在事务内调用 |
| `register_replayer(table, fn)` | 导入期注册，签名 `(store, op, row_id, payload)`，`threading.Lock` 保护 |
| `replay_from(changes)` | 统一回放（替代 `apply_changes`/`pull_and_replay`，含 UnknownTableError 隔离） |
| `export_snapshot()` / ATTACH 逐表 | 一致性快照（排除 `ha_state`） |
| `import_snapshot_manifest()` | 验证并持久化快照元数据 |
| `ReplicaTarget` | 备机/灾备接口（`push_snapshot`/`push_changes`/`fetch`/`health`），**组合 `Transport`+路径/凭证** |
| `Transport` | **只解决字节如何到对端**（SFTP/https），不持有业务语义 |
| `FailoverController` | 心跳判定 + 双故障域 + epoch fencing + 写租约 + safe mode + `resolve_split_brain` |
| `ha_state` 表 | 持久化角色/epoch/租约时间戳（不进快照恢复） |
| `tick(now, probe_heartbeat, probe_lan) -> Decision` | 纯决策无副作用 |
| `khub dr verify` / `khub ha status` / `khub ha reconcile` | 运维 CLI |

- `HeartbeatChannel` 与 `Transport` 职责正交；`Transport` 只服务字节传输。

## 10. 可观测性（告警与状态）

- **`khub ha status`**：人类可读输出当前角色、最后同步时间戳、对端不可达已持续时长、是否 safe mode、建议动作。
- **切换告警含 5 字段**：① 当前角色 ② 最后同步时间 ③ 对端失联时长 ④ safe mode 状态 ⑤ 建议动作（附决策树）。
- **故障剧本大纲（5 步）**：判活 → 改客户端地址 → `reconcile` 比对 → `resolve_split_brain` 定主 → 校验恢复。文件随仓库提供。

## 11. 交付分期

- **P0 — 远程灾备（MVP，优先）**：多版本快照 + WAL 增量 + 恢复校验（integrity_check+行数+lsn+FTS 抽样 + `dr verify`）+ PITR + `FileReplica` + `SshReplica`。
- **P1 — 双机热备（保守完整）**：`FailoverController`（默认人工确认、自动只检测）+ 双故障域提升 + 写租约 + `replay_from` 回放 + `reconcile` 工具 + `--self-test` + `ha status`/告警/剧本 + `S3Replica`。

## 12. 未覆盖 / 未来工作

- 自动 leader election 集群化。
- 强冲突检测（向量时钟）。
- 快照压缩（gzip/zstd）与清理策略细化。
- 增量快照（只传变更页）。
- 整个 DB 的 TDE / `sqlite3_key`（SEE）评估。
- RPO/RTO 指标与分歧重做流程的运维手册化。

## 14. 实现前评审引发的设计补遗

经实现前评审（对着真实代码，见 `docs/ha_dr/review_impl.md`）确认以下设计级调整，均须落地：

- **P0 拆分（§11）**：P0 实为功能集而非单 MVP。改为 **P0a = FileReplica + 多版本快照 + 恢复校验 + `dr verify`（真 MVP，防误删）**；**SshReplica 与 PITR 降为 P0b（防机器坏/勒索）**，PITR 标为高级项附剧本。
- **WAL 保留策略（§5/§7）**：PITR 要求保留**全量 WAL 历史**，现有 `mark_applied` 后丢弃须改为"归档保留 + 保留窗口"，否则 PITR 落空。
- **lsn 原子性张力（§6.1/§6.2）**：触发器内 `UPDATE lsn_seq` 失败会连带主事务回滚，与"WAL 写失败仅告警不阻塞主事务"矛盾。须将 lsn 分配与主写入**解耦**（独立轻量路径或 `WHEN` 守卫），明确取舍：接受 lsn 缺口、回放按内容比对兜底。
- **本地副本 vs 真正灾备（§0/§1/§5）**：CLI/文档须明确区分，避免"同机另一目录=已灾备"的误导；`dr init` 提示机器归属与每季演练。
- **FTS/vec 重建时机（§7）**：回放路径用内联维护保证逐条可见，仅 PITR 整库恢复后做一次 `rebuild_fts`/`rebuild_vec`（vec 分块后台）。

## 13. 关键单测要点（防回归）

1. 真连 SQLite 断言：业务写入**同事务**落 `replication_log`（含正确 `lsn`）。
2. 备机 `PRAGMA recursive_triggers=OFF` 下，`replay_from` 写主表**不再**触发本机 `replication_log` 重入。
3. mock `now()` + 双探针覆盖 `tick()` 全部状态转换（active→degraded→promoting→active、safe_mode→resolve）。
4. `replay_from` 同一 change 回放两次，行数与 `max(lsn)` 不变（幂等）。
5. 未知表回放抛 `UnknownTableError` 且被隔离、不崩溃整体回放。

## 15. 实现状态（代码落地）

- **P0a 已实现**（commit 见 `m1` 分支）：DB 触发器自动落 WAL + 全局 `lsn`；`replay_from` 幂等 + 防重入（`__replay_lock` WHEN 守卫）+ 未知表隔离；`make_snapshot_db` ATTACH 排除 `ha_state`/虚表；`LocalFileReplica` 多版本；`dr` CLI（init/verify/status/restore）。
- **P0b 已实现**：`SshReplica` 多版本快照（远端 `snapshots/<ts>/` 保留 N 份）+ 全量 WAL 历史保留；`replay_from(target_lsn)` 支持 PITR 截断；`dr push` / `list-snapshots` / `restore --to <lsn|@时间|latest>`（file 与 ssh 均支持）。
- **P0b 关键取舍（偏离设计原句）**：
  - 原子替换：已满足设计 §8 —— 远端文件经 scp 写到 `<remote>.part` 后同连接 `ssh mv` 改名（POSIX rename 原子），终态文件 `chmod 600`；读者不会拉到半成品（防勒索/防损坏）。SFTP 协议本身留 P1，但原子替换与权限收窄目标已达成。
  - WAL 保留：PITR 依赖全量 WAL 历史，当前 `SshReplica.push_changes` 先拉取远端 `wal.ndjson` 再 append，跨调用保留全量（满足 I5 的"不丢弃"），但**未做归档窗口/压缩**（简化，留未来工作）。
  - 无 `lsn<=target` 的快照时 PITR 报错（无法从更晚快照回退已有数据），属设计允许边界。
- **仍待 P1**：双机热备（`FailoverController`/`tick`/`reconcile`/`resolve_split_brain`/`--self-test`/`ha status`/告警/剧本/`S3Replica`）。
