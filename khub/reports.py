"""报表引擎——模板 CRUD + 执行 SQL + 导出 + 图表渲染。"""
from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from .db import Store


# ── SQL 安全校验 ─────────────────────────────────────────────

def validate_query(query: str) -> str:
    """校验 SQL 查询安全性，仅允许 SELECT / WITH 只读语句。

    Raises ValueError 若含危险关键字。返回清理后的 SQL。
    """
    stripped = query.strip().lstrip()
    if not stripped:
        raise ValueError("查询语句为空")
    # 检查是否以 SELECT 或 WITH 开头
    if not (stripped.upper().startswith("SELECT") or stripped.upper().startswith("WITH")):
        raise ValueError("仅允许 SELECT / WITH 查询")
    # 禁止危险关键字（忽略字符串内匹配）
    dangerous = re.compile(
        r'\b(INSERT|UPDATE|DELETE|DROP\s+TABLE|ALTER\s+TABLE|PRAGMA|'
        r'ATTACH|DETACH|REINDEX|REPLACE|VACUUM)\b',
        re.IGNORECASE,
    )
    if dangerous.search(stripped):
        raise ValueError("查询包含不允许的 SQL 操作")
    return stripped


def _substitute_params(query: str, params: dict[str, Any] | None) -> str:
    """替换 SQL 中的 ``{{param}}`` 占位符。

    - ``'{{param}}'`` — 已加引号的占位符，替换为值的原始字符串
    - ``{{param}}`` — 裸占位符，字符串自动加单引号并转义
    """
    if not params:
        return query

    def _val(key: str) -> str:
        if key not in params:
            raise ValueError(f"缺少参数: {key}")
        val = params[key]
        if val is None:
            return "NULL"
        if isinstance(val, bool):
            return "1" if val else "0"
        if isinstance(val, (int, float)):
            return str(val)
        return str(val).replace("'", "''")

    # 第一遍：替换带引号的 '{{param}}' — 保留外层引号，只替换内部占位符
    query = re.sub(
        r"'{{(\w+)}}'",
        lambda m: "'" + _val(m.group(1)) + "'",
        query,
    )
    # 第二遍：替换裸 {{param}} — 字符串值自动加单引号
    def _bare_replacer(m: re.Match) -> str:
        key = m.group(1)
        if key not in params:
            raise ValueError(f"缺少参数: {key}")
        val = params[key]
        if val is None:
            return "NULL"
        if isinstance(val, bool):
            return "1" if val else "0"
        if isinstance(val, (int, float)):
            return str(val)
        escaped = str(val).replace("'", "''")
        return "'" + escaped + "'"

    query = re.sub(r'\{\{(\w+)\}\}', _bare_replacer, query)
    return query


# ── 模板 CRUD ────────────────────────────────────────────────

def create_template(store: Store, name: str, query: str,
                    description: str = "",
                    chart_type: str = "table",
                    config: str = "") -> int:
    """创建报表模板。返回新模板 ID。"""
    validate_query(query)
    store.conn.execute(
        "INSERT INTO report_templates "
        "(name, description, query, chart_type, config) "
        "VALUES (?,?,?,?,?)",
        (name, description, query, chart_type, config))
    return store.conn.execute(
        "SELECT last_insert_rowid()").fetchone()[0]


def list_templates(store: Store) -> list[dict]:
    """列出所有报表模板（按创建时间倒序）。"""
    rows = store.conn.execute(
        "SELECT * FROM report_templates ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def get_template(store: Store, tid: int) -> dict | None:
    """获取单个模板详情。"""
    row = store.conn.execute(
        "SELECT * FROM report_templates WHERE id=?", (tid,)).fetchone()
    return dict(row) if row else None


def update_template(store: Store, tid: int, *, name: str | None = None,
                    query: str | None = None,
                    description: str | None = None,
                    chart_type: str | None = None,
                    config: str | None = None) -> dict | None:
    """更新报表模板字段。只更新提供的字段。返回更新后的模板。"""
    existing = get_template(store, tid)
    if not existing:
        raise ValueError("报表模板不存在")
    fields = {
        "name": name,
        "query": query,
        "description": description,
        "chart_type": chart_type,
        "config": config,
    }
    updates = {k: v for k, v in fields.items() if v is not None}
    if not updates:
        return existing
    if "query" in updates:
        validate_query(updates["query"])
    set_clause = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [tid]
    store.conn.execute(
        f"UPDATE report_templates SET {set_clause} WHERE id=?", vals)
    return get_template(store, tid)


def delete_template(store: Store, tid: int) -> None:
    """删除报表模板及其关联执行记录。"""
    existing = get_template(store, tid)
    if not existing:
        raise ValueError("报表模板不存在")
    store.conn.execute("DELETE FROM report_jobs WHERE template_id=?", (tid,))
    store.conn.execute("DELETE FROM report_templates WHERE id=?", (tid,))


# ── 执行与作业 ───────────────────────────────────────────────

def execute(store: Store, tid: int, *,
            params: dict[str, Any] | None = None) -> dict:
    """执行报表查询，支持 ``{{param}}`` 参数替换。

    返回::

        {
            "template_id": int,
            "name": str,
            "columns": [str],
            "rows": [dict],
            "row_count": int,
        }
    """
    tpl = get_template(store, tid)
    if not tpl:
        raise ValueError("报表模板不存在")
    safe_query = validate_query(tpl["query"])
    final_query = _substitute_params(safe_query, params)
    try:
        cursor = store.conn.execute(final_query)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if rows else []
        result = {
            "template_id": tid,
            "name": tpl["name"],
            "columns": columns,
            "rows": [dict(r) for r in rows],
            "row_count": len(rows),
        }
        store.conn.execute(
            "INSERT INTO report_jobs (template_id, status, output) "
            "VALUES (?, 'completed', ?)",
            (tid, json.dumps(result, ensure_ascii=False)))
        return result
    except Exception as e:
        store.conn.execute(
            "INSERT INTO report_jobs (template_id, status, error) "
            "VALUES (?, 'failed', ?)",
            (tid, str(e)))
        raise


def list_jobs(store: Store, tid: int | None = None,
              limit: int = 50) -> list[dict]:
    """列出执行记录。可指定模板 ID 筛选。"""
    if tid is not None:
        rows = store.conn.execute(
            "SELECT * FROM report_jobs WHERE template_id=? "
            "ORDER BY id DESC LIMIT ?", (tid, limit)).fetchall()
    else:
        rows = store.conn.execute(
            "SELECT * FROM report_jobs ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_job(store: Store, jid: int) -> dict | None:
    """获取单条执行记录详情。"""
    row = store.conn.execute(
        "SELECT * FROM report_jobs WHERE id=?", (jid,)).fetchone()
    return dict(row) if row else None


def export_csv(store: Store, tid: int, *,
               params: dict[str, Any] | None = None) -> str:
    """导出 CSV 格式。"""
    result = execute(store, tid, params=params)
    if not result.get("rows"):
        return ""
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(result["columns"])
    for r in result["rows"]:
        w.writerow([r.get(c, "") for c in result["columns"]])
    return output.getvalue()


# ── 图表渲染 ─────────────────────────────────────────────────

def render_chart(store: Store, tid: int, *,
                 params: dict[str, Any] | None = None) -> dict:
    """执行查询并将结果转为图表友好格式。

    返回::

        {
            "type": "table" | "bar" | "pie" | "line",
            "labels": [str],
            "datasets": [{"label": str, "data": [mixed]}],
            "columns": [str],
        }
    """
    tpl = get_template(store, tid)
    if not tpl:
        raise ValueError("报表模板不存在")
    chart_type = tpl.get("chart_type", "table")
    safe_query = validate_query(tpl["query"])
    final_query = _substitute_params(safe_query, params)
    cursor = store.conn.execute(final_query)
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description] if rows else []
    data = [dict(r) for r in rows]
    return _build_chart(chart_type, columns, data)


def build_chart_data(chart_type: str, columns: list[str],
                     data: list[dict]) -> dict:
    """公开的图表数据构建函数，供 prebuilt.py 等模块直接使用。"""
    return _build_chart(chart_type, columns, data)


def _build_chart(chart_type: str, columns: list[str],
                 data: list[dict]) -> dict:
    """将行数据转为指定图表类型的结构。"""
    if not columns or not data:
        return {
            "type": chart_type,
            "labels": [],
            "datasets": [],
            "columns": columns,
        }
    if chart_type == "table":
        return {
            "type": "table",
            "labels": [],
            "datasets": [],
            "columns": columns,
            "rows": data,
        }
    # bar / pie / line：第一列作为 labels，其余列作为 datasets
    labels = [str(r[columns[0]]) for r in data]
    datasets = []
    for col in columns[1:]:
        series = []
        for r in data:
            val = r[col]
            series.append(val if val is not None else 0)
        datasets.append({"label": col, "data": series})
    return {
        "type": chart_type,
        "labels": labels,
        "datasets": datasets,
        "columns": columns,
    }


# ── 数据库自省 ───────────────────────────────────────────────

def list_tables(store: Store) -> list[str]:
    """列出数据库中所有用户表（排除 sqlite_* 系统表）。"""
    rows = store.conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name").fetchall()
    return [r["name"] for r in rows]


def describe_table(store: Store, table: str) -> list[dict]:
    """获取表结构：列名、类型、是否可为空、默认值、是否主键。"""
    cursor = store.conn.execute(f"PRAGMA table_info('{table}')")
    rows = cursor.fetchall()
    if not rows:
        raise ValueError(f"表不存在: {table}")
    columns_info = []
    for r in rows:
        columns_info.append({
            "cid": r["cid"],
            "name": r["name"],
            "type": r["type"],
            "notnull": bool(r["notnull"]),
            "dflt_value": r["dflt_value"],
            "pk": bool(r["pk"]),
        })
    return columns_info
