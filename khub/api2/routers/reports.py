"""报表路由。"""

from fastapi import APIRouter, Depends, Query
from ..deps import get_store
from ...db import Store

router = APIRouter(tags=["reports"])


@router.post("/api/reports")
async def create_report(body: dict, store: Store = Depends(get_store)):
    from ...reports import create_template
    tid = create_template(store, body.get("name", ""), body.get("query", ""),
                          description=body.get("description", ""),
                          chart_type=body.get("chart_type", "table"))
    return {"template_id": tid}


@router.get("/api/reports")
async def list_reports(store: Store = Depends(get_store)):
    from ...reports import list_templates
    return {"templates": list_templates(store)}


@router.post("/api/reports/{report_id}/run")
async def run_report(report_id: int, store: Store = Depends(get_store)):
    if not report_id:
        from fastapi import HTTPException
        raise HTTPException(400, "invalid id")
    from ...reports import execute
    try:
        result = execute(store, report_id)
        return result
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(404, str(e))


@router.get("/api/reports/{report_id}/csv")
async def export_report_csv(report_id: int, store: Store = Depends(get_store)):
    if not report_id:
        from fastapi import HTTPException
        raise HTTPException(400, "invalid id")
    from ...reports import export_csv
    csv_data = export_csv(store, report_id)
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(csv_data, media_type="text/csv; charset=utf-8")
