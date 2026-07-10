"""鉴权路由。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..deps import get_store, get_current_user_dep
from ...db import Store

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(req: LoginRequest, store: Store = Depends(get_store)):
    from ...auth import authenticate, issue_token
    user = authenticate(store, req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = issue_token(store, user["user_id"])
    return {"token": token, "user": user}


@router.post("/logout")
async def logout(authorization: str = "", store: Store = Depends(get_store)):
    from ...auth import revoke_token
    if authorization.startswith("Bearer "):
        revoke_token(store, authorization[7:])
    return {"status": "ok"}


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user_dep)):
    return {"user": current_user}
