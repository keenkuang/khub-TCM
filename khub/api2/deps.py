"""FastAPI 依赖注入。"""
from __future__ import annotations
import os
from fastapi import Header, HTTPException, Depends
from ..db import Store
from ..auth import get_current_user

_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        db_path = os.environ.get("KHUB_DB", os.path.expanduser("~/.khub/khub.db"))
        _store = Store(db_path)
    return _store


async def get_current_user_dep(authorization: str = Header("")) -> dict:
    store = get_store()
    user = get_current_user(store, authorization)
    if not user:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user
