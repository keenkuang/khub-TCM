"""IMA 科学探测测试。"""
import json
import os
import tempfile
from khub.ima_probe import _probe, _log


def test_probe_returns_all_keys():
    """_probe 返回所有必要字段。"""
    r = _probe("search_knowledge_base")
    for key in ("ok", "endpoint", "http", "code", "msg", "elapsed"):
        assert key in r, f"missing: {key}"


def test_probe_no_credentials_still_has_keys():
    """无凭证时也返回完整结构。"""
    # 确保无凭证
    if not os.environ.get("IMA_CLIENT_ID"):
        r = _probe("search_knowledge_base")
        assert "ok" in r
        assert "endpoint" in r


def test_log_appends():
    """_log 追加一行到日志文件。"""
    r = _probe("search_knowledge_base")
    tmp = os.path.join(tempfile.mkdtemp(), "test.jsonl")
    _log(r, tmp)
    with open(tmp) as f:
        lines = f.readlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["ok"] == r["ok"]
