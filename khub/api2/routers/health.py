"""健康检查 + 系统信息 + 国际化。"""
from fastapi import APIRouter, Depends
from ..deps import get_store, get_current_user_dep
from ...db import Store
import time, os

router = APIRouter(tags=["system"])
_START = time.time()


@router.get("/health")
async def health(store: Store = Depends(get_store)):
    checks: dict = {}
    overall = "ok"
    try:
        c = store.conn.execute("SELECT count(*) FROM documents").fetchone()[0]
        checks["db"] = {"ok": True, "documents": c}
    except Exception as e:
        checks["db"] = {"ok": False, "error": str(e)}; overall = "degraded"
    return {"status": overall, "version": "2.0.0", "uptime_sec": int(time.time() - _START), "checks": checks}


@router.get("/api/info")
async def info():
    return {"name": os.environ.get("KHUB_BRAND_NAME", "kHUB"), "version": "2.0.0",
            "uptime_sec": int(time.time() - _START), "api_version": "2.0"}


@router.get("/api/i18n")
async def i18n(lang: str = ""):
    from ...i18n import detect_lang, get_translations
    al = lang or "zh"
    l = detect_lang(al)
    return {"lang": l, "translations": get_translations(l)}
