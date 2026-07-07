"""IMA 频率限制探测测试。"""
import json
import os
import tempfile
from khub.ima_probe import _log, _probe, PROBE_COUNTER


def _reset_counter():
    global PROBE_COUNTER
    PROBE_COUNTER = 0


def test_probe_logs_result():
    """_probe + _log 应写到日志文件并返回结构化结果。"""
    _reset_counter()
    tmp = os.path.join(tempfile.mkdtemp(), "probe.jsonl")
    r = _probe("search_knowledge_base")
    _log(r, log_path=tmp)
    assert "probe_n" in r
    assert "ok" in r
    with open(tmp) as f:
        lines = f.readlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["probe_n"] == r["probe_n"]


def test_probe_counters_increment():
    _reset_counter()
    a = _probe("search_knowledge_base")
    _log(a, "/dev/null")
    b = _probe("list_notebook")
    _log(b, "/dev/null")
    assert b["probe_n"] == a["probe_n"] + 1


def test_probe_returns_all_keys():
    _reset_counter()
    r = _probe("search_knowledge_base")
    for key in ("ok", "endpoint", "http", "code", "elapsed", "probe_n"):
        assert key in r, f"missing key: {key}"
