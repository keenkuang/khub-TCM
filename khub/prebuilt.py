"""0.8.2 预建报表——患者分群/疗效/预测/趋势。"""
from __future__ import annotations

from typing import Any

from . import analytics
from .db import Store


def get_prebuilt_reports() -> list[dict]:
    """返回 4 个预建报表的静态元数据列表。"""
    return [
        {"id": "pb_cohorts", "name": "患者分群分析",
         "description": "年龄/性别/就诊频次分布",
         "chart_type": "pie", "source": "analytics.patient_cohorts"},
        {"id": "pb_efficacy", "name": "辨证方剂疗效",
         "description": "辨证→方剂依从率分析",
         "chart_type": "bar", "source": "analytics.syndrome_efficacy"},
        {"id": "pb_forecast", "name": "就诊量预测",
         "description": "基于历史趋势的未来预测",
         "chart_type": "line", "source": "analytics.visit_forecast"},
        {"id": "pb_trends", "name": "预约趋势",
         "description": "按月预约/签到/取消趋势",
         "chart_type": "line", "source": "analytics.appointment_trends"},
    ]


def _flatten_cohorts(data: dict) -> tuple[list[str], list[dict]]:
    """将 patient_cohorts 的嵌套 dict 展平为 [{dimension, group, value}, ...]。"""
    rows: list[dict] = []
    for dim_key, dim_label in (
        ("gender_distribution", "性别"),
        ("age_groups", "年龄段"),
        ("visit_frequency", "就诊频次"),
    ):
        sub = data.get(dim_key, {})
        for group, value in sub.items():
            rows.append({
                "dimension": dim_label,
                "group": group,
                "value": value,
            })
    # 把 total_patients 也带出去
    rows.insert(0, {
        "dimension": "总计",
        "group": "患者总数",
        "value": data.get("total_patients", 0),
    })
    columns = ["dimension", "group", "value"]
    return columns, rows


def execute_prebuilt(store: Store, pb_id: str, **kwargs: Any) -> dict:
    """执行预建报表，返回统一格式 {columns, rows, row_count, chart_type, chart_data}。"""
    reports = {r["id"]: r for r in get_prebuilt_reports()}
    meta = reports.get(pb_id)
    if meta is None:
        raise ValueError(f"未知的预建报表 id: {pb_id}")

    chart_type = meta["chart_type"]

    if pb_id == "pb_cohorts":
        data = analytics.patient_cohorts(store)
        columns, rows = _flatten_cohorts(data)
    elif pb_id == "pb_efficacy":
        rows = analytics.syndrome_efficacy(store)
        columns = list(rows[0].keys()) if rows else []
    elif pb_id == "pb_forecast":
        data = analytics.visit_forecast(store, **kwargs)
        rows = [data]
        columns = list(data.keys())
    elif pb_id == "pb_trends":
        rows = analytics.appointment_trends(store, **kwargs)
        columns = list(rows[0].keys()) if rows else []
    else:
        raise ValueError(f"未实现的预建报表: {pb_id}")

    # chart_data —— 延迟导入 reports.render_chart
    chart_data = None
    try:
        from .reports import build_chart_data  # type: ignore[attr-defined]
        chart_data = build_chart_data(chart_type, columns, rows)
    except ImportError:
        pass  # render_chart 尚未实现时静默跳过

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "chart_type": chart_type,
        "chart_data": chart_data,
    }
