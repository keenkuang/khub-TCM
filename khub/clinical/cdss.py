"""CDSS 规则引擎——if-then 临床告警。"""
from __future__ import annotations
from typing import Any

RULES: list[dict[str, Any]] = [
    {"id": "CDSS001", "condition": "age > 65 AND diagnosis CONTAINS '麻黄'", "severity": "high",
     "alert": "高龄患者使用麻黄需谨慎，可能引起血压升高和心悸"},
    {"id": "CDSS002", "condition": "diagnosis CONTAINS '附子' AND pulse == '数'", "severity": "high",
     "alert": "脉数患者使用附子可能助热，需配伍清热药"},
    {"id": "CDSS003", "condition": "diagnosis CONTAINS '大黄' AND pregnancy == True", "severity": "critical",
     "alert": "大黄妊娠禁用，可能引起子宫收缩"},
    {"id": "CDSS004", "condition": "visit_count > 10 AND adherence < 0.3", "severity": "medium",
     "alert": "频繁就诊但依从性低，建议加强患者教育"},
    {"id": "CDSS005", "condition": "diagnosis CONTAINS '细辛' AND dosage > 3", "severity": "high",
     "alert": "细辛用量超过 3g，可能存在肾毒性风险"},
]


def evaluate(patient_data: dict, diagnosis: str = "", dosage: float = 0) -> list[dict]:
    alerts = []
    age = patient_data.get("age", 0)
    pregnancy = patient_data.get("pregnancy", False)
    adherence = patient_data.get("adherence", 1.0)
    visit_count = patient_data.get("visit_count", 0)
    for rule in RULES:
        triggered = False
        cond = rule["condition"]
        if "age > 65" in cond and age > 65 and "麻黄" in diagnosis:
            triggered = True
        if "附子" in cond and "附子" in diagnosis:
            triggered = True
        if "大黄" in cond and "大黄" in diagnosis and pregnancy:
            triggered = True
        if "visit_count" in cond and visit_count > 10 and adherence < 0.3:
            triggered = True
        if "细辛" in cond and "细辛" in diagnosis and dosage > 3:
            triggered = True
        if triggered:
            alerts.append({"rule_id": rule["id"], "severity": rule["severity"],
                           "alert": rule["alert"]})
    return alerts
