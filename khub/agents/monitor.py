"""Agent 监控——执行记录 + 统计。"""
from __future__ import annotations
from ..db import Store


def record_execution(store: Store, agent_id: int, input_text: str,
                     output: str, duration_ms: float, success: bool) -> int:
    store.conn.execute(
        "INSERT INTO agent_executions (agent_id, input, output, duration_ms, success) VALUES (?, ?, ?, ?, ?)",
        (agent_id, input_text[:200], output[:500], duration_ms, 1 if success else 0))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def agent_stats(store: Store, agent_id: int = 0) -> list[dict]:
    sql = """SELECT agent_id, count(*) as runs,
             avg(duration_ms) as avg_duration,
             sum(CASE WHEN success THEN 1 ELSE 0 END) * 1.0 / count(*) as success_rate
             FROM agent_executions"""
    params = []
    if agent_id:
        sql += " WHERE agent_id=?"; params.append(agent_id)
    sql += " GROUP BY agent_id ORDER BY runs DESC"
    return store.conn.execute(sql, params).fetchall()
