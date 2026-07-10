"""0.8.2 数据分析——患者分群 + 疗效分析 + 就诊预测 + 预约趋势。"""
from __future__ import annotations

from .db import Store


def patient_cohorts(store: Store) -> dict:
    """患者分群：年龄分布、性别比例、就诊频次分布。"""
    patients = [dict(r) for r in store.conn.execute(
        "SELECT id, name, gender, born FROM patients").fetchall()]
    total = len(patients)
    gender_dist = {}
    age_groups = {"0-18": 0, "19-35": 0, "36-55": 0, "56+": 0}
    for p in patients:
        g = p.get("gender", "") or ""
        gender_dist[g] = gender_dist.get(g, 0) + 1
        if p.get("born"):
            try:
                age = datetime.now().year - int(p["born"][:4])
                if age <= 18: age_groups["0-18"] += 1
                elif age <= 35: age_groups["19-35"] += 1
                elif age <= 55: age_groups["36-55"] += 1
                else: age_groups["56+"] += 1
            except: pass
    # 就诊频次
    freq = store.conn.execute(
        "SELECT patient_id, count(*) as cnt FROM records GROUP BY patient_id").fetchall()
    freq_dist = {"1次": 0, "2-3次": 0, "4-10次": 0, "10次以上": 0}
    for f in freq:
        c = f["cnt"]
        if c == 1: freq_dist["1次"] += 1
        elif c <= 3: freq_dist["2-3次"] += 1
        elif c <= 10: freq_dist["4-10次"] += 1
        else: freq_dist["10次以上"] += 1
    return {"total_patients": total, "gender_distribution": gender_dist,
            "age_groups": age_groups, "visit_frequency": freq_dist}


def syndrome_efficacy(store: Store) -> list[dict]:
    """辨证→方剂疗效分析：从 record_struct + followup_adherence 交叉分析。"""
    rows = store.conn.execute("""
        SELECT rs.differentiation_norm, rs.formula,
               avg(fa.attended) as adherence_rate, count(*) as cases
        FROM record_struct rs
        JOIN records r ON rs.source='record' AND rs.source_id=r.id
        LEFT JOIN followup_plans fp ON fp.patient_id=r.patient_id
        LEFT JOIN followup_adherence fa ON fa.plan_id=fp.id
        WHERE rs.differentiation_norm!='' AND rs.formula!=''
        GROUP BY rs.differentiation_norm, rs.formula
        HAVING cases >= 2
        ORDER BY adherence_rate DESC
    """).fetchall()
    return [dict(r) for r in rows]


def visit_forecast(store: Store, days: int = 30) -> dict:
    """就诊量预测（基于历史周均值 + 线性趋势）。"""
    weekly = store.conn.execute("""
        SELECT strftime('%Y-%W', visit_date) as week, count(*) as visits
        FROM records GROUP BY week ORDER BY week
    """).fetchall()
    if len(weekly) < 4: return {"forecast_days": days, "predicted_visits": 0, "confidence": "low"}
    recent = [r["visits"] for r in weekly[-4:]]
    avg_weekly = sum(recent) / len(recent)
    trend = (recent[-1] - recent[0]) / max(len(recent), 1)
    daily_avg = avg_weekly / 7
    predicted = max(0, int(daily_avg * days + trend * days / 7))
    return {"forecast_days": days, "predicted_visits": predicted,
            "avg_weekly": round(avg_weekly, 1), "confidence": "medium"}


def appointment_trends(store: Store, months: int = 6) -> list[dict]:
    """预约趋势（按月统计）。"""
    rows = store.conn.execute("""
        SELECT strftime('%Y-%m', date) as month, count(*) as total,
               sum(CASE WHEN status='booked' THEN 1 ELSE 0 END) as booked,
               sum(CASE WHEN status='checked_in' THEN 1 ELSE 0 END) as checked_in,
               sum(CASE WHEN status='cancelled' THEN 1 ELSE 0 END) as cancelled
        FROM appointments
        WHERE date >= date('now', ?)
        GROUP BY month ORDER BY month
    """, (f"-{months} months",)).fetchall()
    return [dict(r) for r in rows]
