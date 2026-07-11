"""订阅计划与用量计量。"""
from __future__ import annotations
import os, time
from .db import Store

PLANS = {
    "free": {"max_documents": 100, "max_users": 3, "max_storage_mb": 100, "price_monthly": 0},
    "pro": {"max_documents": 10000, "max_users": 20, "max_storage_mb": 1024, "price_monthly": 199},
    "enterprise": {"max_documents": 1000000, "max_users": 1000, "max_storage_mb": 102400, "price_monthly": 1999},
}

def get_plan(store, tenant_id: int) -> dict:
    tenant = store.conn.execute("SELECT plan FROM tenants WHERE id=?", (tenant_id,)).fetchone()
    return PLANS.get(tenant["plan"] if tenant else "free", PLANS["free"]).copy()

def check_quota(store, tenant_id: int, resource: str) -> dict:
    plan = get_plan(store, tenant_id)
    used = 0
    if resource == "documents":
        used = store.conn.execute("SELECT count(*) as c FROM documents").fetchone()["c"] or 0
    elif resource == "users":
        used = store.conn.execute("SELECT count(*) as c FROM users").fetchone()["c"] or 0
    limit_key = f"max_{resource}"
    limit = plan.get(limit_key, 0)
    return {"plan": tenant["plan"] if (tenant:=store.conn.execute("SELECT plan FROM tenants WHERE id=?", (tenant_id,)).fetchone()) else "free",
            "resource": resource, "used": used, "limit": limit, "exceeded": limit > 0 and used >= limit}

def list_plans() -> list[dict]:
    return [{"name": k, **v} for k, v in PLANS.items()]
