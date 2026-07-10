"""0.2.7 孪生摘要增强——增量摘要、时间线、辨证脉络。"""
from __future__ import annotations

import sqlite3

from ..db import Store
from ..llm import get_provider


def _safe_fetchall(conn, sql, params=()):
    """执行查询，表不存在时返回空列表。"""
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []


def _safe_fetchone(conn, sql, params=()):
    """执行单行查询，表不存在时返回 None。"""
    try:
        return conn.execute(sql, params).fetchone()
    except sqlite3.OperationalError:
        return None


def get_timeline(store: Store, pid: int) -> list[dict]:
    """返回患者就诊/问诊时间线（按日期排序）。"""
    rows = _safe_fetchall(store.conn,
        "SELECT id, visit_date, diagnosis, prescription FROM records "
        "WHERE patient_id=? ORDER BY visit_date ASC", (pid,))
    cons = _safe_fetchall(store.conn,
        "SELECT id, date, chief_complaint, differentiation FROM consultations "
        "WHERE patient_id=? ORDER BY date ASC", (pid,))
    timeline = []
    for r in rows:
        timeline.append({"type": "record", "id": r["id"], "date": r["visit_date"],
                         "summary": f"{r['diagnosis'] or ''} — {r['prescription'] or ''}"})
    for c in cons:
        timeline.append({"type": "consultation", "id": c["id"], "date": c["date"],
                         "summary": f"{c['chief_complaint'] or ''} → {c['differentiation'] or ''}"})
    timeline.sort(key=lambda x: (x["date"] or "", x["id"]))
    return timeline


def build_summary_incremental(store: Store, pid: int) -> str:
    """基于已有游标增量聚合孪生摘要。"""
    cur = _safe_fetchone(store.conn,
        "SELECT base_record_id, base_consult_id, summary FROM twin_versions "
        "WHERE patient_id=? ORDER BY id DESC LIMIT 1", (pid,))
    base_rec, base_cons, existing = (cur["base_record_id"], cur["base_consult_id"],
                                     cur["summary"]) if cur else (0, 0, "")
    new_records = _safe_fetchall(store.conn,
        "SELECT id, visit_date, diagnosis FROM records "
        "WHERE patient_id=? AND id > ? ORDER BY id ASC", (pid, base_rec))
    new_consultations = _safe_fetchall(store.conn,
        "SELECT id, date, chief_complaint, differentiation FROM consultations "
        "WHERE patient_id=? AND id > ? ORDER BY id ASC", (pid, base_cons))
    if not new_records and not new_consultations:
        return existing
    context_parts = []
    if existing:
        context_parts.append(f"既有摘要：\n{existing}")
    if new_records:
        lines = "\n".join(f"- {r['visit_date']}：{r['diagnosis'] or '(无)'}"
                         for r in new_records)
        context_parts.append(f"新增病历：\n{lines}")
    if new_consultations:
        lines = "\n".join(f"- {c['date']}：主诉={c['chief_complaint'] or ''}，辨证={c['differentiation'] or ''}"
                         for c in new_consultations)
        context_parts.append(f"新增问诊：\n{lines}")
    prompt = (
        f"你是一名中医助手。请根据以下信息，在既有摘要的基础上补充最新情况，"
        f"生成一份患者健康摘要（辨证脉络、体质变化、治疗趋势）：\n"
        + "\n\n".join(context_parts)
    )
    provider = get_provider()
    try:
        result = provider.complete(prompt) or ""
    except Exception:
        result = ""
    if not result:
        result = _fallback_incremental(new_records, new_consultations)
    max_rec = max((r["id"] for r in new_records), default=base_rec)
    max_cons = max((c["id"] for c in new_consultations), default=base_cons)
    store.conn.execute(
        "INSERT INTO twin_versions (patient_id, base_record_id, base_consult_id, summary) "
        "VALUES (?, ?, ?, ?)", (pid, max_rec, max_cons, result)
    )
    return result


def _fallback_incremental(records, consultations) -> str:
    """NoOpProvider 或无模型时的模板兜底。"""
    parts = ["### 健康摘要（离线模式，基于结构化数据）"]
    for r in records:
        parts.append(f"- {r['visit_date']}：就诊（记录 #{r['id']}）")
    for c in consultations:
        parts.append(f"- {c['date']}：问诊 #{c['id']} — {c['chief_complaint'] or ''}")
    return "\n".join(parts)


def get_syndrome_evolution(store: Store, pid: int) -> list[dict]:
    """抽取历次辨证/舌脉演变。"""
    cons = _safe_fetchall(store.conn,
        "SELECT id, date, differentiation, tongue_pulse FROM consultations "
        "WHERE patient_id=? ORDER BY date ASC", (pid,))
    return [{"consultation_id": c["id"], "date": c["date"],
             "differentiation": c["differentiation"], "tongue_pulse": c["tongue_pulse"]}
            for c in cons if c["differentiation"] or c["tongue_pulse"]]
