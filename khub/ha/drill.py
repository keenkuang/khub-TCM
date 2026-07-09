"""端到端双节点 failover 演练。

把两台真实 Store（主 A / 备 B）+ 一个共享 WAL 副本目录（LocalFileReplica）串成
完整的双机热备生命周期，跑通「稳态同步 → 对端双域死 → 备机自动提升 → 脑裂双写
→ 存活节点 epoch fencing 进 safe_mode → reconcile 分歧 → resolve 定主 → 重建恢复」。

设计依据：docs/disaster_recovery.md vFinal.3 §4（状态机）/§4.5（脑裂）/
§10（故障剧本），以及 docs/ha_dr/failover_runbook.md 的 5 步剧本。

probe 可注入（DrillProber 或自定义 callable），用于模拟对端链路状态。
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..db import Store, rebuild_fts as _rebuild_fts
from ..models import CanonicalDoc
from ..replication import (
    ReplicationManager,
    make_replica,
    verify_store,
)
from ..retrieval import rebuild_vec as _rebuild_vec
from .controller import FailoverController, ROLE_ACTIVE, ROLE_PASSIVE, ROLE_DEGRADED, ROLE_SAFE
from .reconcile import reconcile, resolve_split_brain


@dataclass
class DrillProber:
    """可注入的链路状态：drill 在故障/恢复阶段切换，模拟对端双域可达性。"""
    state: str = "up"   # "up" = 双域可达；"down" = 双域丢失

    def set(self, state: str):
        self.state = state

    def hb(self) -> bool:
        return self.state != "down"

    def lan(self) -> bool:
        return self.state != "down"


@dataclass
class DrillResult:
    phases: list = field(default_factory=list)
    checks: list = field(default_factory=list)   # {"name", "ok", "detail"}
    final: dict = field(default_factory=dict)


def _write_docs(store: Store, count: int, start: int = 1):
    for i in range(start, start + count):
        store.store_document(CanonicalDoc(
            canonical_id=f"d{i}", title=f"T{i}", content=f"C{i}",
            source="s", source_id="s/1"))


def _wal_info(store: Store):
    epoch = int(store.ha_get("ha_epoch", "1") or 1)
    n = store.conn.execute("SELECT COUNT(*) FROM replication_log").fetchone()[0]
    return epoch, n


def _doc_count(store: Store) -> int:
    return store.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]


def run_drill(primary_path: str, standby_path: str, replica_dir: str,
              *, probe: Optional[Callable] = None, manual: bool = False,
              doc_count: int = 5) -> DrillResult:
    """端到端双节点 failover 演练。

    Args:
        primary_path: 主库（节点 A）db 路径。
        standby_path: 备库（节点 B）db 路径。
        replica_dir: 共享 WAL 副本目录（A 推送、B 拉取）。
        probe: 注入式链路探针（DrillProber 或返回 (hb_up, lan_up) 的 callable）；
               为 None 时内部用 DrillProber 并在各阶段驱动。
        manual: 是否 --manual（仅检测+告警，不自动提升）。
        doc_count: Phase1 稳态写入的文档数。
    Returns:
        DrillResult：各阶段说明 + 断言检查 + 最终状态。
    """
    os.makedirs(replica_dir, exist_ok=True)
    peer = "file://" + os.path.abspath(replica_dir)
    replica = make_replica(peer)

    # probe 适配：drill 内部用 DrillProber（可切换状态）；外部 callable 直接传
    prober = probe if isinstance(probe, DrillProber) else (probe or DrillProber())
    if isinstance(probe, DrillProber):
        _hb, _lan = prober.hb, prober.lan
    elif callable(probe):
        def _hb():
            r = probe()
            return bool(r[0]) if isinstance(r, tuple) else bool(r)
        def _lan():
            r = probe()
            return bool(r[1]) if isinstance(r, tuple) else bool(r)
    else:
        # probe is None — 使用内部 DrillProber（默认链路正常，由 drill 阶段驱动切换）
        _hb, _lan = prober.hb, prober.lan

    A = Store(primary_path)
    B = Store(standby_path)
    A.ha_set("ha_role", ROLE_ACTIVE); A.ha_set("ha_epoch", "1"); A.conn.commit()
    B.ha_set("ha_role", ROLE_PASSIVE); B.ha_set("ha_epoch", "1"); B.conn.commit()

    a_fc = FailoverController(A, peer=peer, probe_heartbeat=_hb, probe_lan=_lan, manual=manual)
    b_fc = FailoverController(B, peer=peer, probe_heartbeat=_hb, probe_lan=_lan, manual=manual)

    phases: list = []
    checks: list = []

    def check(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})

    # ── Phase 1：稳态同步（A 写 + 推送，B 拉取回放） ──
    _write_docs(A, doc_count, start=1)
    A.flush_wal()
    ReplicationManager(A).push_snapshot(replica, db_path=A.path)
    ReplicationManager(A).push_pending(replica)
    b_fc.cycle()                       # B 拉 WAL 回放 + tick
    a_n, b_n = _doc_count(A), _doc_count(B)
    phases.append(f"Phase1 稳态：A 写 {doc_count} 篇并推送，B 拉取回放")
    check("稳态同步：B 收敛到 A 文档数", b_n == a_n, f"A={a_n}, B={b_n}")
    check("稳态：B 仍为 passive", b_fc.state().role == ROLE_PASSIVE,
          f"role={b_fc.state().role}")

    # ── Phase 2：对端双域死 → B 自动提升（epoch+1）──
    if isinstance(prober, DrillProber):
        prober.set("down")
    b_fc.cycle()                       # passive+双域 → promoting → active, epoch+1
    st_b = b_fc.state()
    a_fc.tick_once()                   # active+双域 → degraded（不自愈提升）
    st_a = a_fc.state()
    phases.append("Phase2 故障：双域丢失，B tick / A tick")
    check("B 自动提升为 active", st_b.role == ROLE_ACTIVE, f"role={st_b.role}")
    check("B epoch 自增 (+1)", st_b.epoch == 2, f"epoch={st_b.epoch}")
    check("A 进 degraded（保留主身份，不自愈提升）", st_a.role == ROLE_DEGRADED,
          f"role={st_a.role}")

    # ── Phase 3：脑裂双写（分区期 A、B 各自写入）──
    _write_docs(A, 3, start=100)       # A（旧主/降级）继续写
    A.flush_wal(); ReplicationManager(A).push_pending(replica)
    _write_docs(B, 3, start=200)       # B（新主）继续写
    B.flush_wal(); ReplicationManager(B).push_pending(replica)
    ae, an = _wal_info(A); be, bn = _wal_info(B)
    phases.append("Phase3 脑裂：A 与 B 各自写入（分区期双写）")
    check("脑裂：A/B 各有 WAL 且 epoch 不同",
          ae != be and an > 0 and bn > 0,
          f"A(epoch={ae},{an}行) B(epoch={be},{bn}行)")

    # ── Phase 4：恢复 → A 见更高 epoch 进 safe_mode（epoch fencing）──
    A.ha_set("ha_peer_epoch", str(b_fc.state().epoch)); A.conn.commit()  # 模拟心跳回报 B epoch
    if isinstance(prober, DrillProber):
        prober.set("up")                # 网络恢复
    a_fc.tick_once()
    st_a = a_fc.state()
    phases.append("Phase4 恢复：A 见 B 更高 epoch → safe_mode")
    check("A 进 safe_mode（epoch fencing）", st_a.role == ROLE_SAFE,
          f"role={st_a.role}")

    # ── Phase 5：reconcile 分歧检测 ──
    report = reconcile(A, B)
    phases.append("Phase5 reconcile：比对双机 WAL")
    check("reconcile 检出分歧", report.divergent > 0,
          f"divergent={report.divergent}; {report.summary}")

    # ── Phase 6/7：定主与恢复 ──
    # B 双域丢失时自动提升为 active（epoch+1）即已成为权威新主；A 见更高 epoch
    # 进 safe_mode（已 fencing）。reconcile 推荐 epoch 较高侧（B）为权威。
    # 故以 B 为权威主：B 已 active，无需 resolve；旧主 A（safe_mode）按 runbook
    # 第 5 步从 B 快照重建为新备（分区双写后朴素 WAL 回放不安全，见 L2）。
    if st_a.role == ROLE_SAFE:
        phases.append("Phase6 定主：reconcile 推荐 epoch 较高侧(B)为权威；B 已 active")
        check("B 为权威新主（active + epoch 自增）",
              st_b.role == ROLE_ACTIVE and st_b.epoch == 2,
              f"role={st_b.role}, epoch={st_b.epoch}")
        # Phase 7：重建 A（safe_mode 旧主）从 B 快照 → 收敛为新备
        rb_dir = tempfile.mkdtemp(prefix="khub_drill_rb_")
        try:
            replica_b = make_replica("file://" + os.path.abspath(rb_dir))
            ReplicationManager(B).push_snapshot(replica_b, db_path=B.path)
            best = replica_b.best_snapshot_for(None)   # 取最新（唯一）快照
            rebuilt = os.path.join(rb_dir, "rebuilt.db")
            shutil.copy(best["db"], rebuilt)
            A2 = Store(rebuilt)
            _rebuild_fts(A2)
            _rebuild_vec(A2)
            A2.set_applied_max(best["lsn"])
            a2_n, b_n2 = _doc_count(A2), _doc_count(B)
            v = verify_store(B)
            phases.append("Phase7 恢复：A 从权威主 B 快照重建为新备；B 校验")
            check("重建备 A2 收敛到 B 文档数", a2_n == b_n2, f"A2={a2_n}, B={b_n2}")
            check("B dr verify 通过（权威主健康）", v["ok"], f"integrity={v['integrity']}")
            # A 作为新备重新加入：对齐角色/epoch 到权威主 B
            A.ha_set("ha_role", ROLE_PASSIVE)
            A.ha_set("ha_epoch", str(st_b.epoch))
            A.conn.commit()
        finally:
            shutil.rmtree(rb_dir, ignore_errors=True)
    else:
        # 手动模式（--manual）：双域丢失未自动提升，两端皆非 active，
        # 等待人工 resolve/rebuild。drill 在此止步（检测已达成）。
        phases.append("Phase6/7（手动模式）：未自动提升，等待人工介入（resolve/rebuild）")
        check("手动模式：两端未自动提升（B 非 active）",
              st_b.role != ROLE_ACTIVE, f"B_role={st_b.role}")

    return DrillResult(
        phases=phases, checks=checks,
        final={
            "A_role": a_fc.state().role, "B_role": b_fc.state().role,
            "B_epoch": b_fc.state().epoch, "A_docs": _doc_count(A),
            "B_docs": _doc_count(B), "auto_promoted": st_b.role == ROLE_ACTIVE,
        })


def format_drill(result: DrillResult) -> str:
    lines = ["=== khub ha drill（端到端双节点 failover 演练）==="]
    for i, p in enumerate(result.phases, 1):
        lines.append(f"  {i}. {p}")
    lines.append("── 断言检查 ──")
    all_ok = True
    for c in result.checks:
        mark = "PASS" if c["ok"] else "FAIL"
        if not c["ok"]:
            all_ok = False
        lines.append(f"  [{mark}] {c['name']}" + (f" — {c['detail']}" if c["detail"] else ""))
    lines.append("── 最终状态 ──")
    for k, val in result.final.items():
        lines.append(f"  {k}: {val}")
    lines.append("演练通过 ✓" if all_ok else "❌ 演练存在失败项，请排查。")
    return "\n".join(lines)
