import os
import tempfile

import pytest

from khub.db import Store
from khub.reports import create_template, list_templates, execute, export_csv


def test_create_template():
    store = Store(":memory:")
    tid = create_template(store, "测试报表", "SELECT 1 as col",
                          description="test", chart_type="table")
    assert tid > 0


def test_list_templates():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        s = Store(tmp.name)
        create_template(s, "报表A", "SELECT 1")
        create_template(s, "报表B", "SELECT 2")
        assert len(list_templates(s)) == 2
    finally:
        os.unlink(tmp.name)


def test_execute():
    store = Store(":memory:")
    tid = create_template(store, "总数",
                          "SELECT count(*) as total FROM documents")
    result = execute(store, tid)
    assert "rows" in result and "columns" in result
    assert result["columns"] == ["total"]


def test_export_csv():
    store = Store(":memory:")
    tid = create_template(
        store, "CSV导出",
        "SELECT 'a' as c1, 1 as c2 UNION ALL SELECT 'b', 2")
    csv_data = export_csv(store, tid)
    assert "c1" in csv_data and "c2" in csv_data
    assert "a" in csv_data and "b" in csv_data


def test_execute_invalid():
    store = Store(":memory:")
    with pytest.raises(ValueError, match="不存在"):
        execute(store, 999)
