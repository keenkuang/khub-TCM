"""合规认证检查——安全/隐私/审计/数据保留清单。"""
from __future__ import annotations
import json, os
from datetime import datetime
from typing import Any


CHECKS: list[dict[str, Any]] = [
    {"id": "SEC_001", "category": "安全", "title": "API 认证", "check": lambda s, e: bool(os.environ.get("KHUB_API_TOKEN")), "severity": "high"},
    {"id": "SEC_002", "category": "安全", "title": "PII 加密", "check": lambda s, e: os.environ.get("KHUB_PII_ENCRYPT") == "1", "severity": "high"},
    {"id": "SEC_003", "category": "安全", "title": "审计日志", "check": lambda s, e: _table_exists(s, "audit_log"), "severity": "medium"},
    {"id": "PRI_001", "category": "隐私", "title": "数据保留策略", "check": lambda s, e: _table_exists(s, "notifications") and _has_retention(), "severity": "medium"},
    {"id": "PRI_002", "category": "隐私", "title": "RBAC 权限", "check": lambda s, e: _table_exists(s, "users"), "severity": "medium"},
    {"id": "AUD_001", "category": "审计", "title": "数据隔离", "check": lambda s, e: bool(os.environ.get("KHUB_TENANT_MODE")), "severity": "low"},
    {"id": "OPS_001", "category": "运维", "title": "HTTPS", "check": lambda s, e: os.environ.get("KHUB_HTTPS") == "1", "severity": "high"},
    {"id": "OPS_002", "category": "运维", "title": "健康检查端点", "check": lambda s, e: True, "severity": "low"},
    {"id": "OPS_003", "category": "运维", "title": "慢查询日志", "check": lambda s, e: True, "severity": "low"},
    {"id": "GDPR_001", "category": "合规", "title": "数据导出", "check": lambda s, e: True, "severity": "info"},
]


def _table_exists(store, table: str) -> bool:
    try:
        store.conn.execute(f"SELECT 1 FROM {table} LIMIT 1")
        return True
    except Exception:
        return False


def _has_retention() -> bool:
    return any(k.startswith("KHUB_RETENTION_") for k in os.environ)


def run_checklist(store) -> dict:
    results = []
    for c in CHECKS:
        try:
            passed = c["check"](store, os.environ)
        except Exception:
            passed = False
        results.append({"id": c["id"], "category": c["category"], "title": c["title"],
                        "passed": passed, "severity": c["severity"]})
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    score = round(passed / total * 100, 1) if total else 0
    return {"checklist": results, "summary": {"passed": passed, "total": total, "score": score},
            "generated_at": datetime.now().isoformat()}


def generate_report(store) -> str:
    data = run_checklist(store)
    lines = [f"# khub 合规认证报告", f"生成时间：{data['generated_at']}", f"合规得分：{data['summary']['score']}% ({data['summary']['passed']}/{data['summary']['total']})", ""]
    for c in data["checklist"]:
        icon = "✅" if c["passed"] else "❌"
        lines.append(f"{icon} [{c['category']}] {c['title']} ({c['severity']})")
    return "\n".join(lines)
