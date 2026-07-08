"""分歧检测（reconcile）与安全退出（resolve_split_brain）。

设计依据：docs/disaster_recovery.md vFinal.3 §4.5（脑裂与 reconcile）。

reconcile 比较双机的 replication_log，按 (epoch, lsn) 找出分叉点与冲突行。
resolve_split_brain(keep) 在人工选定权威主后开新 epoch、清除分歧标志。

⚠️ 当前限制（已与计划对齐，避免动摇 P0b）：
- lsn = local_seq（未烘焙 epoch<<48 前缀），epoch 单独存储在 ha_state。
- 因此当两库 ha_epoch 不同时，无法逐行确定每条 WAL 的归属 epoch，
  reconcile 直接报告"不同 epoch，全部分歧"而非逐行比对（见 _rows docstring）。
- 重新设计了 reconcole 流程以确保在相等 epoch 时进行逐行比对，在不同 epoch
  时进行差异报告；未来引入 `lsn = (epoch<<48) | seq` 后可退化为固定前缀扫描。
"""

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
    """读取完整 replication_log，**不含 per-row epoch**（参见模块文档限制）。

    若两库 ha_epoch 不同，reconcile 据此返回"全部分歧"而非逐行比对。
    """
    cur = store.conn.execute(
        "SELECT lsn, op, table_name, row_id, payload, at "
        "FROM replication_log ORDER BY lsn")
    epoch = int(store.ha_get("ha_epoch", "1") or 1)
    return epoch, list(cur)


def _sample(divergent):
    """从分歧行列表中采样最多 10 条。"""
    samples = []
    for side, row in divergent[:10]:
        pl = row["payload"]
        samples.append({
            "side": side,
            "lsn": row["lsn"],
            "op": row["op"],
            "table": row["table_name"],
            "row_id": row["row_id"],
            "payload": pl[:120] if pl else "",
            "payload_truncated": bool(pl and len(pl) > 120),
            "at": row["at"],
        })
    return samples


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

    # ── epoch 不同 → 无法逐行 compare，报告全部分歧 ──
    if le != re_:
        divergent = ([("left", r) for r in lr] +
                     [("right", r) for r in rr])
        report.fork_epoch = min(le, re_)
        report.fork_lsn = 0  # 无法确定分叉点
        report.divergent = len(divergent)
        report.samples = _sample(divergent)
        higher = "left" if le > re_ else "right"
        report.summary = (
            f"不同 epoch（左={le} 右={re_}），无法逐行比对共同前缀。"
            f"全库 {report.divergent} 条分歧行。"
            f"建议：以 epoch 较高侧（{'左' if le > re_ else '右'}）为权威主，"
            f"运行 reconcile --keep {'primary' if le > re_ else 'standby'}")
        return report

    # ── 同 epoch → 逐行对齐扫描 ──
    # key = (epoch, lsn)，此处 epoch 统一为 le==re_
    i = j = 0
    fork_found = False

    while i < len(lr) and j < len(rr):
        kl = lr[i]["lsn"]
        kr = rr[j]["lsn"]
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
    report.samples = _sample(divergent)

    # 生成摘要
    if not fork_found:
        report.summary = "无分叉：两库 (epoch, lsn) 完全一致"
    else:
        report.summary = (
            f"同一 epoch（{le}）内分叉，分叉点 (epoch={report.fork_epoch}, "
            f"lsn={report.fork_lsn})，{report.divergent} 条分歧行。"
            f"建议：以 'primary' 侧为权威，运行 resolve --keep primary")

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
                    (s["table"] or "")[:14], (s["row_id"] or "")[:10],
                    (s["payload"] or "")[:60], trunc))
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
    - **保留 ha_peer 不变**（epoch 轮换 + peer_epoch=0 已足够阻隔陈旧对端）。
    - 设角色为 active（定主后立即承接写入）。
    - 注意：本操作只改本库；对端库需人工另行 resolve。

    Args:
        store: 被定主的 Store 实例。
        keep: "primary"（保持主身份继续写）或 "standby"（切换为新主）。
              两者当前副作用相同（开新 epoch + 定主），保留参数以兼容
              未来可能的行为差异（如 keep=standby 时写应用层降级信号）。

    Returns:
        dict: 操作总结（新 epoch, 原角色, 新角色）。
    """
    if keep not in ("primary", "standby"):
        raise ValueError(f"keep 须为 'primary' 或 'standby'，得到 '{keep}'")

    old_role = store.ha_get("ha_role", "passive")
    if old_role != "safe_mode":
        raise ValueError(
            f"节点当前角色为 '{old_role}'，非 safe_mode。"
            f"只有 safe_mode 下的节点才需 resolve_split_brain；"
            f"如需降级请用 `khub ha demote`")
    if store.applied_max() == 0:
        raise ValueError("applied_max 为 0，库可能未初始化或已损坏")

    old_epoch = int(store.ha_get("ha_epoch", "1") or 1)
    new_epoch = old_epoch + 1

    store.ha_set("ha_epoch", str(new_epoch))
    store.ha_set("ha_role", "active")
    store.ha_set("ha_prev_role", "active")
    store.ha_set("ha_peer_epoch", "0")       # 对端不再是权威
    # 保留 ha_peer 不变（epoch 轮换 + peer_epoch=0 已足够阻隔）
    # 不清除 safe_mode 相关标记（旧版本读过标记的仍可查）
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
        f"请确认对端库已对应 resolve（或对端已不可恢复，降级为新备重同步）。")
