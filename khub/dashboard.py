from __future__ import annotations

import sqlite3
import time
from .db import Store


# ── 就诊趋势 ──

def visit_trend(store: Store, period: str = "daily", days: int = 30) -> list[dict]:
    """按日/周/月统计 records.visit_date。"""
    fmt_map = {"daily": "%Y-%m-%d", "weekly": "%Y-%W", "monthly": "%Y-%m"}
    fmt = fmt_map.get(period, "%Y-%m-%d")
    try:
        rows = store.conn.execute(
            "SELECT strftime(?, visit_date) AS label, count(*) AS count "
            "FROM records WHERE visit_date >= date('now', ? || ' days') "
            "GROUP BY label ORDER BY label",
            (fmt, f"-{days}"),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def peak_hours(store: Store) -> list[dict]:
    """按小时统计就诊量（从 visit_date 提取 hour 字段）。"""
    try:
        rows = store.conn.execute(
            "SELECT CAST(strftime('%H', visit_date) AS INTEGER) AS hour, count(*) AS count "
            "FROM records WHERE visit_date IS NOT NULL "
            "GROUP BY hour ORDER BY hour"
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


# ── 患者画像 ──

def patient_demographics(store: Store) -> list[dict]:
    """年龄分组(0-18/19-35/36-55/56+) + 性别分布。"""
    try:
        rows = store.conn.execute(
            "SELECT "
            "  CASE "
            "    WHEN CAST(strftime('%Y', 'now') AS INTEGER) - CAST(born AS INTEGER) <= 18 THEN '0-18' "
            "    WHEN CAST(strftime('%Y', 'now') AS INTEGER) - CAST(born AS INTEGER) <= 35 THEN '19-35' "
            "    WHEN CAST(strftime('%Y', 'now') AS INTEGER) - CAST(born AS INTEGER) <= 55 THEN '36-55' "
            "    ELSE '56+' "
            "  END AS age_group, "
            "  gender, count(*) AS count "
            "FROM patients WHERE born IS NOT NULL AND born != '' "
            "GROUP BY age_group, gender ORDER BY age_group, gender"
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def diagnosis_distribution(store: Store, top_n: int = 10) -> list[dict]:
    """TOP N 诊断。"""
    try:
        rows = store.conn.execute(
            "SELECT diagnosis, count(*) AS count FROM records "
            "WHERE diagnosis IS NOT NULL AND diagnosis != '' "
            "GROUP BY diagnosis ORDER BY count DESC LIMIT ?",
            (top_n,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def prescription_frequency(store: Store, top_n: int = 10) -> list[dict]:
    """TOP N 处方。"""
    try:
        rows = store.conn.execute(
            "SELECT prescription, count(*) AS count FROM records "
            "WHERE prescription IS NOT NULL AND prescription != '' "
            "GROUP BY prescription ORDER BY count DESC LIMIT ?",
            (top_n,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


# ── 预约统计 ──

def appointment_stats(store: Store) -> list[dict]:
    """按状态分组。"""
    try:
        rows = store.conn.execute(
            "SELECT status, count(*) AS count FROM appointments GROUP BY status"
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def appointment_by_doctor(store: Store, days: int = 30) -> list[dict]:
    """医生预约量排名。"""
    try:
        rows = store.conn.execute(
            "SELECT doctor, count(*) AS count FROM appointments "
            "WHERE date >= date('now', ? || ' days') "
            "GROUP BY doctor ORDER BY count DESC",
            (f"-{days}",),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def appointment_by_date(store: Store, days: int = 30) -> list[dict]:
    """每日预约数量。"""
    try:
        rows = store.conn.execute(
            "SELECT date AS label, count(*) AS count FROM appointments "
            "WHERE date >= date('now', ? || ' days') "
            "GROUP BY date ORDER BY date",
            (f"-{days}",),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


# ── 收入统计 ──

def billing_summary(store: Store, months: int = 6) -> list[dict]:
    """按月收入汇总。"""
    try:
        rows = store.conn.execute(
            "SELECT strftime('%Y-%m', billed_at) AS month, "
            "  sum(amount) AS total, count(*) AS count "
            "FROM billings "
            "WHERE billed_at >= date('now', 'start of month', ? || ' months') "
            "GROUP BY month ORDER BY month",
            (f"-{months}",),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def billing_by_method(store: Store) -> list[dict]:
    """支付方式分布。"""
    try:
        rows = store.conn.execute(
            "SELECT payment_method, sum(amount) AS total, count(*) AS count "
            "FROM billings GROUP BY payment_method ORDER BY total DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


# ── 综合看板 ──

def dashboard_summary(store: Store) -> dict:
    """一次性返回所有关键指标。"""
    result = {}
    try:
        result["visit_trend"] = visit_trend(store)
    except Exception:
        result["visit_trend"] = []
    try:
        result["demographics"] = patient_demographics(store)
    except Exception:
        result["demographics"] = []
    try:
        result["appointment_stats"] = appointment_stats(store)
    except Exception:
        result["appointment_stats"] = []
    try:
        result["diagnosis_top"] = diagnosis_distribution(store)
    except Exception:
        result["diagnosis_top"] = []
    try:
        result["billing"] = billing_summary(store)
    except Exception:
        result["billing"] = []
    return result


# ── 看板瓦片 CRUD ──

def _init_tiles(store: Store):
    store.conn.execute("""CREATE TABLE IF NOT EXISTS dashboard_tiles(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        tile_type TEXT DEFAULT 'stat',
        query TEXT DEFAULT '',
        chart_type TEXT DEFAULT 'table',
        position INTEGER DEFAULT 0,
        width INTEGER DEFAULT 1,
        height INTEGER DEFAULT 1,
        created_at TEXT
    )""")


def create_tile(
    store: Store,
    name: str,
    tile_type: str = "stat",
    query: str = "",
    chart_type: str = "table",
    position: int = 0,
    width: int = 1,
    height: int = 1,
) -> int:
    _init_tiles(store)
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    cur = store.conn.execute(
        "INSERT INTO dashboard_tiles(name, tile_type, query, chart_type, "
        "position, width, height, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (name, tile_type, query, chart_type, position, width, height, now),
    )
    tid = cur.lastrowid
    store.conn.commit()
    return tid


def list_tiles(store: Store) -> list[dict]:
    _init_tiles(store)
    rows = store.conn.execute(
        "SELECT * FROM dashboard_tiles ORDER BY position, id"
    ).fetchall()
    return [dict(r) for r in rows]


def get_tile(store: Store, tid: int) -> dict | None:
    _init_tiles(store)
    row = store.conn.execute(
        "SELECT * FROM dashboard_tiles WHERE id=?", (tid,)
    ).fetchone()
    return dict(row) if row else None


def update_tile(store: Store, tid: int, **kwargs) -> bool:
    _init_tiles(store)
    if not kwargs:
        return False
    allowed = {"name", "tile_type", "query", "chart_type", "position", "width", "height"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    sets = ", ".join(f"{k}=?" for k in updates)
    params = list(updates.values()) + [tid]
    cur = store.conn.execute(
        f"UPDATE dashboard_tiles SET {sets} WHERE id=?", params
    )
    store.conn.commit()
    return cur.rowcount > 0


def delete_tile(store: Store, tid: int) -> bool:
    _init_tiles(store)
    cur = store.conn.execute(
        "DELETE FROM dashboard_tiles WHERE id=?", (tid,)
    )
    store.conn.commit()
    return cur.rowcount > 0


def reorder_tiles(store: Store, ids: list[int]) -> None:
    """按 ids 顺序更新 position。"""
    _init_tiles(store)
    for pos, tid in enumerate(ids):
        store.conn.execute(
            "UPDATE dashboard_tiles SET position=? WHERE id=?", (pos, tid)
        )
    store.conn.commit()
