"""双机热备（P1）：故障切换控制器、状态机与运维 CLI 支撑。

设计依据：docs/disaster_recovery.md vFinal.3 §4/§9/§10/§13。
本包只负责"热数据"的高可用：心跳双故障域判定、写租约、epoch fencing、
WAL 连续回放、safe mode / reconcile。远程灾备（快照+PITR）在 khub.replication。
"""

from .controller import (
    HAState,
    Decision,
    tick,
    FailoverController,
    build_probes,
)
from .reconcile import reconcile, resolve_split_brain, ReconcileReport, format_report, resolve_summary
from .selftest import run_scenario, run_all, ScenarioResult
from .status import render_status
from .alerting import emit_alert, build_alert

__all__ = [
    "HAState",
    "Decision",
    "tick",
    "FailoverController",
    "build_probes",
    "reconcile",
    "resolve_split_brain",
    "ReconcileReport",
    "format_report",
    "resolve_summary",
    "run_scenario",
    "run_all",
    "ScenarioResult",
    "render_status",
    "emit_alert",
    "build_alert",
]
