"""Test health endpoint depth checks."""
from khub.db import Store
import pytest
pytestmark = pytest.mark.smoke


def test_health_deep_fields():
    from khub.api import App
    store = Store(":memory:")
    app = App(store)
    code, obj = app.dispatch("GET", "/health")
    assert code == 200
    assert "status" in obj
    assert "checks" in obj
    assert "db" in obj["checks"]
    assert "disk" in obj["checks"]
