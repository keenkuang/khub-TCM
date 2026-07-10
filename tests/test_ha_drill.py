"""端到端双节点 failover 演练测试。"""

import os
import shutil
import tempfile

from khub.db import Store
from khub.ha.drill import run_drill, DrillProber, format_drill
from khub.ha.controller import ROLE_ACTIVE, ROLE_PASSIVE, ROLE_DEGRADED, ROLE_SAFE
import pytest
pytestmark = [pytest.mark.slow, pytest.mark.full]



def _tmp():
    base = tempfile.mkdtemp(prefix="khub_drill_test_")
    return {
        "base": base,
        "primary": os.path.join(base, "primary.db"),
        "standby": os.path.join(base, "standby.db"),
        "replica": os.path.join(base, "replica"),
    }


def _find(result, name):
    for c in result.checks:
        if c["name"] == name:
            return c
    return None


def _assert_pass(result):
    failed = [c for c in result.checks if not c["ok"]]
    assert not failed, "drill 失败项: " + "; ".join(
        f"{c['name']}({c['detail']})" for c in failed)


def test_drill_full_lifecycle():
    """默认（自动提升）：完整跑通稳态→提升→脑裂→safe_mode→reconcile→重建恢复。"""
    p = _tmp()
    try:
        result = run_drill(p["primary"], p["standby"], p["replica"], doc_count=5)
        _assert_pass(result)
        assert result.final["auto_promoted"] is True
        assert result.final["B_role"] == ROLE_ACTIVE
        assert result.final["B_epoch"] == 2          # 双域丢失自动提升 +1
        assert result.final["A_role"] in (ROLE_SAFE, ROLE_PASSIVE)
        # 重建备 A2 收敛到权威主 B（关键恢复断言）
        assert _find(result, "重建备 A2 收敛到 B 文档数")["ok"]
        assert _find(result, "B dr verify 通过（权威主健康）")["ok"]
    finally:
        shutil.rmtree(p["base"], ignore_errors=True)


def test_drill_promote_epoch_bump():
    """双域丢失时备机应自动提升且 epoch 自增到 2。"""
    p = _tmp()
    try:
        prober = DrillProber()
        result = run_drill(p["primary"], p["standby"], p["replica"],
                           probe=prober, doc_count=3)
        _assert_pass(result)
        assert result.final["B_epoch"] == 2
        assert _find(result, "B epoch 自增 (+1)")["ok"]
    finally:
        shutil.rmtree(p["base"], ignore_errors=True)


def test_drill_split_brain_fencing():
    """原主在分区期写入后，见到新主更高 epoch 必须进 safe_mode（epoch fencing）。"""
    p = _tmp()
    try:
        result = run_drill(p["primary"], p["standby"], p["replica"], doc_count=4)
        _assert_pass(result)
        assert _find(result, "A 进 safe_mode（epoch fencing）")["ok"]
        assert result.final["A_role"] in (ROLE_SAFE, ROLE_PASSIVE)  # drill 重建后重置为备
    finally:
        shutil.rmtree(p["base"], ignore_errors=True)


def test_drill_manual_mode_no_auto_promote():
    """--manual：双域丢失仅进 degraded + 告警，不自动提升（验证 manual 路径）。"""
    p = _tmp()
    try:
        prober = DrillProber()
        result = run_drill(p["primary"], p["standby"], p["replica"],
                           probe=prober, manual=True, doc_count=3)
        promote = _find(result, "B 自动提升为 active")
        assert promote is not None and not promote["ok"], "manual 模式不应自动提升"
        # 手动模式不自动 fencing（对端 epoch 未超），A 保持 active
        safe = _find(result, "A 进 safe_mode（epoch fencing）")
        assert safe is not None and not safe["ok"]
        # 应记录「等待人工介入」
        assert _find(result, "手动模式：两端未自动提升（B 非 active）")["ok"]
    finally:
        shutil.rmtree(p["base"], ignore_errors=True)


def test_drill_format_runs():
    """format_drill 可正常渲染且不抛异常。"""
    p = _tmp()
    try:
        result = run_drill(p["primary"], p["standby"], p["replica"], doc_count=2)
        out = format_drill(result)
        assert "khub ha drill" in out
        assert "演练通过" in out
    finally:
        shutil.rmtree(p["base"], ignore_errors=True)
