"""报表引擎——模板 CRUD + 执行 SQL + 导出。"""
from __future__ import annotations
import csv
import io
import json

from .db import Store


def create_template(store: Store, name: str, query: str, description: str = "",
                    chart_type: str = "table", config: str = "") -> int:
    store.conn.execute(
        "INSERT INTO report_templates (name, description, query, chart_type, config) "
        "VALUES (?,?,?,?,?)",
        (name, description, query, chart_type, config))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def list_templates(store: Store) -> list[dict]:
    return store.conn.execute(
        "SELECT * FROM report_templates ORDER BY id DESC").fetchall()


def get_template(store: Store, tid: int) -> dict | None:
    return store.conn.execute(
        "SELECT * FROM report_templates WHERE id=?", (tid,)).fetchone()


def execute(store: Store, tid: int) -> dict:
    """执行报表查询，返回结果。"""
    tpl = get_template(store, tid)
    if not tpl:
        raise ValueError("报表模板不存在")
    try:
        cursor = store.conn.execute(tpl["query"])
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


def export_csv(store: Store, tid: int) -> str:
    """导出 CSV 格式。"""
    result = execute(store, tid)
    if not result.get("rows"):
        return ""
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(result["columns"])
    for r in result["rows"]:
        w.writerow([r.get(c, "") for c in result["columns"]])
    return output.getvalue()
