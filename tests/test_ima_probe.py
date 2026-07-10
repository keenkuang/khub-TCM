"""IMA 多端点探测测试。"""
import pytest
from khub.ima_probe import _probe, _log
pytestmark = pytest.mark.net



def test_probe_returns_all_keys():
    r = _probe()
    for key in ("ok", "endpoint", "weight", "http", "code", "msg", "elapsed"):
        assert key in r, f"missing: {key}"


def test_probe_rotates_endpoints():
    r1 = _probe()
    if not r1["ok"] and r1["code"] == -99:
        pytest.skip("无 IMAC 凭证")
    ep1 = r1["endpoint"]
    ep2 = _probe()["endpoint"]
    ep3 = _probe()["endpoint"]
    assert len({ep1, ep2, ep3}) >= 2


def test_log_appends():
    import os, tempfile, json
    r = _probe()
    tmp = os.path.join(tempfile.mkdtemp(), "test.jsonl")
    _log(r, tmp)
    with open(tmp) as f:
        assert len(f.readlines()) == 1
