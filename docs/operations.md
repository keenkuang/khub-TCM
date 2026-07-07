# 运维手册

## 备份

### 备份内容

- `khub.db` — SQLite 数据库（含文档元数据、FTS 索引、向量索引、患者/排班等业务数据）
- `library/` — 受管库目录，存放已注册的原始文件（PDF/EPUB），按 sha256 分桶

默认数据目录：`~/.khub/`

### 备份命令

```bash
# 数据库
cp "$KHUB_DB" backup/khub-$(date +%Y%m%d).db

# 受管库（若需完整恢复原始文件）
cp -r "$KHUB_LIBRARY" backup/library-$(date +%Y%m%d)
```

### 定时备份建议

```cron
# 每日凌晨 2:00 备份数据库
0 2 * * * cp ~/.khub/khub.db ~/backups/khub-$(date +\%Y\%m\%d).db
```

> cron 中 `%` 需转义为 `\%`。如需同时备份 `library/`，建议用脚本而非单行 crontab。

### 灾难恢复

将备份的 `.db` 文件复制回数据目录即可，无需 rebuild 或迁移：

```bash
cp backup/khub-20260401.db ~/.khub/khub.db
# 服务重启后自动生效
systemctl restart khub
```

> 备份时建议停写（或使用 SQLite WAL 模式），避免拷贝过程中写操作导致不一致。

---

## 日志查看

### systemd 托管

```bash
journalctl -u khub -f          # 实时跟踪
journalctl -u khub -n 50       # 最近 50 行
journalctl -u khub --since "1 hour ago"  # 最近 1 小时
```

### 文件日志

```bash
tail -f /var/log/khub/khub.log
tail -n 100 /var/log/khub/khub.log
```

---

## 健康检查

```bash
curl http://127.0.0.1:8765/health
```

正常响应示例：

```json
{
  "status": "ok",
  "version": "0.2.0",
  "documents": 42,
  "uptime_sec": 3600.0
}
```

> 端口 8765 为默认值，实际端口取决于启动时 `--port` 参数。

异常时返回非 200 状态码或 `status` 不为 `"ok"`。

---

## 性能监控

### 数据库大小

```bash
ls -lh ~/.khub/khub.db
```

### 文档总数

```bash
curl -s http://127.0.0.1:8765/documents | python -c "import sys,json; print(len(json.load(sys.stdin)))"
```

### 向量索引大小

向量索引存储在 SQLite 同一文件（`embeddings` 表）中，不需要单独监控。数据库文件大小已包含向量索引。

---

## 升级操作

```bash
cd /home/keen/khub-m1
git pull origin m1
pip install -e ".[pdf,ann]" --quiet
systemctl restart khub
curl http://127.0.0.1:8765/health
```

步骤说明：

1. `git pull` — 拉取最新代码
2. `pip install -e ".[pdf,ann]"` — 更新依赖（含 PDF 提取与 ANN 向量检索）
3. `systemctl restart khub` — 重启服务
4. `curl .../health` — 确认服务恢复正常

---

## 问题排查

### 服务无法启动

```bash
journalctl -u khub -n 50 --no-pager
```

常见原因：

- Python 依赖缺失 → 检查 `pip list` 确认安装
- 端口占用 → `ss -tlnp | grep 8765`
- 数据库迁移不兼容 → 检查启动日志中 SQLite 错误

### FTS 索引为空

全文检索返回空结果：

- 确认已执行入库（`khub ingest ebook:<sha256>` 或 Web UI 操作）
- 入库操作会自动建 FTS 索引，无需手动干预
- 检查 `documents` 表是否有数据

### 语义检索不返回结果

向量搜索无命中：

- 确认已入库文档已向量化
- 直接查 SQLite 确认 embeddings 表有数据：

```bash
sqlite3 ~/.khub/khub.db "SELECT count(*) FROM embeddings;"
```

返回 0 表示尚未构建向量索引，触发一次入库操作即可。

### 数据库损坏

```bash
sqlite3 ~/.khub/khub.db "PRAGMA integrity_check;"
```

返回 `"ok"` 表示正常。如返回错误信息，从最新备份恢复。
