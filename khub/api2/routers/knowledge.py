"""知识图谱路由（infer/herbs/formulas/syndromes/similarity/search/stats/extract）。"""

from fastapi import APIRouter, Depends, Query
from ..deps import get_store
from ...db import Store

router = APIRouter(tags=["kg"])


def _safe_int(vals, default=0):
    try:
        return int(vals[0]) if vals else default
    except Exception:
        return default


@router.get("/api/kg/infer")
async def kg_infer(syndrome: str = Query(""), store: Store = Depends(get_store)):
    if not syndrome:
        from fastapi import HTTPException
        raise HTTPException(400, "syndrome param required")
    from ...knowledge.inference import infer
    return {"result": infer(store, syndrome)}


@router.get("/api/kg/herbs")
async def kg_herbs(channel: str = Query(""), nature: str = Query(""), store: Store = Depends(get_store)):
    from ...knowledge.herbs import search_herbs
    return {"herbs": search_herbs(store, channel=channel, nature=nature)}


@router.get("/api/kg/formulas")
async def kg_formulas(category: str = Query(""), store: Store = Depends(get_store)):
    from ...knowledge.formulas import list_formulas
    return {"formulas": list_formulas(store, category=category)}


@router.get("/api/kg/syndromes")
async def kg_syndromes(category: str = Query(""), store: Store = Depends(get_store)):
    from ...knowledge.syndromes import list_syndromes
    return {"syndromes": list_syndromes(store, category=category)}


@router.get("/api/kg/similarity")
async def kg_similarity(f1: str = Query(""), f2: str = Query(""), store: Store = Depends(get_store)):
    if not f1 or not f2:
        from fastapi import HTTPException
        raise HTTPException(400, "f1 and f2 required")
    from ...knowledge.formulas import formula_similarity
    return {"formula1": f1, "formula2": f2, "similarity": formula_similarity(store, f1, f2)}


@router.get("/api/kg/search")
async def kg_search(q: str = Query(""), store: Store = Depends(get_store)):
    from ...knowledge.search import search_kg
    return {"results": search_kg(store, q)}


@router.get("/api/kg/stats")
async def kg_stats(store: Store = Depends(get_store)):
    from ...knowledge.search import kg_stats as _kg_stats
    return _kg_stats(store)


@router.post("/api/kg/extract")
async def kg_extract(body: dict, store: Store = Depends(get_store)):
    from ...knowledge.extractor import extract_from_text, cache_names
    cache_names(store)
    return extract_from_text(store, body.get("text", ""))
