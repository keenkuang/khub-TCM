"""Agent 路由（含 ensemble）。"""

from fastapi import APIRouter, Depends, Query
from ..deps import get_store, get_current_user_dep
from ...db import Store

router = APIRouter(tags=["agents"])


@router.post("/api/agents")
async def create_agent(body: dict, store: Store = Depends(get_store)):
    from ...agents.store import create_agent as _create_agent
    aid = _create_agent(store, body.get("name", ""),
                        system_prompt=body.get("system_prompt", ""),
                        tools=body.get("tools", []),
                        description=body.get("description", ""))
    return {"agent_id": aid}


@router.get("/api/agents")
async def list_agents(store: Store = Depends(get_store)):
    from ...agents.store import list_agents as _list_agents
    return {"agents": _list_agents(store)}


@router.post("/api/agents/{agent_id}/run")
async def run_agent(agent_id: int, body: dict, store: Store = Depends(get_store),
                    user: dict = Depends(get_current_user_dep)):
    from ...agents.engine import run_with_llm
    result = run_with_llm(store, agent_id, user_input=body.get("input", ""),
                          current_user=user)
    return result


@router.get("/api/agents/templates")
async def list_agent_templates(category: str = Query(""), store: Store = Depends(get_store)):
    from ...agents.templates import list_templates, seed
    seed(store)
    return {"templates": list_templates(store, category=category)}


@router.post("/api/agents/create-from-template")
async def create_agent_from_template(body: dict, store: Store = Depends(get_store)):
    from ...agents.templates import create_from_template
    aid = create_from_template(store, body.get("template_id", 0), name=body.get("name", ""))
    return {"agent_id": aid}


@router.post("/api/agents/memory")
async def store_agent_memory(body: dict, store: Store = Depends(get_store)):
    from ...agents.memory import store as mem_store
    mem_store(store, body.get("agent_id", 0), body.get("key", ""),
              body.get("value", ""), type=body.get("type", "string"))
    return {"status": "stored"}


@router.get("/api/agents/{agent_id}/memory")
async def list_agent_memory(agent_id: int, store: Store = Depends(get_store)):
    from ...agents.memory import list_memory as _list_memory
    return {"memory": _list_memory(store, agent_id)}


@router.post("/api/agents/pipelines")
async def create_agent_pipeline(body: dict, store: Store = Depends(get_store)):
    from ...agents.pipeline import create_pipeline
    pid = create_pipeline(store, body.get("name", ""), body.get("agent_ids", []),
                          description=body.get("description", ""))
    return {"pipeline_id": pid}


@router.get("/api/agents/pipelines")
async def list_agent_pipelines(store: Store = Depends(get_store)):
    from ...agents.pipeline import list_pipelines
    return {"pipelines": list_pipelines(store)}


@router.post("/api/agents/pipelines/{pipeline_id}/run")
async def run_agent_pipeline(pipeline_id: int, body: dict, store: Store = Depends(get_store),
                             user: dict = Depends(get_current_user_dep)):
    from ...agents.pipeline import run as run_pipeline
    results = run_pipeline(store, pipeline_id, input_text=body.get("input", ""),
                           current_user=user)
    return {"results": results}


@router.post("/api/agents/parallel")
async def agents_parallel(body: dict, store: Store = Depends(get_store),
                          user: dict = Depends(get_current_user_dep)):
    from ...agents.ensemble import run_parallel
    results = run_parallel(store, body.get("agent_ids", []), input_text=body.get("input", ""),
                           current_user=user)
    return {"results": results}


@router.post("/api/agents/vote")
async def agents_vote(body: dict, store: Store = Depends(get_store),
                      user: dict = Depends(get_current_user_dep)):
    from ...agents.ensemble import vote
    result = vote(store, body.get("agent_ids", []), input_text=body.get("input", ""),
                  current_user=user)
    return result


@router.post("/api/agents/cascade")
async def agents_cascade(body: dict, store: Store = Depends(get_store),
                         user: dict = Depends(get_current_user_dep)):
    from ...agents.ensemble import cascade
    results = cascade(store, body.get("pipeline", []), input_text=body.get("input", ""),
                      current_user=user)
    return {"results": results}
