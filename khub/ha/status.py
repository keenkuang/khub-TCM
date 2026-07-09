"""khub ha status：人类可读的高可用状态报告。

依据设计 §10：切换告警含 5 字段——① 当前角色 ② 最后同步时间
③ 对端失联时长 ④ safe mode 状态 ⑤ 建议动作（附决策树）。
"""

from .controller import FailoverController, ROLE_SAFE


def _suggest(st, dec) -> str:
    """依据状态给出建议动作（含简短决策树）。"""
    if st.role == ROLE_SAFE:
        return ("进入 safe_mode：停止写入，运行 `khub ha reconcile --left <本库> "
                "--right <对端库>` 比对分叉，再用 `khub ha resolve --keep "
                "primary|standby` 定主后恢复。")
    if st.role == "promoting":
        return "正在提升为新主，稍后 `khub ha status` 确认角色变为 active。"
    if st.role == "degraded":
        if "await_manual_promote" in dec.actions:
            return ("对端疑似死亡（双故障域），但 --manual 模式：请确认对端确已宕机后，"
                    "手动 `khub ha promote` 提升。")
        return ("单/双故障域丢失，已进 degraded：先 `khub ha status` 观察，"
                "若为网络抖动待对端恢复自动回到原角色；若确为对端死且开启自动提升，"
                "将自动提升。")
    if st.role == "active":
        remain = max(0.0, st.lease_until - _mono())
        return (f"本节点为主（active），租约剩余 {remain:.0f}s；"
                f"正常承接写入。")
    # passive
    return ("本节点为备（passive），持续从对端回放 WAL；无需操作。")


def _mono():
    import time
    return time.monotonic()


def render_status(fc: FailoverController) -> str:
    st = fc.state()
    last_sync = fc.store.ha_get("ha_last_sync", "—")
    down_s = st.peer_down_s(_mono())
    safe = st.role == ROLE_SAFE

    # 基于当前角色生成建议（不触发探针副作用）
    suggest = _suggest(st, _fake_dec(st))

    lines = [
        "=== khub ha status ===",
        f"当前角色     : {st.role}",
        f"epoch        : {st.epoch}（对端观测 epoch={st.peer_epoch}）",
        f"最后同步时间 : {last_sync}",
        f"对端失联时长 : {down_s:.0f}s" if st.down_since is not None
        else "对端失联时长 : 0s（链路正常）",
        f"safe mode    : {'是' if safe else '否'}",
        f"自动提升     : {'关（--manual）' if st.manual else '开'}",
        f"租约        : {'持有' if st.lease_until > _mono() else '未持/过期'}",
        "── 建议动作 ──",
        f"  {suggest}",
    ]
    return "\n".join(lines)


def _fake_dec(st):
    """构造一个仅含 actions 的占位 Decision，供 _suggest 使用。"""
    from .controller import Decision
    actions = []
    if st.role == ROLE_SAFE:
        actions = ["reconcile"]
    elif st.role == "degraded" and st.down_since is not None:
        actions = ["await_manual_promote"] if st.manual else ["promote"]
    return Decision(st.role, actions)
