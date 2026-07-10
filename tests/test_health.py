import tempfile
from khub.api import App, __version__
from khub.db import Store
from khub.storage import ManagedLibrary
import pytest
pytestmark = pytest.mark.smoke



def test_health_returns_all_fields():
    d = tempfile.mkdtemp()
    store = Store(":memory:")
    lib = ManagedLibrary(d + "/lib")
    app = App(store, lib)
    code, obj = app.dispatch("GET", "/health")
    assert code == 200
    assert obj["status"] == "ok"
    assert obj["version"] == __version__
    assert "uptime_sec" in obj
    assert obj["documents"] >= 0
