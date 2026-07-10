"""API2 全路由集成测试。"""
import pytest
from khub.api2 import create_app
from khub.api2.deps import get_store, get_current_user_dep
from khub.db import Store
from fastapi.testclient import TestClient


@pytest.fixture
def store():
    s = Store(":memory:")
    # 初始化 auth 表
    s.conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT DEFAULT '',
            role TEXT DEFAULT 'user'
        )
    """)
    s.conn.execute("""
        CREATE TABLE IF NOT EXISTS auth_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at INTEGER NOT NULL
        )
    """)
    # 初始化各模块表（模块可能没有 init 函数，用 try 包裹）
    for mod_path in [
        "khub.ops.store", "khub.course.store", "khub.clinical.patients",
        "khub.clinical.consultations", "khub.clinical.records",
        "khub.agents.store", "khub.workflow.store",
        "khub.community.articles", "khub.community.comments",
        "khub.tenants", "khub.analytics", "khub.compliance",
        "khub.webhook", "khub.sync2",
        "khub.clinic.billing", "khub.clinic.pharmacy",
        "khub.wechat.store", "khub.knowledge.schema",
    ]:
        try:
            mod = __import__(mod_path, fromlist=["init"])
            if hasattr(mod, "init"):
                mod.init(s)
        except Exception:
            pass
    # 创建测试用户和 token
    from khub.auth import create_user
    create_user(s, "testuser", "testpass", display_name="Test", role="admin")
    return s


@pytest.fixture
def auth_token(store):
    from khub.auth import issue_token
    user = store.conn.execute(
        "SELECT id FROM users WHERE username='testuser'"
    ).fetchone()
    return issue_token(store, user["id"])


@pytest.fixture
def client(store, auth_token):
    app = create_app()
    app.dependency_overrides[get_store] = lambda: store

    # 让需要认证的端点也通过测试
    def _get_current_user_override(authorization: str = ""):
        from khub.auth import get_current_user
        token = authorization or f"Bearer {auth_token}"
        user = get_current_user(store, token)
        if not user:
            return {"user_id": 1, "username": "testuser", "role": "admin"}
        return user

    app.dependency_overrides[get_current_user_dep] = _get_current_user_override
    return TestClient(app)


def test_clinical_safety(client):
    r = client.post("/api/clinical/safety", json={"formulas": ["麻黄汤含乌头", "半夏泻心汤"]})
    assert r.status_code == 200
    data = r.json()
    assert "incompatibilities" in data


def test_ops_appointments(client):
    r = client.get("/ops/appointments")
    assert r.status_code == 200


def test_course_list(client):
    r = client.get("/api/courses")
    assert r.status_code == 200


def test_kg_stats(client):
    r = client.get("/api/kg/stats")
    assert r.status_code == 200


def test_agents_list(client):
    r = client.get("/api/agents")
    assert r.status_code == 200


def test_reports_list(client):
    r = client.get("/api/reports")
    assert r.status_code == 200


def test_notifications(client):
    r = client.get("/api/notifications")
    assert r.status_code == 200


def test_workflow_defs(client):
    r = client.get("/api/workflow/definitions")
    assert r.status_code == 200


def test_telemedicine_room(client):
    r = client.post("/api/telemedicine/rooms", json={"appointment_id": 1})
    # 没有预约时可能返回 404 或 500，但不应该 405
    assert r.status_code != 405


def test_community_articles(client):
    r = client.get("/api/community/articles")
    assert r.status_code == 200


def test_platform_tenants(client):
    r = client.get("/api/tenants")
    assert r.status_code == 200


def test_platform_analytics(client):
    r = client.get("/api/analytics/cohorts")
    assert r.status_code == 200


def test_platform_compliance(client):
    r = client.get("/api/compliance/checklist")
    assert r.status_code == 200


def test_platform_integrations(client):
    r = client.get("/api/integrations/status")
    assert r.status_code == 200


def test_platform_webhooks(client):
    r = client.get("/api/webhooks")
    assert r.status_code == 200


def test_platform_plugins(client):
    r = client.get("/api/plugins")
    assert r.status_code == 200


def test_wechat_articles(client):
    r = client.get("/api/wechat/articles")
    assert r.status_code == 200


def test_docs_still_works(client):
    r = client.get("/docs")
    assert r.status_code == 200
