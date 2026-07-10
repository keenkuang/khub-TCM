"""HA 自我演练：注入场景运行验证。

设计依据：docs/disaster_recovery.md §4 状态机 + §13 单测要点。
self-test 构造模拟故障、驱动 FailoverController、断言行为符合预期。
"""

import time
from dataclasses import dataclass, field
from typing import Optional

from .controller import (
    FailoverController,
    HAState,
    Decision,
    ROLE_ACTIVE,
    ROLE_PASSIVE,
    ROLE_DEGRADED,
    ROLE_PROMOTING,
    ROLE_SAFE,
)


@dataclass
class ScenarioResult:
    """单个场景结果。"""
    name: str
    passed: bool = False
    steps: list = field(default_factory=list)
    error: str = ""


def _seq(step: int, action: str, detail: str):
    return {"step": step, "action": action, "detail": detail}


SCENARIOS = {
    "link-down": "单域丢失（心跳断/业务网可达）：active→degraded，不提升",
    "promote":  "双域丢失自动提升：passive→promoting→active，epoch+1",
    "split-brain": "epoch fencing：存活节点见更高 epoch → safe_mode",
}


def run_scenario(name: str, fc: FailoverController | None = None) -> ScenarioResult:
    """运行指定场景（需提供 FailoverController 或默认构造临时实例）。

    self-test 用纯 tick() 推断（不下真实探针），避免副作用。
    """
    from ..db import Store
    import tempfile, os

    steps = []
    ok = True
    error = ""

    try:
        if name == "link-down":
            st = HAState(role=ROLE_ACTIVE, epoch=1, down_since=None, prev_role=ROLE_ACTIVE)
            from .controller import tick
            dec1 = tick(time.monotonic(), hb_up=False, lan_up=True, state=st)
            steps.append(_seq(1, "tick(active, hb=0, lan=1)",
                              f"→ {dec1.role}/{dec1.actions}"))
            if dec1.role != ROLE_DEGRADED or "promote" in dec1.actions:
                ok = False
                error = "active+单域丢失应为 degraded 且不包含 promote"
            else:
                # 对端恢复 → back
                dec2 = tick(time.monotonic(), hb_up=True, lan_up=True,
                            state=HAState(role=ROLE_DEGRADED, prev_role=ROLE_ACTIVE, epoch=1))
                steps.append(_seq(2, "tick(degraded, hb=1, lan=1)",
                                  f"→ {dec2.role}/{dec2.actions}"))
                if dec2.role != ROLE_ACTIVE:
                    ok = False
                    error = "degraded+恢复应为 active"

        elif name == "promote":
            st = HAState(role=ROLE_PASSIVE, epoch=1, down_since=0.0, prev_role=ROLE_PASSIVE)
            from .controller import tick
            dec = tick(time.monotonic(), hb_up=False, lan_up=False, state=st, down_since=5.0)
            steps.append(_seq(1, "tick(passive, hb=0, lan=0, down=5s)",
                              f"→ {dec.role}/{dec.actions}"))
            if dec.role != ROLE_PROMOTING or "promote" not in dec.actions:
                ok = False
                error = "passive+双域丢失应为 promoting+promote"
            else:
                steps.append(_seq(2, "断言", "pass Promote action present"))

        elif name == "split-brain":
            st = HAState(role=ROLE_ACTIVE, epoch=3, peer_epoch=5)
            from .controller import tick
            dec = tick(time.monotonic(), hb_up=True, lan_up=True, state=st)
            steps.append(_seq(1, "tick(active, thb=1, lan=1, peer_epoch=5>3)",
                              f"→ {dec.role}/{dec.actions}"))
            if dec.role != ROLE_SAFE:
                ok = False
                error = "见更高 epoch 应为 safe_mode"

        else:
            ok = False
            error = f"未知场景：{name}（可选：link-down / promote / split-brain）"

    except Exception as e:
        ok = False
        error = f"异常：{type(e).__name__}: {e}"

    return ScenarioResult(name=name, passed=ok, steps=steps, error=error)


def run_all(fc: FailoverController | None = None) -> list:
    """运行所有内置场景。"""
    results = []
    for name in SCENARIOS:
        results.append(run_scenario(name, fc))
    return results


def format_selftest(results: list) -> str:
    lines = ["=== khub ha self-test 结果 ==="]
    all_ok = True
    for r in results:
        lines.append(f"  [{ 'PASS' if r.passed else 'FAIL' }] {r.name} — {SCENARIOS.get(r.name, '')}")
        if not r.passed:
            all_ok = False
            lines.append(f"        错误：{r.error}")
        for s in r.steps:
            lines.append(f"        步骤 {s['step']}: {s['action']} → {s['detail']}")
    lines.append(f"── 总计 {len(results)} 个场景，"
                 f"{sum(1 for r in results if r.passed)} 通过 / "
                 f"{sum(1 for r in results if not r.passed)} 失败 ──")
    lines.append("自检通过" if all_ok else f"❌ 部分场景失败，请排查。")
    return "\n".join(lines)
