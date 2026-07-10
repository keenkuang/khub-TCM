"""0.4.0 孪生可视化——健康趋势数据、体质画像推断。"""
from __future__ import annotations
from ..db import Store
from .twin_v2 import get_timeline, get_syndrome_evolution


def get_health_trends(store: Store, pid: int) -> dict:
    """返回可视化用结构化数据（前端渲染用 JSON）。"""
    timeline = get_timeline(store, pid)
    evolution = get_syndrome_evolution(store, pid)
    records = store.conn.execute(
        "SELECT visit_date, diagnosis, prescription FROM records "
        "WHERE patient_id=? ORDER BY visit_date", (pid,)
    ).fetchall()
    return {
        "timeline": timeline,
        "syndrome_evolution": evolution,
        "treatment_sequence": [
            {"date": r["visit_date"], "diagnosis": r["diagnosis"],
             "prescription": r["prescription"]} for r in records
        ],
        "body_constitution": _infer_constitution(records, evolution),
    }


def _infer_constitution(records, evolution) -> dict:
    """从历次就诊数据推断体质类型（朴素规则关键词匹配）。"""
    all_diag = " ".join(r.get("diagnosis", "") or "" for r in (records or []))
    all_syn = " ".join(e.get("differentiation", "") or "" for e in (evolution or []))
    text = all_diag + " " + all_syn
    bias = 0
    for kw in ["气虚", "阳虚", "阴虚", "痰湿", "湿热", "血瘀", "气滞"]:
        if kw in text:
            bias += 1
    return {"偏颇体质": bias} if bias > 0 else {"平和体质": 1}
