"""0.4.0 疗效追踪——就诊频次 + 随访依从性 → 疗效评估。"""
from __future__ import annotations
from ..db import Store


def evaluate_efficacy(store: Store, pid: int) -> dict:
    """评估患者整体疗效趋势。"""
    records = store.conn.execute(
        "SELECT id, visit_date, diagnosis FROM records "
        "WHERE patient_id=? ORDER BY visit_date", (pid,)
    ).fetchall()
    followups = store.conn.execute("""
        SELECT fp.id, fp.due_date, fp.reason, fa.attended
        FROM followup_plans fp
        LEFT JOIN followup_adherence fa ON fa.plan_id=fp.id
        WHERE fp.patient_id=?
    """, (pid,)).fetchall()
    total_followups = len(followups)
    attended = sum(1 for f in followups if f["attended"])
    adherence_rate = attended / max(total_followups, 1)
    visit_count = len(records)
    return {
        "patient_id": pid,
        "visit_count": visit_count,
        "followup_count": total_followups,
        "adherence_rate": round(adherence_rate, 2),
        "followup_compliance": "good" if adherence_rate >= 0.7 else "needs_improvement",
        "treatment_continuity": "consistent" if visit_count >= 3 else "early_stage",
    }
