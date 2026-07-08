"""分歧检测（reconcile）与安全退出（resolve_split_brain）。

设计依据：docs/disaster_recovery.md vFinal.3 §4.5（脑裂与 reconcile）。

reconcile 比较双机的 replication_log，按 (epoch, lsn) 找出分叉点与冲突行。
resolve_split_brain(keep) 在人工选定权威主后开新 epoch、清除分歧标志。
"""

import json
import time
from dataclasses import dataclass, field
from typing import Optional

from ..db import Store


@dataclass
class ReconcileReport:
    """分歧检测报告。"""
    fork_epoch: int = 0          # 分叉时的 epoch
    fork_lsn: int = 0            # 分叉点的 lsn 边界（之前一致、之后分歧）
    divergent: int = 0           # 分歧行数（两库合计）
    samples: list = field(default_factory=list)  # 最多 10 条冲突行采样
    left_total: int = 0          # 左库 replication_log 总行数
    right_total: int = 0         # 右库总行数
    left_epoch: int = 1          # 左库 ha_epoch
    right_epoch: int = 1         # 右库 ha_epoch
    summary: str = ""


def _rows(store: Store):
    """读取完整 replication_log，按 (epoch, lsn) 排序。"""
    cur = store.conn.execute(
        "SELECT lsn, op, table_name, row_id, payload, at "
        "FROM replication_log ORDER BY lsn")
    epoch = int(store.ha_get("ha_epoch", "1") or 1)
    return epoch, list(cur)


def reconcile(left: Store, right: Store) -> ReconcileReport:
    """按 (epoch, lsn) 比对双机 replication_log，输出分歧报告。

    Args:
        left: 主/左侧库的 Store 实例。
        right: 备/右侧库的 Store 实例。

    Returns:
        ReconcileReport：分叉信息、冲突采样与建议。
    """
    le, lr = _rows(left)
    re_, rr = _rows(right)
    report = ReconcileReport(
        left_total=len(lr),
        right_total=len(rr),
        left_epoch=le,
        right_epoch=re_,
    )

    # 按 (epoch, lsn) 对齐扫描
    def _key(epoch, row):
        return (epoch, row["lsn"])

    i = j = 0
    fork_found = False
    conflicts = []

    while i < len(lr) and j < len(rr):
        kl = _key(le, lr[i])
        kr = _key(re_, rr[j])
        if kl == kr:
            i += 1
            j += 1
        elif kl < kr:
            if not fork_found:
                report.fork_epoch = le
                report.fork_lsn = lr[i]["lsn"]
                fork_found = True
            i += 1
        else:
            if not fork_found:
                report.fork_epoch = re_
                report.fork_lsn = rr[j]["lsn"]
                fork_found = True
            j += 1

    # 采集分歧行
    divergent = []
    while i < len(lr):
        if not fork_found:
            report.fork_epoch = le
            report.fork_lsn = lr[i]["lsn"]
            fork_found = True
        divergent.append(("left", lr[i]))
        i += 1
    while j < len(rr):
        if not fork_found:
            report.fork_epoch = re_
            report.fork_lsn = rr[j]["lsn"]
            fork_found = True
        divergent.append(("right", rr[j]))
        j += 1

    report.divergent = len(divergent)
    for side, row in divergent[:10]:
        report.samples.append({
            "side": side,
            "lsn": row["lsn"],
            "op": row["op"],
            "table": row["table_name"],
            "row_id": row["row_id"],
            "payload": row["payload"][:120] if row["payload"] else "",
            "at": row["at"],
        })
        report.samples[-1]["payload_truncated"] = (
            True if row["payload"] and len(row["payload"]) > 120 else False)

    # 生成摘要
    if not fork_found and le == re_:
        report.summary = "无分叉：两库 (epoch, lsn) 完全一致"
    elif le == re_:
        report.summary = (
            f"同一 epoch（{le}）内分叉，分叉点 (epoch={report.fork_epoch}, "
            f"lsn={report.fork_lsn})，{report.divergent} 条分歧行。"
            f"建议：以 'primary' 侧为权威，运行 resolve --keep primary")
    else:
        report.summary = (
            f"不同 epoch（左={le} 右={re_}），"
            f"分叉点 (epoch={report.fork_epoch}, lsn={report.fork_lsn})，"
            f"{report.divergent} 条分歧行。"
            f"建议：较高 epoch 侧为主，运行 resolve --keep primary|standby")

    return report


def format_report(report: ReconcileReport) -> str:
    """生成人类可读的 reconcile 报告。"""
    lines = [
        "=== khub ha reconcile 报告 ===",
        f"左库 epoch={report.left_epoch}（{report.left_total} 行 WAL）",
        f"右库 epoch={report.right_epoch}（{report.right_total} 行 WAL）",
        "── 分叉摘要 ──",
        f"  {report.summary}",
    ]
    if report.fork_epoch:
        lines.append(f"分叉点    : epoch={report.fork_epoch}  lsn={report.fork_lsn}")
    lines.append(f"分歧行数  : {report.divergent}")
    if report.samples:
        lines.append("── 冲突采样（最多 10 条）──")
        header = "  {:<5} {:<6} {:<8} {:<14} {:<10} {}".format(
            "边", "lsn", "操作", "表", "row_id", "payload（截短）")
        lines.append(header)
        lines.append("  " + "-" * len(header.strip()))
        for s in report.samples:
            trunc = "（截）" if s.get("payload_truncated") else ""
            lines.append(
                "  {:<5} {:<6} {:<8} {:<14} {:<10} {}{}".format(
                    s["side"], s["lsn"], s["op"],
                    s["table"][:14], s["row_id"][:10],
                    s["payload"][:60], trunc))
    lines.append("── 建议 ──")
    if report.divergent == 0:
        lines.append("  无分歧，无需 resolve。")
    else:
        lines.append("  1. 确认以哪一侧为权威主")
        lines.append("  2. 运行 `khub ha resolve --keep primary|standby`")
        lines.append("  3. 确认后新主 `khub ha status` 角色稳定")
    return "\n".join(lines)


def resolve_split_brain(store: Store, keep: str):
    """人工安全退出 safe_mode / 定主。

    - 选定权威主后开新 epoch（epoch+1）。
    - 清除对端 epoch 记录与 safe_mode 标记。
    - 重置 applied_max 到当前（后续 WAL 从新 epoch 续写）。
    - 设角色为 active（定主后立即承接写入）、对端角色标记为 passive。
    - 注意：本操作只改本库；对端库需人工另行 resolve。

    Args:
        store: 被定主的 Store 实例。
        keep: "primary"（保持主身份继续写）或 "standby"（作为新主继续写）。

    Returns:
        dict: 操作总结（新 epoch, 原角色, 新角色）。
    """
    if keep not in ("primary", "standby"):
        raise ValueError(f"keep 须为 'primary' 或 'standby'，得到 '{keep}'")

    old_epoch = int(store.ha_get("ha_epoch", "1") or 1)
    old_role = store.ha_get("ha_role", "passive")

    new_epoch = old_epoch + 1
    store.ha_set("ha_epoch", str(new_epoch))
    store.ha_set("ha_role", "active")
    store.ha_set("ha_prev_role", "active")
    store.ha_set("ha_peer_epoch", "0")       # 对端不再是权威
    store.ha_set("ha_peer", "none")          # 临时清除对端指向
    # 清除 safe_mode / 分歧标志
    if old_role == "safe_mode":
        store.conn.execute(
            "DELETE FROM ha_state WHERE key IN ('ha_safe_reason','ha_divergence')")
    # applied_max 保持当前值（不重置），新 WAL 从新 epoch 续写
    store.set_applied_max(store.applied_max())
    store.conn.commit()

    return {
        "old_epoch": old_epoch,
        "new_epoch": new_epoch,
        "old_role": old_role,
        "new_role": "active",
        "action": f"resolve_split_brain(keep={keep})",
    }


def resolve_summary(result: dict) -> str:
    return (
        f"已 resolve safe_mode：epoch {result['old_epoch']} → {result['new_epoch']}，"
        f"{result['old_role']} → {result['new_role']}。"
        f"请确认对端库已对应 resolve。")
