"""平台路由（tenants/compliance/analytics/integrations/webhook/plugins/i18n/info/users/sync/clinic）。"""

from fastapi import APIRouter, Depends, Query
from ..deps import get_store
from ...db import Store

router = APIRouter(tags=["platform"])


# ---- Tenants ----
@router.post("/api/tenants")
async def create_tenant(body: dict, store: Store = Depends(get_store)):
    from ...tenants import create_tenant as _create_tenant
    tid = _create_tenant(store, body.get("name", ""), body.get("slug", ""),
                         plan=body.get("plan", "free"))
    return {"tenant_id": tid}


@router.get("/api/tenants")
async def list_tenants(store: Store = Depends(get_store)):
    from ...tenants import list_tenants as _list_tenants
    return {"tenants": _list_tenants(store)}


@router.post("/api/tenants/members")
async def add_tenant_member(body: dict, store: Store = Depends(get_store)):
    from ...tenants import add_member
    add_member(store, body.get("tenant_id", 0), body.get("user_id", 0),
               role=body.get("role", "member"))
    return {"status": "added"}


@router.get("/api/tenants/{tenant_id}/members")
async def list_tenant_members(tenant_id: int, store: Store = Depends(get_store)):
    from ...tenants import list_members
    return {"members": list_members(store, tenant_id)}


# ---- Compliance ----
@router.get("/api/compliance/checklist")
async def compliance_checklist(store: Store = Depends(get_store)):
    from ...compliance import run_checklist
    return run_checklist(store)


@router.get("/api/compliance/report")
async def compliance_report(store: Store = Depends(get_store)):
    from ...compliance import generate_report
    return {"report": generate_report(store)}


# ---- Analytics ----
@router.get("/api/analytics/cohorts")
async def analytics_cohorts(store: Store = Depends(get_store)):
    from ...analytics import patient_cohorts
    return patient_cohorts(store)


@router.get("/api/analytics/efficacy")
async def analytics_efficacy(store: Store = Depends(get_store)):
    from ...analytics import syndrome_efficacy
    return {"efficacy": syndrome_efficacy(store)}


@router.get("/api/analytics/forecast")
async def analytics_forecast(store: Store = Depends(get_store)):
    from ...analytics import visit_forecast
    return visit_forecast(store)


@router.get("/api/analytics/trends")
async def analytics_trends(store: Store = Depends(get_store)):
    from ...analytics import appointment_trends
    return {"trends": appointment_trends(store)}


# ---- Integrations ----
@router.get("/api/integrations/status")
async def integrations_status(store: Store = Depends(get_store)):
    from ...integrations.status import check_all
    return {"integrations": check_all()}


# ---- Webhooks ----
@router.post("/api/webhooks")
async def subscribe_webhook(body: dict, store: Store = Depends(get_store)):
    from ...webhook import subscribe
    try:
        sid = subscribe(store, body.get("event", ""), body.get("url", ""),
                        secret=body.get("secret", ""))
        return {"subscription_id": sid}
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(400, str(e))


@router.get("/api/webhooks")
async def list_webhooks(store: Store = Depends(get_store)):
    from ...webhook import list_subscriptions
    return {"subscriptions": list_subscriptions(store)}


@router.delete("/api/webhooks/{webhook_id}")
async def unsubscribe_webhook(webhook_id: int, store: Store = Depends(get_store)):
    from ...webhook import unsubscribe
    try:
        unsubscribe(store, webhook_id)
        return {"status": "deleted"}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(400, str(e))


# ---- Plugins ----
@router.get("/api/plugins")
async def list_plugins(store: Store = Depends(get_store)):
    from ...plugins.registry import list_plugins as _list_plugins
    return {"plugins": _list_plugins()}


# ---- i18n ----
@router.get("/api/i18n")
async def get_i18n(lang: str = Query(""), store: Store = Depends(get_store)):
    from ...i18n import detect_lang, get_translations
    clang = detect_lang(lang)
    return {"lang": clang, "translations": get_translations(clang)}


@router.get("/api/i18n/langs")
async def get_i18n_langs(store: Store = Depends(get_store)):
    from ...i18n import supported_langs
    return {"languages": supported_langs()}


@router.get("/api/i18n/translate")
async def translate_i18n(key: str = Query(""), lang: str = Query(""), store: Store = Depends(get_store)):
    from ...i18n import t, detect_lang
    target = lang or detect_lang("")
    return {"key": key, "translation": t(key, target), "lang": target}


# ---- Info ----
@router.get("/api/info")
async def api_info(store: Store = Depends(get_store)):
    from ... import __version__
    from ...cache import get as _cache_get, set as _cache_set
    import time
    cached = _cache_get("api_info")
    if cached is not None:
        return cached
    import os
    info = {
        "name": os.environ.get("KHUB_BRAND_NAME", "kHUB"),
        "version": __version__,
        "logo_url": os.environ.get("KHUB_BRAND_LOGO", ""),
        "uptime_sec": int(time.time()),
        "api_version": "0.5.1",
    }
    _cache_set("api_info", info, ttl=5)
    return info


# ---- Users ----
@router.get("/api/users")
async def list_users(store: Store = Depends(get_store)):
    from ...auth import list_users
    return {"users": list_users(store)}


@router.post("/api/users")
async def create_user(body: dict, store: Store = Depends(get_store)):
    from ...auth import create_user as _create_user
    try:
        uid = _create_user(store, body.get("username", ""), body.get("password", ""),
                           display_name=body.get("display_name", ""),
                           role=body.get("role", "user"))
        return {"user_id": uid}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(400, str(e))


@router.put("/api/users/{user_id}/role")
async def update_user_role(user_id: int, body: dict, store: Store = Depends(get_store)):
    from ...auth import update_user_role
    try:
        update_user_role(store, user_id, body.get("role", ""))
        return {"status": "ok"}
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(400, str(e))


# ---- Audit ----
@router.get("/api/admin/audit")
async def admin_audit(event: str = Query(None), actor: str = Query(None),
                      since: str = Query(None), limit: int = Query(100),
                      store: Store = Depends(get_store)):
    from ...audit import search_audit
    results = search_audit(store, event=event, actor=actor, since=since, limit=limit)
    return {"audit_logs": results}


# ---- Sync ----
@router.post("/api/sync/push")
async def sync_push(body: dict, store: Store = Depends(get_store)):
    from ...sync2 import push
    client_id = body.get("client_id", "unknown")
    result = push(store, client_id, body.get("changes", []))
    return result


@router.get("/api/sync/pull")
async def sync_pull(client_id: str = Query("unknown"), since: int = Query(0),
                    store: Store = Depends(get_store)):
    from ...sync2 import pull
    result = pull(store, client_id, since)
    return result


@router.get("/api/sync/status")
async def sync_status(store: Store = Depends(get_store)):
    from ...sync2 import status as _sync_status
    return _sync_status(store)


# ---- Clinic ----
@router.post("/api/clinic/billings")
async def create_billing(body: dict, store: Store = Depends(get_store)):
    from ...clinic.billing import create_billing as _create_billing
    bid = _create_billing(store, body.get("appointment_id", 0), body.get("patient_id", 0),
                          body.get("items", []), method=body.get("method", ""))
    return {"billing_id": bid}


@router.get("/api/clinic/billings")
async def list_billings(patient_id: int = Query(0), store: Store = Depends(get_store)):
    from ...clinic.billing import list_billings
    return {"billings": list_billings(store, patient_id=patient_id)}


@router.post("/api/clinic/billings/{billing_id}/pay")
async def pay_billing(billing_id: int, body: dict, store: Store = Depends(get_store)):
    from ...clinic.billing import pay
    pay(store, billing_id, float(body.get("amount", 0)), method=body.get("method", "cash"))
    return {"status": "paid"}


@router.post("/api/clinic/inventory")
async def add_inventory(body: dict, store: Store = Depends(get_store)):
    from ...clinic.pharmacy import add_stock
    iid = add_stock(store, body.get("herb_name", ""), int(body.get("qty", 0)),
                    unit=body.get("unit", "g"), price=float(body.get("price", 0)))
    return {"inventory_id": iid}


@router.get("/api/clinic/inventory")
async def list_inventory(low_stock: str = Query(""), store: Store = Depends(get_store)):
    from ...clinic.pharmacy import list_inventory
    return {"inventory": list_inventory(store, low_stock=low_stock == "1")}


@router.post("/api/clinic/dispense")
async def dispense_medication(body: dict, store: Store = Depends(get_store)):
    from ...clinic.pharmacy import dispense
    did = dispense(store, body.get("prescription_id", 0), body.get("items", []))
    return {"dispense_id": did}
