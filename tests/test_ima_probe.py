"""IMA 频率限制探测测试。"""
import json
import os
import tempfile
from khub.ima_probe import probe_once


def test_probe_logs_result():
    """probe_once 应写到日志文件并返回结构化结果。"""
    tmp = os.path.join(tempfile.mkdtemp(), "probe.jsonl")
    r = probe_once(log_path=tmp)
    assert "ts" in r
    assert "ok" in r
    # 日志文件应有一行
    with open(tmp) as f:
        lines = f.readlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["ts"] == r["ts"]
