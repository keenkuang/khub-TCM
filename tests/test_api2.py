import pytest
from khub.api2 import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"


def test_info(client):
    r = client.get("/api/info")
    assert r.status_code == 200
    assert r.json()["api_version"] == "2.0"


def test_i18n(client):
    r = client.get("/api/i18n?lang=en")
    assert r.status_code == 200
    assert r.json()["lang"] == "en"


def test_search(client):
    r = client.get("/search?q=test")
    assert r.status_code == 200
    assert "results" in r.json()


def test_docs_available(client):
    r = client.get("/docs")
    assert r.status_code == 200
    assert "swagger" in r.text.lower()


def test_openapi(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert r.json()["info"]["version"] == "2.0.0"
