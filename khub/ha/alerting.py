"""高可用告警（设计 §10）：5 字段告警 + 持久化最近一次告警。

5 字段：① 当前角色 ② 最后同步时间 ③ 对端失联时长 ④ safe mode 状态
⑤ 建议动作（附决策树）。告警写入 ha_state(ha_last_alert) 并打到日志/标准输出，
便于接入外部监控系统（抓取 ha_last_alert 或进程日志）。
"""

import json
import time

from .controller import FailoverController, ROLE_SAFE


def build_alert(fc: FailoverController, dec, st) -> dict:
    """生成符合 §10 的 5 字段告警 dict。"""
    last_sync = fc.store.ha_get("ha_last_sync", "—")
    down_s = st.peer_down_s(time.monotonic())
    action = _action_hint(dec, st)
    return {
        "role": st.role,
        "last_sync": last_sync,
        "peer_down_s": round(down_s, 1),
        "safe_mode": st.role == ROLE_SAFE,
        "suggested_action": action,
        "reason": dec.reason,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
    }


def _action_hint(dec, st) -> str:
    if st.role == ROLE_SAFE:
        return "停写并 reconcile：khub ha reconcile --left <本库> --right <对端库>"
    if "promote" in dec.actions:
        return "已自动提升为新主（epoch 已自增）"
    if "await_manual_promote" in dec.actions:
        return "对端死（双域）但 --manual：人工确认后 khub ha promote"
    if st.role == "degraded":
        return "观察网络；对端恢复自动回原角色，确为死则自动/手动提升"
    return "无"


def emit_alert(fc: FailoverController, dec, st):
    """发出告警：打印 + 持久化到 ha_state(ha_last_alert)。"""
    alert = build_alert(fc, dec, st)
    payload = json.dumps(alert, ensure_ascii=False)
    fc.store.ha_set("ha_last_alert", payload)
    fc.store.conn.commit()
    print(f"[HA ALERT] {payload}", flush=True)
    return alert
