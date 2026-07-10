from fastapi import APIRouter
from .health import router as health_router
from .auth import router as auth_router
from .search import router as search_router
from .clinical import router as clinical_router
from .ops import router as ops_router
from .course import router as course_router
from .knowledge import router as knowledge_router
from .reports import router as reports_router
from .notifications import router as notifications_router
from .agents import router as agents_router
from .workflow import router as workflow_router
from .telemedicine import router as telemedicine_router
from .community import router as community_router
from .platform import router as platform_router
from .wechat import router as wechat_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(search_router)
api_router.include_router(clinical_router)
api_router.include_router(ops_router)
api_router.include_router(course_router)
api_router.include_router(knowledge_router)
api_router.include_router(reports_router)
api_router.include_router(notifications_router)
api_router.include_router(agents_router)
api_router.include_router(workflow_router)
api_router.include_router(telemedicine_router)
api_router.include_router(community_router)
api_router.include_router(platform_router)
api_router.include_router(wechat_router)
