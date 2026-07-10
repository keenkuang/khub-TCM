"""Uvicorn 启动入口。"""
import uvicorn


def serve(host: str = "127.0.0.1", port: int = 8766):
    from . import create_app
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")
