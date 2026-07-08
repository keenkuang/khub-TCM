# 双机热备故障剧本（failover runbook）

> 随仓库提供，配合 `khub ha status` / `khub ha reconcile` / `khub ha resolve` 使用。
> 设计依据：docs/disaster_recovery.md vFinal.3 §10（5 步剧本）。

## 总原则
- 应用层不做物理围栏（STONITH）；应用层做到"见到更高 epoch 立即降级停写"。
- 单条故障域丢失（心跳 **或** 业务网任一）**绝不自动提升**，只进 `degraded`；
  必须"心跳链路断 **且** 业务网对端不可达"双独立故障域同时证实，才提升。
- 默认开启自动提升（用户决策）；`--manual` 模式仅检测+告警，提升需人工确认。

## 5 步

### 1. 判活（确认对端真死，而非网络抖动）
- `khub ha status` 看"对端失联时长"与角色。
- 从**第三台机器**或带外（IPMI/控制台）确认对端主机确实宕机/不可达。
- 仅单域丢失 → 等网络恢复，勿提升。

### 2. 改客户端地址（把流量切到新主）
- 若自动提升已发生：确认新主 `khub ha status` 角色=active、epoch 已自增。
- 更新应用/客户端连接串指向新主（或 VIP/健康检查切换到新主）。

### 3. reconcile 比对（判断是否已分叉）
- 新主与旧主（或其最后快照）做分歧检测：
  `khub ha reconcile --left <新主.db> --right <旧主.db>`
- 报告列出 `(epoch, local_seq)` 分叉点与冲突行，给出覆盖/保留/合并建议。

### 4. resolve_split_brain 定主（安全退出 safe_mode）
- 若旧主曾短暂接管写入（脑裂窗口），**以 reconcile 报告为准选定权威主**：
  `khub ha resolve --keep primary|standby`
- 该命令开新 epoch、清除分歧标志、以新 epoch 前缀续接 `replication_log`，
  旧主侧进 safe_mode 停写等待重同步。

### 5. 校验恢复
- 新主 `khub dr verify` 通过；`khub ha status` 角色稳定。
- 旧主作为新备重新 `khub ha run`（指向新主 replica 目录）开始回放追平。

## 决策树（速查）
```
对端失联？
├─ 否 → 正常，无需操作
└─ 是 → 双故障域？（心跳 AND 业务网都断）
   ├─ 否（仅单域）→ degraded，观察，等恢复
   └─ 是（双域）→ 对端死确认
      ├─ 自动模式 → 自动提升为新主（epoch+1）
      └─ --manual → 人工 `khub ha promote`
提升后若发现脑裂 → safe_mode → reconcile → resolve --keep → 校验
```
