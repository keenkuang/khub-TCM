"""搜索路由。"""
from fastapi import APIRouter, Depends, Query
from ..deps import get_store, get_current_user_dep
from ...db import Store

router = APIRouter(tags=["search"])


@router.get("/search")
async def search(q: str = "", tag: str = "", cursor: str = "",
                 per: int = Query(20, le=100), store: Store = Depends(get_store)):
    if not q:
        return {"results": []}
    rows = store.conn.execute(
        "SELECT d.canonical_id, d.title, d.updated_at FROM documents d "
        "WHERE d.title LIKE ? ORDER BY d.updated_at DESC LIMIT ?",
        (f"%{q}%", per)).fetchall()
    return {"results": [dict(r) for r in rows], "query": q}


@router.get("/api/search")
async def unified_search(q: str = "", type: str = "all", limit: int = Query(20, le=100),
                          store: Store = Depends(get_store)):
    from ...search2 import unified_search as us
    results = us(store, q, type=type, limit=limit)
    return {"query": q, "count": len(results), "results": results}
