"""双机热备核心：纯决策函数 tick() + FailoverController 状态机。

设计依据：docs/disaster_recovery.md vFinal.3 §4（状态机）/§4.3（双故障域）/
§4.4（写租约）/§4.5（脑裂）/§6.2（epoch 围栏）。

关于 epoch 与 lsn 的实现取舍（已与计划对齐，避免动摇 P0b）：
- 本实现将 epoch 作为独立值持久化于 ha_state（ha_epoch），用于
  (a) 控制层 epoch fencing（见对端更高 epoch → safe_mode）；
  (b) reconcile 按 (epoch, local_seq) 比对分叉。
- replication_log.lsn 当前 = local_seq（触发器内 `UPDATE lsn_seq` 分配），
  未烘焙 epoch<<48 前缀。reconcile/ fencing 改由显式 epoch 承载，
  功能等价且不影响 P0b 既有行为；后续如需严格 lsn 前缀可单独演进。
"""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..db import Store
from ..replication import make_replica, ReplicationManager
from ..scheduler import Scheduler

logger = logging.getLogger("khub.ha")

# 写租约有效期（秒）：持租约者在该窗口内可写；超时未续则视为失租。
LEASE_SECONDS = 30.0

# 角色集合
ROLE_ACTIVE = "active"
ROLE_PASSIVE = "passive"
ROLE_DEGRADED = "degraded"
ROLE_PROMOTING = "promoting"
ROLE_SAFE = "safe_mode"
ROLES = {ROLE_ACTIVE, ROLE_PASSIVE, ROLE_DEGRADED, ROLE_PROMOTING, ROLE_SAFE}


@dataclass
class HAState:
    """控制器持久化的高可用状态（来自 ha_state 表）。"""
    role: str = ROLE_PASSIVE
    epoch: int = 1                       # 本节点当前 epoch
    peer_epoch: int = 0                  # 心跳中观察到的对端 epoch
    lease_until: float = 0.0             # 单调时钟下的租约到期秒；0=无租约
    down_since: Optional[float] = None   # 对端首次被判不可达的单调秒；None=可达
    prev_role: str = ROLE_ACTIVE         # 进入 degraded 前的稳定角色（用于恢复）
    manual: bool = False                 # --manual：仅检测+告警，不自动提升

    def peer_down_s(self, now: float) -> float:
        if self.down_since is None:
            return 0.0
        return max(0.0, now - self.down_since)


@dataclass
class Decision:
    """tick() 的纯决策结果（无副作用）。"""
    role: str
    actions: list = field(default_factory=list)   # promote/alarm/reconcile/await_manual_promote/noop
    peer_down_s: float = 0.0
    safe_mode: bool = False
    reason: str = ""


def _optfloat(v, default=None):
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def tick(now: float, hb_up: bool, lan_up: bool, state: HAState,
         down_since: Optional[float] = None) -> Decision:
    """纯决策函数：依据双域探针结果与当前状态，返回新角色与动作。

    - 无任何 I/O、不读写数据库、不修改 state；传 bool 探针结果，便于单测。
    - 双独立故障域：hb_up=心跳链路，lan_up=业务网对端 service_addr。
      单一链路丢失 → degraded（绝不提升）；双域均不可达 → 对端死确认。
    - epoch fencing：观察到对端更高 epoch → safe_mode 立即停写。
    - 默认自动提升（用户决策）：双域证实对端死时 passive/degraded → promoting；
      若 state.manual=True 则只进 degraded 并报 await_manual_promote。

    Args:
        now: 单调时钟秒。
        hb_up: 心跳链路是否存活。
        lan_up: 业务网对端是否可达。
        state: 当前 HAState。
        down_since: 对端首次不可达的单调秒（由控制器维护，传入便于决策）。
    """
    # ── epoch fencing：旧主/备见到对端更高 epoch → 立即降级停写 ──
    if state.peer_epoch > state.epoch and state.role in (ROLE_ACTIVE, ROLE_PASSIVE):
        return Decision(
            ROLE_SAFE, ["alarm", "reconcile"], state.peer_down_s(now), True,
            f"见对端更高 epoch（{state.peer_epoch}>{state.epoch}），"
            f"立即降级停写（epoch fencing）")

    both_up = hb_up and lan_up
    down_s = (now - down_since) if down_since is not None else 0.0

    if both_up:
        # 对端存活
        if state.role in (ROLE_ACTIVE, ROLE_PROMOTING):
            # ROLE_PROMOTING 理论上不会被持久化（_promote 在同一决策周期内
            # 将 role 设为 active），保留作为安全兜底——若 ha_state 因异常残留
            # 'promoting'，见到对端存活就回到 active，避免卡在过渡态。
            return Decision(ROLE_ACTIVE, [], 0.0, False, "对端存活，主角色正常")
        if state.role == ROLE_DEGRADED:
            return Decision(state.prev_role, [], 0.0, False, "对端恢复，回到原角色")
        if state.role == ROLE_SAFE:
            return Decision(ROLE_SAFE, ["reconcile"], 0.0, True,
                            "safe_mode，需 reconcile 定主")
        return Decision(ROLE_PASSIVE, [], 0.0, False, "备机正常，持续回放")

    # ── 至少一条故障域丢失 ──
    single = (hb_up != lan_up)   # 恰有一条丢失 = 疑似分区（不提升）

    if state.role == ROLE_ACTIVE:
        # 主角色：单/双域丢失都先进 degraded，保留主身份，不自愈提升
        # （避免活跃主在被网络抖动误判时自废武功；提升只由备机侧触发）
        return Decision(ROLE_DEGRADED, ["alarm"], down_s, False,
                        "主角色故障域丢失→degraded，保留主身份待重连/人工")

    if state.role == ROLE_PASSIVE:
        if single:
            return Decision(ROLE_DEGRADED, ["alarm"], down_s, False,
                            "仅单故障域丢失→degraded（疑似分区），不提升")
        # 双域均不可达 → 对端死确认（双独立故障域）
        if state.manual:
            return Decision(ROLE_DEGRADED, ["alarm", "await_manual_promote"], down_s,
                            False, "对端死（双域），但 --manual：等待人工提升")
        return Decision(ROLE_PROMOTING, ["promote", "alarm"], down_s, False,
                        "对端死（双域）→ 自动提升为新主")

    if state.role == ROLE_DEGRADED:
        if state.prev_role == ROLE_ACTIVE:
            # 原主降级来的：即便双域丢失也不自提升，避免与真备同时晋升
            # 导致 epoch 碰撞、重连后静默脑裂。仅告警等待对端恢复或人工介入。
            # 提升必须仅由原本非 active 的节点触发（设计 §4.3）。
            return Decision(ROLE_DEGRADED, ["alarm"], down_s, False,
                            "原主 degraded：双域丢失仍不自愈提升，待对端恢复或人工推进")
        # degraded 原为备机（prev_role=passive）：与 passive 逻辑一致
        if single:
            return Decision(ROLE_DEGRADED, ["alarm"], down_s, False,
                            "仅单故障域丢失→仍 degraded，不提升")
        if state.manual:
            return Decision(ROLE_DEGRADED, ["alarm", "await_manual_promote"], down_s,
                            False, "对端死（双域），--manual：等待人工提升")
        return Decision(ROLE_PROMOTING, ["promote", "alarm"], down_s, False,
                        "对端死（双域），原备→自动提升为新主")

    if state.role == ROLE_PROMOTING:
        return Decision(ROLE_PROMOTING, ["promote"], down_s, False, "提升中")

    if state.role == ROLE_SAFE:
        return Decision(ROLE_SAFE, ["alarm", "reconcile"], down_s, True,
                        "safe_mode，需 reconcile 定主")

    return Decision(state.role, [], down_s, state.safe_mode, "未变化")


def _tcp_probe(host: str, port: int, timeout: float = 2.0) -> bool:
    """TCP 连通性探针（独立故障域用不同端口区分）。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _peer_host(peer: str) -> Optional[str]:
    """从 file:// / ssh:// / s3:// 目标串解析主机（用于 TCP 探针）。"""
    if peer.startswith("ssh://"):
        # ssh://user@host/path
        body = peer[len("ssh://"):]
        if "@" in body:
            body = body.split("@", 1)[1]
        return body.split("/", 1)[0].split(":")[0] or None
    if peer.startswith("s3://"):
        # s3://bucket[/prefix] → 无主机，返回 None（S3 用对象存，TCP 探活无意义）
        return None
    return None  # file:// 同机副本，不跨机，无对端探针


def build_probes(peer: Optional[str], hb_port: int = 8001,
                 lan_port: int = 8000) -> tuple[Callable[[], bool], Callable[[], bool]]:
    """依据 peer 构造（probe_heartbeat, probe_lan）。

    双故障域：心跳链路走 hb_port，业务网走 lan_port（默认与 serve 端口一致）。
    无法解析主机（file:// 或 s3://）时探针恒为 True（即"视为可达"，
    不触发故障切换），避免误判。
    """
    host = _peer_host(peer) if peer else None
    if not host:
        return (lambda: True, lambda: True)
    return (lambda: _tcp_probe(host, hb_port),
            lambda: _tcp_probe(host, lan_port))


class FailoverController:
    """双机热备控制器：驱动 tick 决策、持久化状态、连续回放 WAL。

    用法（备机）::

        fc = FailoverController(store, peer="ssh://user@host/path",
                                manual=False)
        fc.run(interval=5)   # 阻塞：每 5s 拉 WAL + tick 决策

    或按需单次决策（CLI 调用）::

        fc = FailoverController(store, peer=...)
        dec = fc.tick_once()
    """

    def __init__(self, store: Store, peer: Optional[str] = None,
                 probe_heartbeat: Optional[Callable[[], bool]] = None,
                 probe_lan: Optional[Callable[[], bool]] = None,
                 manual: bool = False):
        self.store = store
        self.peer = peer
        if probe_heartbeat is None or probe_lan is None:
            pb, pl = build_probes(peer)
            probe_heartbeat = probe_heartbeat or pb
            probe_lan = probe_lan or pl
        self.probe_heartbeat = probe_heartbeat
        self.probe_lan = probe_lan
        # manual 取值：构造参数优先，否则读已持久化的 ha_manual
        persisted = store.ha_get("ha_manual", "0") == "1"
        self.manual = manual or persisted
        # 缓存 ReplicaTarget（避免每 tick 重建 SshReplica 时产生 tempdir 泄漏）
        self._replica = make_replica(peer) if peer else None

    # ── 状态读写 ──────────────────────────────────────────────────────────
    def state(self) -> HAState:
        hg = self.store.ha_get
        return HAState(
            role=hg("ha_role", ROLE_PASSIVE),
            epoch=int(hg("ha_epoch", "1") or 1),
            peer_epoch=int(hg("ha_peer_epoch", "0") or 0),
            lease_until=_optfloat(hg("ha_lease_until"), 0.0) or 0.0,
            down_since=_optfloat(hg("ha_down_since")),
            prev_role=hg("ha_prev_role", ROLE_ACTIVE),
            manual=self.manual,
        )

    def save(self, st: HAState):
        hs = self.store.ha_set
        hs("ha_role", st.role)
        hs("ha_epoch", str(int(st.epoch)))
        hs("ha_peer_epoch", str(int(st.peer_epoch)))
        hs("ha_lease_until", str(float(st.lease_until)))
        hs("ha_prev_role", st.prev_role)
        hs("ha_manual", "1" if st.manual else "0")
        if st.down_since is None:
            self.store.conn.execute(
                "DELETE FROM ha_state WHERE key='ha_down_since'")
        else:
            hs("ha_down_since", str(float(st.down_since)))
        self.store.conn.commit()

    # ── 单次决策/动作 ──────────────────────────────────────────────────────
    def tick_once(self, now: Optional[float] = None):
        now = time.monotonic() if now is None else now
        st = self.state()
        hb = bool(self.probe_heartbeat())
        lan = bool(self.probe_lan())

        if hb and lan:
            st.down_since = None
        elif st.down_since is None:
            st.down_since = now

        dec = tick(now, hb, lan, st, st.down_since)

        # 应用动作
        if "promote" in dec.actions:
            self._promote(st, now)
        else:
            # 进入 degraded 时记录降级前的稳定角色（用于原主不自愈提升 和 降级恢复）
            if dec.role == ROLE_DEGRADED and st.role != ROLE_DEGRADED:
                st.prev_role = st.role
            st.role = dec.role

        self.save(st)

        if "alarm" in dec.actions:
            from .alerting import emit_alert
            emit_alert(self, dec, st)
        return dec

    def _promote(self, st: HAState, now: float):
        """提升为本节点为新主：开新 epoch、续租约、清对端 epoch。"""
        st.epoch = st.epoch + 1
        st.lease_until = now + LEASE_SECONDS
        st.role = ROLE_ACTIVE
        st.prev_role = ROLE_ACTIVE
        st.down_since = None
        st.peer_epoch = 0
        # local_seq（lsn_seq）保持当前最大值，新 WAL 不与原主区间冲突；
        # applied_max 维持现状（升主后从已回放点继续）。
        logger.info("[ha] 提升为新主，epoch=%s", st.epoch)

    def demote(self, to_safe: bool = False):
        """人工降级（停写）。to_safe=True 进入 safe_mode 等待 reconcile。"""
        st = self.state()
        st.role = ROLE_SAFE if to_safe else ROLE_PASSIVE
        st.prev_role = ROLE_PASSIVE
        self.save(st)
        return st

    def promote(self, now: Optional[float] = None):
        """人工提升为本节点新主（--manual 模式或运维介入用）。"""
        now = time.monotonic() if now is None else now
        st = self.state()
        self._promote(st, now)
        self.save(st)
        return st

    # ── 连续运行 ────────────────────────────────────────────────────────────
    def cycle(self):
        """单次迭代：拉对端 WAL 回放（备/降级态）+ tick 决策。

        供端到端演练（`khub ha drill`）与外部循环驱动；等价于 `_loop_once` 的
        公开入口，避免直接调用私有方法。
        """
        self._loop_once()

    def _loop_once(self):
        st = self.state()
        # 备机/降级态持续从对端拉 WAL 回放（连续热备）
        if st.role in (ROLE_PASSIVE, ROLE_DEGRADED) and self._replica:
            try:
                mgr = ReplicationManager(self.store)
                res = mgr.pull_and_replay(self._replica)
                self.store.ha_set("ha_last_sync",
                                  time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()))
                self.store.conn.commit()
                if res["applied"]:
                    logger.info("[ha] 回放 %s 条变更", res["applied"])
            except Exception as e:  # 拉取/回放失败不应中断主循环
                logger.warning("[ha] pull_and_replay 失败：%s", e)
        self.tick_once()

    def run(self, interval: float = 5.0, blocking: bool = True) -> Scheduler:
        sched = Scheduler()
        sched.add_task("ha_tick", interval, self._loop_once)
        sched.run(blocking=blocking)
        return sched
