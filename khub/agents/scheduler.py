"""Agent 定时调度器——基于 scheduler.py 的定时 Agent 执行。"""
from __future__ import annotations
import json
import logging
from datetime import datetime
from ..db import Store
from .engine import run_with_llm
from .store import get_agent

logger = logging.getLogger("khub.agents.scheduler")


def run_scheduled(store: Store) -> list[dict]:
    """扫描所有 active 且有 schedule 定义的 Agent，执行到期的。"""
    agents = store.conn.execute(
        "SELECT id, schedule FROM agent_definitions WHERE active=1 AND schedule!=''"
    ).fetchall()
    results = []
    for a in agents:
        schedule = a["schedule"]
        # 简单检查："daily" / "hourly" / "*/N * * * *" (cron-like)
        now = datetime.now()
        last_run = store.conn.execute(
            "SELECT MAX(created_at) as last FROM agent_schedules WHERE agent_id=? AND status='completed'",
            (a["id"],)
        ).fetchone()
        should_run = False
        if not last_run or not last_run["last"]:
            should_run = True
        elif schedule == "hourly":
            last = datetime.fromisoformat(last_run["last"])
            should_run = (now - last).total_seconds() >= 3600
        elif schedule == "daily":
            last = datetime.fromisoformat(last_run["last"])
            should_run = (now - last).total_seconds() >= 86400
        if should_run:
            try:
                result = run_with_llm(store, a["id"], user_input="定时执行",
                                      current_user={"role": "admin", "user_id": 0})
                store.conn.execute(
                    "INSERT INTO agent_schedules (agent_id, cron, status) VALUES (?, ?, 'completed')",
                    (a["id"], schedule))
                results.append({"agent_id": a["id"], "status": "completed"})
                logger.info("定时 Agent #%d 执行完成", a["id"])
            except Exception as e:
                logger.warning("定时 Agent #%d 执行失败: %s", a["id"], e)
                results.append({"agent_id": a["id"], "status": "failed", "error": str(e)})
    return results
