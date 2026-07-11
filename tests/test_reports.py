"""Tests for BI report engine."""
import pytest
from khub.db import Store
from khub.reports import (
    create_template, list_templates, get_template, update_template, delete_template,
    execute, list_jobs, get_job, export_csv, render_chart, build_chart_data,
    validate_query, list_tables, describe_table,
)
pytestmark = pytest.mark.smoke


# ── SQL 安全校验 ──

def test_validate_query_accepts_select():
    assert validate_query("SELECT 1") is not None

def test_validate_query_accepts_with():
    assert validate_query("WITH t AS (SELECT 1) SELECT * FROM t") is not None

def test_validate_query_rejects_insert():
    with pytest.raises(ValueError, match="仅允许"):
        validate_query("INSERT INTO docs VALUES(1)")

def test_validate_query_rejects_drop():
    with pytest.raises(ValueError, match="仅允许"):
        validate_query("DROP TABLE documents")

def test_validate_query_rejects_update():
    with pytest.raises(ValueError, match="仅允许"):
        validate_query("UPDATE documents SET title='x'")

def test_validate_query_empty():
    with pytest.raises(ValueError, match="为空"):
        validate_query("")

def test_validate_query_rejects_alter():
    with pytest.raises(ValueError, match="仅允许"):
        validate_query("ALTER TABLE documents ADD COLUMN x TEXT")

def test_validate_query_rejects_pragma():
    with pytest.raises(ValueError, match="仅允许"):
        validate_query("PRAGMA table_info(documents)")


# ── 模板 CRUD ──

def test_create_template():
    store = Store(":memory:")
    tid = create_template(store, "测试报表", "SELECT 1 as col",
                          description="test", chart_type="table")
    assert tid > 0

def test_list_templates():
    store = Store(":memory:")
    create_template(store, "报表A", "SELECT 1")
    create_template(store, "报表B", "SELECT 2")
    assert len(list_templates(store)) == 2

def test_get_template():
    store = Store(":memory:")
    tid = create_template(store, "测试", "SELECT 1")
    tpl = get_template(store, tid)
    assert tpl is not None
    assert tpl["name"] == "测试"
    assert get_template(store, 999) is None

def test_update_template():
    store = Store(":memory:")
    tid = create_template(store, "原名", "SELECT 1")
    updated = update_template(store, tid, name="新名")
    assert updated["name"] == "新名"
    tpl = get_template(store, tid)
    assert tpl["name"] == "新名"

def test_update_template_not_found():
    store = Store(":memory:")
    with pytest.raises(ValueError, match="不存在"):
        update_template(store, 999, name="x")

def test_delete_template():
    store = Store(":memory:")
    tid = create_template(store, "待删", "SELECT 1")
    delete_template(store, tid)
    assert get_template(store, tid) is None

def test_delete_template_not_found():
    store = Store(":memory:")
    with pytest.raises(ValueError, match="不存在"):
        delete_template(store, 999)

def test_create_template_rejects_dangerous_sql():
    store = Store(":memory:")
    with pytest.raises(ValueError, match="仅允许"):
        create_template(store, "危险", "DROP TABLE documents")


# ── 执行与作业 ──

def test_execute():
    store = Store(":memory:")
    tid = create_template(store, "总数", "SELECT count(*) as total FROM documents")
    result = execute(store, tid)
    assert "rows" in result and "columns" in result
    assert result["columns"] == ["total"]

def test_execute_invalid():
    store = Store(":memory:")
    with pytest.raises(ValueError, match="不存在"):
        execute(store, 999)

def test_execute_with_params():
    store = Store(":memory:")
    # 创建参数化模板
    tid = create_template(store, "参数查询",
        "SELECT '{{val}}' as label, {{num}} as value")
    result = execute(store, tid, params={"val": "hello", "num": 42})
    assert result["row_count"] > 0
    assert result["rows"][0]["label"] == "hello"
    assert result["rows"][0]["value"] == 42

def test_execute_missing_param():
    store = Store(":memory:")
    tid = create_template(store, "缺参", "SELECT '{{x}}'")
    with pytest.raises(ValueError, match="缺少"):
        execute(store, tid, params={"y": "1"})

def test_export_csv():
    store = Store(":memory:")
    tid = create_template(store, "CSV导出",
        "SELECT 'a' as c1, 1 as c2 UNION ALL SELECT 'b', 2")
    csv_data = export_csv(store, tid)
    assert "c1" in csv_data and "c2" in csv_data
    assert "a" in csv_data and "b" in csv_data

def test_export_csv_empty():
    store = Store(":memory:")
    tid = create_template(store, "空报表", "SELECT 1 WHERE 1=0")
    assert export_csv(store, tid) == ""

def test_list_jobs():
    store = Store(":memory:")
    tid = create_template(store, "JT", "SELECT 1")
    execute(store, tid)
    jobs = list_jobs(store, tid=tid)
    assert len(jobs) >= 1
    assert jobs[0]["status"] == "completed"

def test_list_jobs_all():
    store = Store(":memory:")
    jobs = list_jobs(store)
    assert isinstance(jobs, list)

def test_get_job():
    store = Store(":memory:")
    tid = create_template(store, "JG", "SELECT 1")
    execute(store, tid)
    jobs = list_jobs(store, tid=tid)
    if jobs:
        job = get_job(store, jobs[0]["id"])
        assert job is not None
        assert job["id"] == jobs[0]["id"]


# ── 图表渲染 ──

def test_render_chart_table():
    store = Store(":memory:")
    tid = create_template(store, "表格", "SELECT 'a' as c1, 1 as c2", chart_type="table")
    chart = render_chart(store, tid)
    assert chart["type"] == "table"
    assert "rows" in chart

def test_render_chart_bar():
    data = [{"label": "A", "val": 10}, {"label": "B", "val": 20}]
    chart = build_chart_data("bar", ["label", "val"], data)
    assert chart["type"] == "bar"
    assert chart["labels"] == ["A", "B"]
    assert len(chart["datasets"]) == 1

def test_render_chart_pie():
    data = [{"cat": "x", "n": 5}, {"cat": "y", "n": 3}]
    chart = build_chart_data("pie", ["cat", "n"], data)
    assert chart["type"] == "pie"
    assert len(chart["labels"]) == 2

def test_render_chart_line():
    data = [{"d": "2024-01", "v": 100}, {"d": "2024-02", "v": 200}]
    chart = build_chart_data("line", ["d", "v"], data)
    assert chart["type"] == "line"
    assert len(chart["datasets"][0]["data"]) == 2

def test_render_chart_empty():
    chart = build_chart_data("bar", ["x", "y"], [])
    assert chart["type"] == "bar"
    assert chart["labels"] == []


# ── 数据库自省 ──

def test_list_tables():
    store = Store(":memory:")
    # 至少有一些核心表
    tables = list_tables(store)
    assert "documents" in tables

def test_describe_table():
    store = Store(":memory:")
    cols = describe_table(store, "documents")
    assert any(c["name"] == "canonical_id" for c in cols)

def test_describe_table_not_found():
    store = Store(":memory:")
    with pytest.raises(ValueError, match="不存在"):
        describe_table(store, "nonexistent_table")
