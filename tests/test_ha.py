"""Tests for khub.ha — tick 纯决策 + FailoverController 状态机 + CLI 入口。"""

import json
import os
import socket
import tempfile
import time

import pytest  # for param helpers; not needed but importable

from khub.ha import (
    HAState,
    Decision,
    tick,
    FailoverController,
    build_probes,
    render_status,
)
from khub.db import Store


# ── 辅助 ──────────────────────────────────────────────────────────────────────

def _temp_db():
    _, path = tempfile.mkstemp(suffix=".db")
    try:
        store = Store(path)
        yield store
    finally:
        os.unlink(path)


def _st(role="passive", epoch=1, peer_epoch=0, lease=0.0,
        down_since=None, prev_role="active", manual=False):
    return HAState(role=role, epoch=epoch, peer_epoch=peer_epoch,
                   lease_until=lease, down_since=down_since,
                   prev_role=prev_role, manual=manual)


# ── tick(): 纯决策函数（无 DB/I/O） ──────────────────────────────────────────

def test_tick_active_single_down():
    """active + 仅单域丢失 → degraded + alarm（不提升）。"""
    now = 1000.0
    dec = tick(now, hb_up=False, lan_up=True, state=_st(role="active"))
    assert dec.role == "degraded"
    assert "alarm" in dec.actions
    assert "promote" not in dec.actions


def test_tick_passive_both_down_auto():
    """passive + 双域丢失 + 默认自动 → promoting + promote+alarm。"""
    now = 1000.0
    dec = tick(now, hb_up=False, lan_up=False, state=_st(role="passive"),
               down_since=990.0)
    assert dec.role == "promoting"
    assert "promote" in dec.actions
    assert "alarm" in dec.actions


def test_tick_passive_both_down_manual():
    """passive + 双域丢失 + --manual → degraded + await_manual_promote。"""
    now = 1000.0
    dec = tick(now, hb_up=False, lan_up=False, state=_st(role="passive", manual=True),
               down_since=990.0)
    assert dec.role == "degraded"
    assert "await_manual_promote" in dec.actions
    assert "promote" not in dec.actions


def test_tick_passive_single_down():
    """passive + 单域丢失 → degraded（疑似分区，不提升）。"""
    dec = tick(1000.0, hb_up=False, lan_up=True, state=_st(role="passive"))
    assert dec.role == "degraded"
    assert "promote" not in dec.actions


def test_tick_promoting_stays():
    """promoting → promoting（提升中，未完成）。"""
    dec = tick(1000.0, hb_up=False, lan_up=False,
               state=_st(role="promoting"), down_since=990.0)
    assert dec.role == "promoting"


def test_tick_active_epoch_fencing():
    """active + 见对端更高 epoch → safe_mode。"""
    dec = tick(1000.0, hb_up=True, lan_up=True,
               state=_st(role="active", peer_epoch=5, epoch=3))
    assert dec.role == "safe_mode"
    assert "reconcile" in dec.actions


def test_tick_passive_epoch_fencing():
    """passive + 见对端更高 epoch → safe_mode。"""
    dec = tick(1000.0, hb_up=True, lan_up=True,
               state=_st(role="passive", peer_epoch=5, epoch=3))
    assert dec.role == "safe_mode"
    assert "reconcile" in dec.actions


def test_tick_degraded_recovery():
    """degraded + 对端恢复 → 回到 prev_role（active）。"""
    dec = tick(1000.0, hb_up=True, lan_up=True,
               state=_st(role="degraded", prev_role="active"))
    assert dec.role == "active"
    assert "reconcile" not in dec.actions


def test_tick_safe_mode_stays():
    """safe_mode + 对端存活 → 仍 safe_mode + reconcile。"""
    dec = tick(1000.0, hb_up=True, lan_up=True,
               state=_st(role="safe_mode"))
    assert dec.role == "safe_mode"
    assert "reconcile" in dec.actions


def test_tick_active_both_down():
    """active + 双域丢失 → degraded（不自愈提升，保留主身份）。"""
    now = 1000.0
    dec = tick(now, hb_up=False, lan_up=False, state=_st(role="active"),
               down_since=990.0)
    assert dec.role == "degraded"
    assert "alarm" in dec.actions
    assert "promote" not in dec.actions


def test_tick_peer_down_s_computed():
    """peer_down_s 随 down_since 正确计算。"""
    dec = tick(1000.0, hb_up=False, lan_up=False, state=_st(role="passive"),
               down_since=900.0)
    assert dec.peer_down_s == 100.0


def test_tick_no_decision_for_damaged_reason():
    """safe_mode tick 含原因说明。"""
    dec = tick(1000.0, hb_up=False, lan_up=True,
               state=_st(role="safe_mode"))
    assert dec.safe_mode
    assert "reconcile" in dec.actions


# ── FailoverController（持久化 + promote/demote）─────────────────────────────

def _mk_store(d):
    return Store(os.path.join(d, "test.db"))


def test_controller_state_persist():
    """HAState 通过 ha_state 表持久化后应完整读回。"""
    d = tempfile.mkdtemp()
    try:
        store = _mk_store(d)
        fc = FailoverController(store)
        st = HAState(role="active", epoch=3, peer_epoch=2, lease_until=500.0,
                     down_since=100.0, prev_role="passive", manual=False)
        fc.save(st)

        read = fc.state()
        assert read.role == "active"
        assert read.epoch == 3
        assert read.peer_epoch == 2
        assert read.lease_until == 500.0
        assert read.down_since == 100.0
        assert read.prev_role == "passive"
        assert read.manual is False
    finally:
        import shutil
        shutil.rmtree(d)


def test_controller_promote():
    """promote() 应自增 epoch 并设 role=active。"""
    d = tempfile.mkdtemp()
    try:
        store = _mk_store(d)
        fc = FailoverController(store)
        st0 = fc.state()
        assert st0.role == "passive"
        assert st0.epoch == 1

        st1 = fc.promote()
        assert st1.role == "active"
        assert st1.epoch == 2  # 自增

        read = fc.state()
        assert read.role == "active"
        assert read.epoch == 2
    finally:
        import shutil
        shutil.rmtree(d)


def test_controller_demote():
    """demote() 设 role=passive。"""
    d = tempfile.mkdtemp()
    try:
        store = _mk_store(d)
        fc = FailoverController(store)
        fc.promote()
        st = fc.demote()
        assert st.role == "passive"
        assert fc.state().role == "passive"
    finally:
        import shutil
        shutil.rmtree(d)


def test_controller_demote_to_safe():
    """demote(to_safe=True) 进入 safe_mode。"""
    d = tempfile.mkdtemp()
    try:
        store = _mk_store(d)
        fc = FailoverController(store)
        st = fc.demote(to_safe=True)
        assert st.role == "safe_mode"
    finally:
        import shutil
        shutil.rmtree(d)


# ── build_probes / _tcp_probe ──────────────────────────────────────────────

def test_build_probes_no_host():
    """build_probes 返回 None（file://） → 探针恒 True。"""
    pb, pl = build_probes("file:///tmp/replica")
    assert pb() is True
    assert pl() is True

    pb2, pl2 = build_probes(None)
    assert pb2() is True
    assert pl2() is True

    pb3, pl3 = build_probes("s3://bucket/prefix")
    assert pb3() is True
    assert pl3() is True


def test_build_probes_ssh_host():
    """ssh:// → 探针为 TCP 连接（实际不一定可连，但不抛异常）。"""
    pb, pl = build_probes("ssh://user@192.0.2.1/dr")
    # 192.0.2.1 是保留地址，不可达但不应抛异常（socket 超时应静默返回 False）
    assert pb() is False  # 因为连接会超时/拒绝
    assert pl() is False


def test_tcp_probe_timeout(monkeypatch):
    """socket.create_connection 超时/拒绝 → False。"""
    def _bad(*a, **kw):
        raise OSError("timeout")
    monkeypatch.setattr(socket, "create_connection", _bad)
    from khub.ha.controller import _tcp_probe
    assert _tcp_probe("host", 9999) is False


def test_tcp_probe_success(monkeypatch):
    """socket.create_connection 成功 → True。"""
    class FakeSock:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def close(self):
            pass
    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: FakeSock())
    from khub.ha.controller import _tcp_probe
    assert _tcp_probe("host", 9999) is True


# ── render_status（无探针副作用的快速断言） ────────────────────────────────

def test_render_status_idle(tmp_path):
    """ha status 在无配置时应展示 passive 角色且不抛异常。"""
    store = Store(str(tmp_path / "s.db"))
    fc = FailoverController(store)
    out = render_status(fc)
    assert "passive" in out.lower() or "备" in out
    assert "khub ha status" in out or "===" in out
