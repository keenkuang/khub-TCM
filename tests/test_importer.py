"""老问诊系统数据导入器测试。"""

import os
import tempfile

from khub.db import Store
from khub.importer import LegacyImporter


def _make_excel(headers: list[str], rows: list[list]):
    """用 openpyxl 创建内存 Excel 并返回路径。"""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    path = os.path.join(tempfile.mkdtemp(), "test.xlsx")
    wb.save(path)
    return path


class TestExcelImport:
    def test_basic_import(self):
        s = Store()
        path = _make_excel(
            ["姓名", "性别", "诊断", "处方", "主诉", "辨证"],
            [["张三", "男", "太阳病", "桂枝汤", "发热", "表虚"],
             ["李四", "女", "少阳病", "小柴胡汤", "口苦", "半表半里"]]
        )
        imp = LegacyImporter(s)
        result = imp.import_excel(path)
        assert result["patients"] == 2
        assert result["records"] == 2
        assert result["consultations"] == 2
        assert len(result["errors"]) == 0

    def test_dry_run(self):
        s = Store()
        path = _make_excel(
            ["姓名", "性别", "诊断"],
            [["张三", "男", "太阳病"]]
        )
        imp = LegacyImporter(s)
        result = imp.import_excel(path, dry_run=True)
        assert result["patients"] == 1
        assert result["records"] == 1
        # dry_run 不应实际写入
        assert s.conn.execute(
            "SELECT count(*) FROM documents").fetchone()[0] == 0

    def test_empty_rows(self):
        s = Store()
        path = _make_excel(["姓名"], [])
        imp = LegacyImporter(s)
        result = imp.import_excel(path)
        assert result["patients"] == 0

    def test_auto_pid(self):
        s = Store()
        path = _make_excel(["姓名", "主诉"], [["王五", "头痛"]])
        imp = LegacyImporter(s)
        result = imp.import_excel(path)
        assert result["patients"] == 1
        assert result["consultations"] == 1

    def test_missing_optional_fields(self):
        s = Store()
        path = _make_excel(["姓名"], [["赵六"]])
        imp = LegacyImporter(s)
        result = imp.import_excel(path)
        assert result["patients"] == 1
        assert result["records"] == 0
        assert result["consultations"] == 0

    def test_fuzzy_header_matching(self):
        s = Store()
        path = _make_excel(
            ["患者编号", "姓名", "出生日期", "中医辨证", "中药方"],
            [["P001", "张三", "1980-01-01", "湿热", "龙胆泻肝汤"]]
        )
        imp = LegacyImporter(s)
        result = imp.import_excel(path)
        assert result["patients"] == 1
        assert result["consultations"] == 1
        assert result["records"] == 1


class TestHTMLImport:
    def test_html_table(self):
        s = Store()
        html = """<html><body><table>
<tr><th>姓名</th><th>诊断</th><th>主诉</th></tr>
<tr><td>张三</td><td>太阳病</td><td>发热</td></tr>
</table></body></html>"""
        imp = LegacyImporter(s)
        result = imp.import_html(html)
        assert result["patients"] == 1
        assert result["records"] == 1
        assert result["consultations"] == 1

    def test_html_missing_table(self):
        s = Store()
        imp = LegacyImporter(s)
        try:
            imp.import_html("<html><body>无表格</body></html>")
            assert False, "应抛出异常"
        except ValueError as e:
            assert "表格" in str(e)

    def test_html_file(self):
        s = Store()
        d = tempfile.mkdtemp()
        path = os.path.join(d, "test.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write("""<table>
<tr><th>姓名</th><th>处方</th></tr>
<tr><td>李四</td><td>麻黄汤</td></tr>
</table>""")
        imp = LegacyImporter(s)
        result = imp.import_html(path)
        assert result["patients"] == 1
        assert result["records"] == 1


class TestColMap:
    def test_exact_match(self):
        imp = LegacyImporter(Store())
        m = imp._build_col_map(["姓名", "诊断", "处方"])
        assert m["name"] == 0
        assert m["diagnosis"] == 1
        assert m["prescription"] == 2

    def test_no_match(self):
        imp = LegacyImporter(Store())
        m = imp._build_col_map(["无关列1", "无关列2"])
        assert len(m) == 0

    def test_duplicate_match(self):
        """当一列同时匹配多个字段时不应抛异常。"""
        imp = LegacyImporter(Store())
        m = imp._build_col_map(["辨证"])  # 可匹配 differentiation 和 syndrome
        assert "differentiation" in m
