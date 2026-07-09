"""行级 Diff 算法（LCS 变体），零外部依赖。

用法::

    from .diff import diff_lines
    result = diff_lines(old_text, new_text)
    for line in result:
        print(line["type"], line["content"])
"""

from __future__ import annotations

from typing import Generator


def diff_lines(old: str, new: str) -> list[dict]:
    """计算两段文本的行级差异。

    Args:
        old: 旧版本文本。
        new: 新版本文本。

    Returns:
        list[dict]: [{"type": "equal"|"insert"|"delete", "content": str, "old_ln": int, "new_ln": int}, ...]
    """
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    return _lcs_diff(old_lines, new_lines)


def _lcs_diff(a: list[str], b: list[str]) -> list[dict]:
    """基于 LCS 的行级 diff 实现。"""
    m, n = len(a), len(b)
    # 构建 LCS 长度表
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    # 回溯构建结果
    result: list[dict] = []
    i, j = m, n
    oi, ni = 0, 0  # 当前行号追踪

    # 用栈暂存逆序结果
    stack = []
    while i > 0 or j > 0:
        if i > 0 and j > 0 and a[i - 1] == b[j - 1]:
            stack.append({"type": "equal", "content": a[i - 1],
                          "old_ln": i, "new_ln": j})
            i -= 1
            j -= 1
        elif j > 0 and (i == 0 or dp[i][j - 1] >= dp[i - 1][j]):
            stack.append({"type": "insert", "content": b[j - 1],
                          "old_ln": None, "new_ln": j})
            j -= 1
        elif i > 0:
            stack.append({"type": "delete", "content": a[i - 1],
                          "old_ln": i, "new_ln": None})
            i -= 1

    while stack:
        result.append(stack.pop())
    return result


def diff_to_html(diff: list[dict]) -> str:
    """将 diff 结果渲染为并排 HTML。"""
    lines_html = ""
    for d in diff:
        cls = d["type"]
        old_ln = str(d["old_ln"]) if d["old_ln"] else ""
        new_ln = str(d["new_ln"]) if d["new_ln"] else ""
        content = d["content"].rstrip("\n").rstrip("\r")
        content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if cls == "equal":
            bg = "background:#fff"
        elif cls == "insert":
            bg = "background:#e6ffed"
        else:  # delete
            bg = "background:#ffeef0"
        lines_html += (
            f'<div style="{bg};display:flex;font-family:monospace;font-size:13px;'
            f'border-bottom:1px solid #f0f0f0">'
            f'<span style="width:40px;text-align:right;padding:0 8px;color:#999;'
            f'user-select:none">{old_ln}</span>'
            f'<span style="width:40px;text-align:right;padding:0 8px;color:#999;'
            f'user-select:none">{new_ln}</span>'
            f'<span style="flex:1;padding:0 8px;white-space:pre-wrap">{content}</span>'
            f'</div>'
        )
    return lines_html
