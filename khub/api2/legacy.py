"""旧 API 代理——将请求转发到旧的 dispatch()。"""
import json
from fastapi import APIRouter, Request, Depends
from .deps import get_store
from ..db import Store

router = APIRouter()


@router.api_route("/legacy/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def legacy_proxy(path: str, request: Request, store: Store = Depends(get_store)):
    from ..api import App
    app = App(store)
    body = await request.body()
    body_dict = json.loads(body) if body else {}
    query_string = str(request.url.query)
    full_path = f"/{path}" + (f"?{query_string}" if query_string else "")
    try:
        code, data = app.dispatch(request.method, full_path, body_dict,
                                   auth_header=request.headers.get("Authorization", ""))
        from fastapi.responses import JSONResponse
        if isinstance(data, str):
            return JSONResponse(content={"data": data}, status_code=code)
        return JSONResponse(content=data, status_code=code)
    except Exception as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(content={"error": str(e)}, status_code=500)
