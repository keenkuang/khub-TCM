"""工作流路由。"""

from fastapi import APIRouter, Depends, Query
from ..deps import get_store
from ...db import Store

router = APIRouter(tags=["workflow"])


@router.post("/api/workflow/definitions")
async def create_workflow_def(body: dict, store: Store = Depends(get_store)):
    from ...workflow.store import create_definition
    did = create_definition(store, body.get("name", ""), body.get("steps", []),
                            description=body.get("description", ""))
    return {"definition_id": did}


@router.get("/api/workflow/definitions")
async def list_workflow_defs(store: Store = Depends(get_store)):
    from ...workflow.store import list_definitions
    return {"definitions": list_definitions(store)}


@router.post("/api/workflow/definitions/{def_id}/run")
async def run_workflow(def_id: int, body: dict, store: Store = Depends(get_store)):
    from ...workflow.store import create_instance
    from ...workflow.engine import run
    iid = create_instance(store, def_id, entity_type=body.get("entity_type", ""),
                          entity_id=body.get("entity_id", ""), context=body.get("context"))
    result = run(store, iid)
    return {"instance_id": iid, "result": result}


@router.get("/api/workflow/instances")
async def list_workflow_instances(status: str = Query(""), store: Store = Depends(get_store)):
    from ...workflow.store import list_instances
    return {"instances": list_instances(store, status=status)}
