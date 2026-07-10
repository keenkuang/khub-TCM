"""数据保留策略引擎——按配置自动清理过期数据。"""
from __future__ import annotations
import os
from datetime import datetime, timedelta

from .db import Store

# 默认保留天数
DEFAULT_RETENTION = {
    "audit_log": 365,           # 审计日志保留 1 年
    "notifications": 90,        # 通知保留 90 天
    "sync_changes": 180,        # 同步变更保留 180 天
    "webhook_deliveries": 30,   # Webhook 投递记录保留 30 天
    "workflow_instances": 90,   # 工作流实例保留 90 天
}


def clean(store: Store, table: str = "", dry_run: bool = False) -> dict:
    """清理过期数据。返回 {table: deleted_count}。"""
    if table:
        tables = [table]
    else:
        tables = list(DEFAULT_RETENTION.keys())
    result = {}
    for tbl in tables:
        days = int(os.environ.get(
            f"KHUB_RETENTION_{tbl.upper()}",
            DEFAULT_RETENTION.get(tbl, 365)))
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        if dry_run:
            cnt = store.conn.execute(
                f"SELECT count(*) as c FROM {tbl} WHERE created_at < ?",
                (cutoff,)
            ).fetchone()["c"]
        else:
            store.conn.execute(f"DELETE FROM {tbl} WHERE created_at < ?", (cutoff,))
            cnt = store.conn.execute("SELECT changes()").fetchone()[0]
        result[tbl] = cnt
    return result
