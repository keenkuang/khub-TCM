"""社区路由。"""

from fastapi import APIRouter, Depends, Query
from ..deps import get_store
from ...db import Store

router = APIRouter(tags=["community"])


@router.post("/api/community/articles")
async def create_community_article(body: dict, store: Store = Depends(get_store)):
    from ...community.articles import create_article
    aid = create_article(store, body.get("title", ""), body.get("content", ""),
                         author_id=0, tags=body.get("tags", []),
                         is_public=body.get("is_public", True))
    return {"article_id": aid}


@router.get("/api/community/articles")
async def list_community_articles(tag: str = Query(""), store: Store = Depends(get_store)):
    from ...community.articles import list_articles as _list_articles
    return {"articles": _list_articles(store, tag=tag)}


@router.get("/api/community/articles/{article_id}")
async def get_community_article(article_id: int, store: Store = Depends(get_store)):
    if not article_id:
        from fastapi import HTTPException
        raise HTTPException(400, "invalid id")
    from ...community.articles import get_article
    article = get_article(store, article_id)
    if not article:
        from fastapi import HTTPException
        raise HTTPException(404, "not found")
    from ...community.comments import list_comments
    return {"article": dict(article), "comments": list_comments(store, article_id)}


@router.get("/api/community/tags")
async def list_community_tags(store: Store = Depends(get_store)):
    from ...community.articles import list_tags
    return {"tags": list_tags(store)}


@router.post("/api/community/comments")
async def add_community_comment(body: dict, store: Store = Depends(get_store)):
    from ...community.comments import add_comment
    cid = add_comment(store, body.get("article_id", 0), body.get("content", ""),
                      author_id=0)
    return {"comment_id": cid}
