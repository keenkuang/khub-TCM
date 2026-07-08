# 第 3 轮（纯设计）三角色评审记录 — 双机热备 & 远程灾备

> 评审对象：第 2 轮定稿 `docs/disaster_recovery.md`（vFinal.2）。
> 评审角色：产品经理 / 顶级架构师 / 顶级软件设计师（三个独立 agent）。
> 结论：三视角均"需修订"，共 **3 个高严重度前提性缺陷** + 多个中/低。修订稿已并入 `docs/disaster_recovery.md`（vFinal.3）。

---

## 一、评审记录（三视角原始意见）

### 1.1 产品经理
- **高 · 痛点缺口**：排序只含误删/改坏/机器坏，缺「勒索加密劫持」「DB 格式损坏打不开」「多设备手动同步冲突」三类个人高频丢失场景；灾备价值感打折。
- **高 · 恢复校验不足**：仅行数+lsn+FTS 抽样（逻辑层），缺 SQLite 自身 `PRAGMA integrity_check`，且无用户可感知报告；快照页损坏/被勒索改写时恢复才暴露。
- **中 · 范围不透明**：STONITH 缺失、演练必要性一笔带过，未说清"不演练=切换必手忙脚乱"的真实成本。
- **中 · P0 过重**：含 Ssh/S3/File 三套 Replica，个人 MVP 有 File+SSH 足够，S3 拖慢首发。
- **低 · 前后矛盾**：§1「人工或保守的自动切换」与 §4.3/§11「默认人工确认、自动只检测不提升」冲突，决策者易误以为有自动切换。
- **低 · 不可救火**：故障剧本仅"配套文档"无大纲；"建议动作"无决策树。

### 1.2 顶级架构师
- **高 · H1 触发器在备机重入（§6.1/§6.3）**：触发器是 DB 级机制，与 `record_change` 短路无关。备机 `apply_changes` 写主表会再次激发 AFTER 触发器，向备机 `replication_log` 重复落 WAL 并自增 lsn，污染回放。原 N9 只堵了 Python API 路径，触发器化反而放大该风险。
- **高 · H2 `lsn` 无真实全局来源（§6.1/§4.5）**：称"单调分配"却无分配器定义；各节点本地计数则在双活/分区时 lsn 区间重叠、非全局可比，`reconcile` 按 lsn 二分的前提不成立。
- **高 · H3 `conn.backup()` 无法排除 `ha_state`（§7）**：`conn.backup()` 拷整库不能按表排除；须备份到临时库后 `DROP TABLE ha_state` 或双库逐表 `INSERT…SELECT` 跳过。且快照含 `replication_log`，备机升主后 lsn 与原主区间冲突，缺续接/重置策略。
- **中 · M1 二进制失真（§6.1）**：`json_object` 不能表示 BLOB，向量 blob/附件入 TEXT 会损坏，须 base64 或改 BLOB 列。
- **中 · M2 触发器反噬可用性（§6.1）**：与主事务同事务，序列化/列错即整条业务写被拒——HA 反而降可用。
- **中 · M3 epoch fencing 不覆盖分区期（§4.4/§4.5）**：旧主在分区内永不见更高 epoch 持续写，fencing 只保护重连后瞬间，窗口须明示。
- **中 · M4 PITR 机制缺位（§5/§11）**：只列特性未给"按目标 lsn 截断回放"实现。
- **中 · M5 `rebuild_vec` 全量阻塞（§7）**：大数据量 O(n) 重建无增量/分块。
- **低 · L1 触发器列枚举随 schema 漂移（§6.1）**：新增列不更新触发器即静默漏记，须代码生成触发器。
- **低 · L2 分区双写被包装成"已知风险"（§4.5）**：实为潜在损坏，应明示并以 PITR 为唯一兜底。

### 1.3 顶级软件设计师
- **高 · 触发器重入（§6.3/§6.1）**：与 H1 同；须备机连接 `PRAGMA recursive_triggers=OFF`，或 `apply_changes` 在 `PRAGMA triggers=OFF` 会话内执行。
- **高 · `lsn` 分配契约缺失（§6.2）**：触发器内如何单调分配 lsn 未定义（需独立 sequence 表、与主写入同事务）；`record_change` 必须复用同一分配器，否则回放 lsn 不连续。
- **高 · `register_replayer` 注册时机/线程安全（§6.3）**：未约定"仅导入期注册、`apply` 启动前完成"，运行时注册会与回放线程竞争全局 dict。须导入期注册 + 模块级锁 + 导入顺序保证。
- **中 · `tick` 可测性与完备（§4.6/§9）**：返回类型未定义（建议返回 `Decision` dataclass：state/actions，无副作用）；状态机需补全全部转换；`resolve_split_brain(keep)` 的 `keep` 未类型化。
- **中 · PITR 截断边界（§7）**：按 lsn 停中途留半事务，恢复校验对不齐；须明确粒度=语句级容忍半事务，或仅允许快照边界恢复。
- **中 · `UnknownTableError` 调用方处理（§6.3）**：schema 迁移后新表回放抛错会使整体崩溃；须"隔离该表+告警/降级"而非整体失败。
- **中 · 派生索引并发（§2/§8）**：`rebuild_fts/rebuild_vec` 须批量回放后统一执行，文档未约束节奏与读锁错开。
- **低 · 安全落地（§8）**：scp 无法"同连接 rename"——原子替换应用 SFTP（put 临时名+rename）或 ssh `mv`；`flock` 仅适用本地 WAL 追加；key 文件生成即 `chmod 600`。
- **低 · 测试策略缺失（§8）**：①断言业务写入同事务落 log；②备机 `recursive_triggers=OFF` 断言 `apply` 不再写 log；③mock 两探针覆盖 `tick` 全转换。
- **低 · 冗余/歧义（§9）**：`record_change` 非主路径建议改名 `manual_record_change`；`Change` 无消费方应删；`apply_changes` 与 `pull_and_replay` 重叠建议统一 `replay_from(changes)`。

---

## 二、评审修订记录（方案据此改动）

| # | 来源 | 严重度 | 问题 | 修订动作 |
|---|------|--------|------|----------|
| P1 | PM | 高 | 痛点缺口（勒索/损坏/冲突） | §0/§1 补足三类场景；远程灾备目标含「防勒索（远端不可改写+版本保留）+ 防损坏（integrity_check）」 |
| P2 | PM | 高 | 恢复校验不足 | §5 增 `PRAGMA integrity_check` 前置 + 写 manifest（lsn/行数/FTS 样本）+ `khub dr verify` 人类可读报告 |
| P3 | PM | 中 | 范围不透明 | §1.3 将演练必要性升级为对决策者的诚实成本项，给建议频率（每季一次切换演练） |
| P4 | PM | 中 | P0 过重 | §11 P0 收敛 FileReplica + SshReplica，S3Replica 移 P1 |
| P5 | PM | 低 | 前后矛盾 | §1 改「切换默认人工确认、自动只检测不提升」；§4.1 明确绑端口/VIP 外部/切后改客户端地址 |
| P6 | PM | 低 | 不可救火 | §10 列故障剧本 5 步大纲 + 「建议动作」决策树 |
| A1 | 架构师 | 高 | 触发器在备机重入 | 复制触发器仅装 Primary；备机 `apply_changes` 前 `PRAGMA recursive_triggers=OFF`（或 `triggers=OFF`） |
| A2 | 架构师 | 高 | `lsn` 无全局来源 | lsn 改为 `(epoch<<48)|local_seq`，由持租约者经 `lsn_seq` 表同事务分配；`reconcile` 按 `(epoch,local_seq)` 比较 |
| A3 | 架构师 | 高 | `conn.backup` 无法排除 ha_state | 快照用 ATTACH 临时库 + 逐表 `INSERT…SELECT` 跳过 `ha_state`；升主后以新 epoch 前缀续接 `replication_log` 并清 `applied` |
| A4 | 架构师 | 中 | BLOB 失真 | payload 中 BLOB 列先 `base64()` 再 `json_object`，或 `payload` 分离 BLOB 列 |
| A5 | 架构师 | 中 | 触发器反噬可用性 | 触发器逻辑最小化；WAL 写失败仅告警不阻塞主事务（明示取舍） |
| A6 | 架构师 | 中 | fencing 不覆盖分区期 | §4.5 明示旧主分区期持续写为已知窗口，PITR 为唯一兜底 |
| A7 | 架构师 | 中 | PITR 缺位 | §5/§7 明确 PITR = 恢复快照后 `apply_changes` 回放至 `lsn<=target` |
| A8 | 架构师 | 中 | rebuild_vec 阻塞 | §7 标注分块/低峰后台重建阻塞成本 |
| A9 | 架构师 | 低 | 触发器列漂移 | §6.1 触发器由代码随 schema 生成，避免手工漏列 |
| A10 | 架构师 | 低 | 分区双写包装风险 | §4.5 明示以 PITR 为兜底，不再称"可接受" |
| D1 | 设计师 | 高 | 触发器重入 | 同 A1，给出备机 `recursive_triggers=OFF` 伪代码 |
| D2 | 设计师 | 高 | lsn 分配契约 | §6.2 补 `lsn_seq` 表 + 触发器内 `UPDATE lsn_seq ... RETURNING val`；`manual_record_change` 复用同一分配器 |
| D3 | 设计师 | 高 | register_replayer 线程安全 | 导入期注册 + `threading.Lock`；运行时注册抛 `RuntimeError` |
| D4 | 设计师 | 中 | tick 可测性 | §4.6/§9 `tick()->Decision(state, actions)` 无副作用；补全部状态转换；`resolve_split_brain(keep: Role)` 类型化 |
| D5 | 设计师 | 中 | PITR 边界 | §7 明确粒度=语句级容忍半事务，或仅快照边界恢复 |
| D6 | 设计师 | 中 | UnknownTableError 处理 | §6.3 调用方"隔离该表+告警/降级"而非整体崩溃 |
| D7 | 设计师 | 中 | 派生索引并发 | §7 约束"批量回放后统一重建，错开读锁" |
| D8 | 设计师 | 低 | 安全落地 | §8 scp→SFTP put+rename；`flock` 仅本地追加；key 生成即 `chmod 600` |
| D9 | 设计师 | 低 | 测试策略 | §8/§9 补三则应测项（同事务落 log / 备机不重入 / tick 全转换） |
| D10 | 设计师 | 低 | 冗余清理 | `record_change`→`manual_record_change`；删无用 `Change`；统一 `replay_from(changes)` |

---

## 三、修订后的修订稿（第 3 轮定稿要点）

> 完整修订稿见 `docs/disaster_recovery.md`（vFinal.3）。本节约其要点：

1. **痛点补全**：覆盖误删/改坏/机器坏 + 勒索加密劫持（远端不可改写+版本保留）+ DB 格式损坏（integrity_check）+ 同步冲突。
2. **恢复校验强化**：`PRAGMA integrity_check` 前置 + 写 manifest（lsn/行数/FTS 样本）+ `khub dr verify` 人类可读报告。
3. **触发器仅装 Primary**；备机回放 `PRAGMA recursive_triggers=OFF`，杜绝重入污染。
4. **lsn 真实全局化**：`(epoch<<48)|local_seq`，`lsn_seq` 表同事务分配，`manual_record_change` 复用；`reconcile` 按 `(epoch,local_seq)` 比较。
5. **快照排除 ha_state**：ATTACH 临时库逐表 `INSERT…SELECT` 跳过；升主以新 epoch 前缀续接 `replication_log` 清 `applied`。
6. **BLOB 安全**：payload 中 BLOB 先 base64；触发器代码随 schema 生成。
7. **可用性取舍**：WAL 写失败仅告警不阻塞主事务（明示）。
8. **PITR**：恢复快照后回放至 `lsn<=target`，粒度语句级容忍半事务。
9. **状态机与并发**：`tick()->Decision` 无副作用；`register_replayer` 导入期+锁；`UnknownTableError` 隔离降级；派生索引批量后统一重建。
10. **交付收敛**：P0 = FileReplica + SshReplica（+recovery 校验+PITR）；S3Replica → P1。
11. **运维诚实化**：切换默认人工确认、自动只检测；切换后改客户端地址；每季演练；故障剧本 5 步 + 决策树。
12. **安全/测试落地**：SFTP put+rename 原子替换、`flock` 本地追加、key `chmod 600`；补三条关键单测。
