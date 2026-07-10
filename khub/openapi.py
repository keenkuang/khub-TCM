"""OpenAPI 3.0 规范生成。"""
OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "kHUB API", "version": "0.6.0", "description": "kHUB 个人知识中枢 REST API"},
    "servers": [{"url": "/", "description": "本地服务器"}],
    "paths": {
        "/health": {"get": {"summary": "健康检查", "responses": {"200": {"description": "OK"}}}},
        "/auth/login": {"post": {"summary": "用户登录", "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"username": {"type": "string"}, "password": {"type": "string"}}}}}}, "responses": {"200": {"description": "登录成功"}}}},
        "/api/info": {"get": {"summary": "系统信息", "responses": {"200": {"description": "系统信息"}}}},
        "/api/plugins": {"get": {"summary": "列出已加载的插件", "responses": {"200": {"description": "插件列表"}}}},
        "/api/webhooks": {
            "get": {"summary": "列出 Webhook 订阅", "responses": {"200": {"description": "订阅列表"}}},
            "post": {"summary": "创建 Webhook 订阅", "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"event": {"type": "string"}, "url": {"type": "string"}, "secret": {"type": "string"}}}}}}, "responses": {"201": {"description": "订阅已创建"}}}},
        "/api/openapi.json": {"get": {"summary": "获取 OpenAPI 规范", "responses": {"200": {"description": "OpenAPI 规范"}}}},
        "/api/docs": {"get": {"summary": "Swagger UI 文档页面", "responses": {"200": {"description": "HTML 页面"}}}},
    },
}


def get_spec() -> dict:
    return OPENAPI_SPEC
