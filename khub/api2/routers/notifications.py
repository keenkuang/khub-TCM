"""通知路由。"""

from fastapi import APIRouter, Depends, Query
from ..deps import get_store, get_current_user_dep
from ...db import Store

router = APIRouter(tags=["notifications"])


@router.get("/api/notifications")
async def list_notifications(store: Store = Depends(get_store),
                             user: dict = Depends(get_current_user_dep)):
    from ...notifications import list_recent, unread_count
    uid = user.get("user_id", 0)
    return {"notifications": list_recent(store, uid),
            "unread": unread_count(store, uid)}


@router.post("/api/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: int, store: Store = Depends(get_store),
                                  user: dict = Depends(get_current_user_dep)):
    from ...notifications import mark_read
    uid = user.get("user_id", 0)
    mark_read(store, notification_id, uid)
    return {"status": "ok"}


@router.post("/api/notifications/read-all")
async def mark_all_notifications_read(store: Store = Depends(get_store),
                                       user: dict = Depends(get_current_user_dep)):
    from ...notifications import mark_all_read
    uid = user.get("user_id", 0)
    mark_all_read(store, uid)
    return {"status": "ok"}
