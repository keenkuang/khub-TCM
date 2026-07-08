# 第 1 轮三角色评审记录 — 双机热备 & 远程灾备

> 评审对象：会话中"双机热备 + 远程灾备"方案（群晖式直连心跳、WAL 实时回放初版）。
> 评审角色：产品经理 / 顶级架构师 / 顶级软件设计师（自定义 agent，因会话内无对应现成 skill）。
> 发起：`U[2863]`「找产品经理、顶级架构师、顶级软件设计师，从三个角度对方案进行评审」。
> 结论：三视角评审全部完成，方案据此修订到位。修订稿即 `docs/disaster_recovery.md`（vFinal）。

---

## 一、评审记录（三视角原始意见）

### 1.1 产品经理（PM）
- 双机**自动切换**对个人 / 小团队是过度投入，真实痛点是"**数据丢失**"。
- 因此**远程灾备（含恢复校验）才是 MVP**，应优先交付；HA 自动 failover 应后置且保持保守。
- **VIP / 集群地址是外部依赖，必须显式声明**出应用层范围。
- **备份不校验等于没备** → 灾备必须带恢复校验。
- 默认只做 HTTP 心跳（直连链路），SSH / File 心跳标为可选。
- 删除 `QuorumChecker`（2 节点无第三方，恒为"未知→不提升"，徒增复杂度），只保留 `LanProbe` 双域判定。
- 需提供 `khub ha status`（人类可读）+ 切换告警 + 故障剧本文档。

### 1.2 顶级软件设计师
- 抽象划分（`HeartbeatChannel` / `ReplicaTarget` / `Transport` 正交）方向良好。
- **事务边界名实不符**：`store_document` 与 `WALLog.record` 各自 commit，所谓"同事务"并不成立 → 必须把事务边界**上提为统一包装一次性提交**。
- `apply_changes` 会退化成巨型 `if/else` → 改**分发表**，把回放知识下沉各域。
- **安全细节**：ssh 走 list 传参、**禁 `shell=True`**；scp 整文件而非远程 `cat >>`；WAL 追加加锁 / rename。
- `tick()` 做成纯决策函数，可注入 `now()` 便于测试。

### 1.3 顶级架构师
- 应用层 WAL 比存储层复制更契合本项目。
- 补出三大硬伤（见下「评审修订记录」）：拷活库半写页、FTS5 虚表不进 WAL、双写窗口未设防。
- 认可：事务原子性、`HeartbeatChannel` 与 `Transport` 正交。

> 注：架构师评审中途曾被中断（`A[2875]`/`A[2884]` 因误判存在 `architect-review` skill 而改用 agent 跑时被打断），其核心关切（事务原子性、抽象正交）已被软件设计师评审覆盖，最终于 `A[2900]` 补齐并确认三视角齐备。

---

## 二、评审修订记录（方案据此改动）

| # | 来源 | 问题 | 修订动作 |
|---|------|------|----------|
| R1 | PM + 设计师/架构师 | "同事务"名实不符，提交后补写 WAL 会静默丢变更 | 事务边界上提为统一包装，`WALLog.record()` 不再内部 commit，与主写入同一事务一次性提交 |
| R2 | 设计师/架构师 | 心跳与复制职责重叠 | `HeartbeatChannel` 与 `ReplicaTarget`/`Transport` 正交，Transport 只服务复制 |
| R3 | 设计师 | `apply_changes` 巨型 if/else | 改为按 `table_name` 分发表，回放知识下沉各域 |
| R4 | 设计师 | 命令注入 / 半写风险 | ssh list 传参禁 `shell=True`；scp 整文件；WAL 追加加锁/rename |
| R5 | PM | 过度设计与范围不清 | 默认 HTTP 心跳；删 `QuorumChecker`；显式声明 VIP/STONITH 超出范围；HA 自动切换后置 |
| R6 | 架构师 | 直接拷活库会出半写页损坏 | 快照改用 `conn.backup()` 生成一致性副本再传 |
| R7 | 架构师 | FTS5 虚表不进 WAL，备机搜索分歧 | 回放后 `rebuild_fts`（向量索引按需重建） |
| R8 | 架构师 | 双写窗口未设防（灰故障） | 引入**写租约**：active 心跳续租，续不上即停写；超时用 `time.monotonic()` + 探针 socket timeout |
| R9 | PM | 备份不可信 | 灾备增加**恢复校验**（行数 / `max_replication_id` / 抽样比对） |
| R10 | PM | 可观测性缺失 | 增加 `khub ha status` + 切换告警 + 故障剧本文档 |
| R11 | PM | 优先级 | 交付分期定为 **P0 远程灾备(MVP) → P1 双机热备(保守)** |
| R12 | 设计师 | 测试性 | `tick()` 纯决策可注入 `now()`；补 `--self-test` 注入链路故障 |

---

## 三、修订后的修订稿（第 1 轮定稿要点）

> 完整修订稿见权威文档 `docs/disaster_recovery.md`（vFinal）。本节约其要点：

1. 两个独立模块：双机热备（热数据，保守自动切换）+ 远程灾备（半冷数据，人工切换）。
2. 原子 WAL：主写入与 `replication_log` 同事务一次性提交，宁可主写入失败也不静默分歧。
3. 防脑裂：提升须**双独立故障域**（直连心跳超时 **且** 业务 LAN `service_addr` 不可达）同时失败；删除 `QuorumChecker`；epoch fencing。
4. 写租约 + `time.monotonic()` + socket timeout 防灰故障双写。
5. 快照 `conn.backup()` 一致性；回放后 `rebuild_fts` 重建派生索引。
6. `apply_changes` 分发表；回放幂等（UPSERT）。
7. 远程灾备带恢复校验；ssh list 传参禁 `shell=True`；scp 整文件。
8. 交付分期 P0（远程灾备 MVP 含校验）→ P1（双机热备保守完整）+ `ha status`/告警/剧本。
9. 显式声明 VIP / STONITH / 真实网络脑裂验证超出应用层范围。
