"""khub 2.0 FastAPI 应用工厂。"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    app = FastAPI(title="kHUB API", version="2.0.0",
                  description="kHUB 个人知识中枢 REST API",
                  docs_url="/docs", redoc_url="/redoc")
    app.add_middleware(CORSMiddleware,
                       allow_origins=["*"], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    from .routers import api_router
    app.include_router(api_router)
    from .legacy import router as legacy_router
    app.include_router(legacy_router)
    return app
