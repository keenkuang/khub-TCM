# 远程灾备与双机热备 — 规划文档

## 目标

为 khub 个人知识中枢构建一套**仅依赖 Python 标准库 + scp 即可搭建**的灾备与高可用方案。核心目标：

- **RPO 尽可能小**：不丢数据。每次关键变更（文档入库、病历更新、孪生体生成）都记录到 WAL 变更日志，备机持续回放。
- **RTO 分钟级**：主库宕机时，人工或自动切换至备机，分钟级恢复服务。
- **零外部依赖**：传输层基于 SSH/SCP（系统自带）或 HTTPS（标准库 `urllib` / `http.server`），无需 Docker、Kubernetes、云 SDK。可选对接对象存储（S3 兼容）作为增强。

## 背景

khub 使用 SQLite 单文件作为主存储，辅以 FTS5 全文索引和 sqlite-vec 向量索引。SQLite 的并发写入能力有限，因此双机方案设计为**主-备（active-passive）架构**：

- **Primary（主动方）**：运行 khub 服务，接受读写请求，实时写入 WAL 变更日志。
- **Standby（被动方 / 热备）**：静默同步 Primary 的变更，不对外提供服务；故障时升为 Primary。
- **Disaster Recovery（远程灾备）**：位于异地，通过快照 + WAL 增量同步，仅用于灾难恢复，不提供热切换。

## WAL 变更日志（replication_log）

核心机制是 `replication_log` 表（由 `WALLog` 类自动创建）。每个"变更操作"记录一行：

```sql
CREATE TABLE replication_log(
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    op          TEXT,           -- "insert" | "update" | "delete"
    table_name  TEXT,           -- 表名，如 documents / patients / records
    row_id      TEXT,           -- 主键值
    payload     TEXT,           -- 变更数据的 JSON 序列化
    at          TEXT,           -- ISO-8601 时间戳
    applied     INTEGER DEFAULT 0  -- 0=未回放, 1=已回放
);
```

- `WALLog.record()` 由核心函数（如 `store_document`、`record_change` 便捷函数）在每次业务变更后调用。
- 备机/灾备端通过 `pending()` 拉取未回放的记录，回放后调用 `mark_applied()` 标记。
- `record_change()` 是未来钩入 `khub/db.py` 等模块的统一入口。

## 快照同步（Snapshot）

WAL 变更日志是增量机制，但备机冷启动或长时间断连后需要基准点。因此引入定期快照：

- **频率**：建议每小时一次（可配置）。
- **内容**：调用 `export_snapshot()` 生成清单（各表行数、`max_replication_id`），并将完整 `.db` 文件（含 FTS5 和 sqlite-vec 表）通过 `LocalFileReplica.push_snapshot()` 复制到备机。
- **恢复流程**：拷贝 DB 快照 → 读取 `snapshot_meta.last_manifest` → 回放 `max_replication_id` 之后的所有 WAL 变更 → 达到一致状态。

## 双机热备工作流

```
Primary                          Standby
  │                                │
  ├─ 实时服务读写                   │ (静默，不对外)
  ├─ 每次变更 → WALLog.record()    │
  ├─ 定时(如 10s) ── push_changes ──→  回放 WAL，mark_applied()
  ├─ 定时(如 1h)  ── push_snapshot ─→  覆盖 DB 快照
  ├─ 心跳 / health check ────────→  响应
  │                                │
  └── 故障 ──→  检测 Primary 离线
                   │
              Standby 升为 Primary
              启动 khub 服务
              接管读写
```

- **心跳检测**：Primary 定期 `health()` 报告在线；Standby 若连续 N 次未收到心跳，可告警或自动切换。
- **切换**：当前设计为**半自动**——检测到故障后由运维（或监控脚本）手动触发切换。自动故障切换（leader election）列为未来工作。

## 远程灾备工作流

```
Primary                          Remote DR Site
  │                                │
  ├─ 定时(如 1h) push_snapshot ──→  覆盖快照文件
  │     (经 SSH/SCP / HTTPS)       │
  ├─ 持续 push_changes ───→  追加到 wal.ndjson
  │     (经 SSH/SCP / HTTPS)       │
  │                                │
  └── 灾难 ──→  人工介入
                  拷贝 DB 快照
                  回放 WAL 至最新
                  启动 khub 服务
```

远程传输使用 SSH（`paramiko` 或原生 `scp` 命令）或 HTTPS 加密，无需额外 VPN。

## 接口合约

`khub/replication.py` 定义了以下核心接口：

| 接口 | 说明 |
|------|------|
| `Change` | 变更记录 data class |
| `WALLog` | WAL 变更日志管理器（record / pending / mark_applied） |
| `export_snapshot()` | 生成快照清单 |
| `import_snapshot_manifest()` | 验证并持久化快照元数据 |
| `ReplicaTarget` | 备机接口抽象（push_snapshot / push_changes / health） |
| `LocalFileReplica` | 本地文件系统参考实现 |

未来远程实现只需继承 `ReplicaTarget`：

- `SshReplica`：经 SSH/SCP 传输到远程服务器。
- `S3Replica`：经 HTTPS 上传到 S3 兼容对象存储。

## 安全

- **PII 加密**：khub 的 `crypto.py` 在 `KHUB_PII_ENCRYPT=1` 时自动加密 PII 字段。快照和 WAL 包含的是密文，传输和存储时无需额外脱敏处理。
- **传输加密**：WAL 变更和快照必须通过 TLS（HTTPS）或 SSH 加密通道传输，禁止明文暴露。

## 未覆盖 / 未来工作

- **自动故障切换**：需要健康检查集群 + leader election 机制（如 etcd / Consul 或基于 `socket` 的简单心跳协议）。
- **冲突检测**：WAL 回放时若目标行已被修改，取最后写入者胜（last-write-wins）。需要更强的冲突检测时可引入向量时钟。
- **备份压缩与清理**：快照和 WAL 文件需定期压缩（gzip/zstd）和清理（保留最近 N 个快照、WAL 超过 M 天可归档）。
- **增量快照**：当前是全量快照，数据量大时可考虑只传输变更页。
- **回放幂等性**：WAL 回放需保证幂等（如 UPSERT 语义），避免重复回放导致数据不一致。
- **加密存储**：PII 密文已加密；但整个 DB 文件可考虑 TDE（透明数据加密）或 SQLite 的 `sqlite3_key`（SEE 扩展），需评估是否纳入核心依赖。
