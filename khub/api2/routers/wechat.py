"""微信公众号路由。"""

from fastapi import APIRouter, Depends, Query
from ..deps import get_store
from ...db import Store

router = APIRouter(tags=["wechat"])


@router.post("/api/wechat/articles")
async def create_wechat_article(body: dict, store: Store = Depends(get_store)):
    from ...wechat.store import add_article
    aid = add_article(store, title=body.get("title", ""), content=body.get("content", ""),
                      author=body.get("author", ""), digest=body.get("digest", ""),
                      content_source_url=body.get("content_source_url", ""))
    return {"article_id": aid}


@router.get("/api/wechat/articles")
async def list_wechat_articles(status: str = Query(None), store: Store = Depends(get_store)):
    from ...wechat.store import list_articles
    return {"articles": list_articles(store, status=status)}


@router.post("/api/wechat/schedules")
async def create_wechat_schedule(body: dict, store: Store = Depends(get_store)):
    from ...wechat.store import add_schedule
    sid = add_schedule(store, int(body.get("article_id", 0)),
                       body.get("publish_at", ""), int(body.get("tag_id", 0)))
    return {"schedule_id": sid}


@router.get("/api/wechat/followers")
async def list_wechat_followers(store: Store = Depends(get_store)):
    rows = store.conn.execute(
        "SELECT openid, nickname, city, province, subscribe FROM wechat_followers ORDER BY last_sync_at DESC LIMIT 100"
    ).fetchall()
    return {"followers": rows}
