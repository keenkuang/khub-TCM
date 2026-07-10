"""Test /metrics Prometheus endpoint."""
import os
from khub.db import Store
import pytest
pytestmark = pytest.mark.smoke


def test_metrics_disabled_by_default():
    from khub.api import App
    store = Store(":memory:")
    app = App(store)
    code, obj = app.dispatch("GET", "/metrics")
    assert code == 404  # 默认不启用


def test_metrics_enabled(monkeypatch):
    from khub.api import App
    monkeypatch.setenv("KHUB_METRICS_ENABLED", "1")
    store = Store(":memory:")
    app = App(store)
    code, obj = app.dispatch("GET", "/metrics")
    assert code == 200
    assert "khub_requests_total" in obj
    assert "khub_db_documents" in obj
